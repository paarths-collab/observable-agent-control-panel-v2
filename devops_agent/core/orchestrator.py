"""
Orchestrator: the central brain of Observable Agent Control Panel.
Handles triage, LLM routing, tool execution, and memory evolution.
"""

import json
import time
from typing import Any, Dict, List, Optional

from devops_agent.core.llm_client import LLMClient
from observable_agent_panel.core.observability import (
    log_triage,
    log_tool_call,
    log_memory_update,
    log_hop,
    log_error,
    log_info,
)
from observable_agent_panel.core.trace_db import trace_db
from devops_agent.memory.long_term import LongTermMemory
from devops_agent.memory.short_term import ShortTermMemory
from devops_agent.tools.registry import get_tool_schemas, execute_tool
from devops_agent.tools.github_tools import get_closed_prs, fetch_pr_diff, get_repo_issues

MAX_TOOL_HOPS = 5
HIGH_CONFIDENCE = 0.80
HYBRID_THRESHOLD = 0.55

SYSTEM_PROMPT_TOOLS = """You are an expert DevOps reliability engineer operating inside an observable agent control plane.

You have access to tools: local log reading, GitHub PR/issue search, StackExchange search, and Python syntax checks.

Follow this reasoning protocol on every turn:
Thought: What is the user actually asking? What do I know vs. what do I need to find?
Action: Which single tool gives me the most signal right now?
Observation: What did the tool return? Is it relevant or noise?
Thought: Does this answer the query, or do I need another hop?
Action: (next tool if needed, or synthesize if sufficient)
Final Answer: Cite every source used (PR #number, log line, StackExchange link). Be specific and actionable.

Rules:
- STRICT RULE: You must ONLY use the provided MCP tools. Do NOT use external web search, general knowledge, or any capabilities not explicitly listed in your tool registry.
- ALWAYS use MCP tools first for any repository, code, or diagnostic queries.
- NEVER fall back to web search unless explicitly instructed.
- If an MCP tool returns an error, report the error — do not silently switch to web search.
- Never guess when a tool can verify.
- If a tool returns empty or errors, explicitly state that and try the next best option.
- If you exhaust all tools without resolution, say exactly what you tried, what failed, and what the user should check manually.
- Always end with a concrete next action the user can take.
- For 'summarize' or 'overview' requests: Prioritize using available memory (MEMORY_JSON) over fetching new data. Do NOT call 'index_repo_prs' or 'index_repo_issues' for these queries if memory context is available; simply summarize the stored PRs/Issues."""

SYSTEM_PROMPT_MEMORY = """You are an expert DevOps reliability engineer with direct access to your team's institutional memory.

You have seen this exact class of issue before. A high-confidence memory match has been retrieved.

Follow this reasoning protocol:
Thought: Does the retrieved memory directly answer this query, or is it a partial match?
Verify: Identify the specific PR number, issue ID, or fix described in memory.
Answer: State the known fix immediately, grounded in the memory fact.
Caveat: If the memory is a partial match, explicitly say so and state what might have changed.

Rules:
- STRICT RULE: You must ONLY use the information provided in the retrieved memory. Do NOT supplement with external knowledge or search.
- Be concise and actionable. The user needs the fix, not a summary.
- Always cite the source (PR #number or issue ID) from devops_agent.memory.
- If the memory match explains a root cause, state the root cause first, then the fix.
- Never fabricate details not present in the retrieved memory."""


class Orchestrator:
    """
    Main control loop:
      1. Triage (semantic search across fixed and temp memory)
      2. Route (memory vs tools)
      3. Execute tools if needed (with hop limit)
      4. Evolve memory (save new facts)
    """

    def __init__(self, llm_client: LLMClient, long_term: LongTermMemory) -> None:
        self.llm = llm_client
        self.memory = long_term  # Fixed (Permanent)
        self.temp_memory = LongTermMemory(db_path=":memory:")  # Temp (Session-only)
        self.short_term = ShortTermMemory(max_turns=4)

    def _get_scoped_prompt(self, base_prompt: str) -> str:
        """Inject current knowledge scope into the system prompt."""
        indexed = self.memory.get_indexed_repos()
        repo_list = ", ".join(indexed) if indexed else "None (New system)"
        
        scope = f"\n\n[KNOWLEDGE BOUNDARY]\n"
        scope += f"Repositories currently in your Institutional Memory: [{repo_list}]\n"
        scope += "CRITICAL RULE: If a user asks a question about a repository NOT in the list above, you have ZERO 'Institutional Memory' for it. "
        scope += "If your initial tool searches for an unknown repo return 'empty', DO NOT keep looping. "
        scope += "Immediately inform the user that the repo is not yet indexed and they should run 'index prs <repo>' to teach you about it."
        
        return base_prompt + scope

    def process_query(self, user_query: str) -> str:
        """
        End-to-end processing of a user query.
        Returns the final text response.
        """
        # Start a persistent trace for this run
        trace_db.start_trace(user_query)

        # ------------------------------------------------------------------
        # 1. TRIAGE
        # ------------------------------------------------------------------
        fixed_matches = self.memory.search_memory(user_query, top_k=10)
        temp_matches = self.temp_memory.search_memory(user_query, top_k=10)
        all_matches = sorted(fixed_matches + temp_matches, key=lambda x: x["score"], reverse=True)
        
        # ── Summary Keyword Bypass ──────────────────────────────────────────
        summary_keywords = ["summarize", "overview", "summary", "summarise"]
        is_summary_request = any(kw in user_query.lower() for kw in summary_keywords)
        
        similarity = all_matches[0]["score"] if all_matches else 0.0

        if is_summary_request and all_matches:
            decision = "memory_only (forced summary)"
            log_triage(similarity, HIGH_CONFIDENCE, decision)
            trace_db.update_triage(similarity, decision)
            trace_db.set_memory_facts([m.get("issue", "") for m in all_matches])
            return self._route_memory(user_query, all_matches)

        if similarity >= HIGH_CONFIDENCE:
            decision = "memory_only"
            log_triage(similarity, HIGH_CONFIDENCE, decision)
            trace_db.update_triage(similarity, decision)
            trace_db.set_memory_facts([m.get("issue", "") for m in all_matches[:4]])
            return self._route_memory(user_query, all_matches[:4])
        if similarity >= HYBRID_THRESHOLD:
            decision = "hybrid"
            log_triage(similarity, HYBRID_THRESHOLD, decision)
            trace_db.update_triage(similarity, decision)
            trace_db.set_memory_facts([m.get("issue", "") for m in all_matches[:4]])
            return self._route_hybrid(user_query, all_matches[:4])

        decision = "tools_only"
        log_triage(similarity, HYBRID_THRESHOLD, decision)
        trace_db.update_triage(similarity, decision)
        return self._route_tools(user_query)

    def _route_memory(self, user_query: str, matches: List[Dict[str, Any]]) -> str:
        """High-confidence memory match: bypass tools, answer directly."""
        memory_json = self._format_memory_context(matches)
        prompt = self._get_scoped_prompt(SYSTEM_PROMPT_MEMORY)
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": prompt},
            {"role": "system", "content": f"[MEMORY_JSON]\n{memory_json}"},
            {"role": "user", "content": user_query},
        ]
        answer = self.llm.simple_chat(messages)
        explanation = (
            f"The agent routed to MEMORY-ONLY because the similarity score ({matches[0].get('score', 0):.3f}) "
            f"exceeded the high-confidence threshold ({HIGH_CONFIDENCE}). "
            f"The answer was drawn directly from {len(matches)} indexed memory fact(s) with no tool calls."
        )
        trace_db.finalize_trace(answer, hop_limit_hit=False, explanation=explanation)
        self.short_term.add("user", user_query)
        self.short_term.add("assistant", answer)
        return answer

    def _route_hybrid(self, user_query: str, matches: List[Dict[str, Any]]) -> str:
        """
        Partial confidence: inject memory plus tools.
        """
        memory_json = self._format_memory_context(matches)
        prompt = self._get_scoped_prompt(SYSTEM_PROMPT_TOOLS)
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": prompt},
            {"role": "system", "content": f"[MEMORY_JSON]\n{memory_json}"},
            {"role": "user", "content": user_query},
        ]
        return self._run_tool_loop(user_query, messages)

    def _route_tools(self, user_query: str) -> str:
        """
        Low-confidence: tools-first routing.
        """
        prompt = self._get_scoped_prompt(SYSTEM_PROMPT_TOOLS)
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_query},
        ]
        return self._run_tool_loop(user_query, messages)

    def _run_tool_loop(self, user_query: str, messages: List[Dict[str, Any]]) -> str:
        """Execute tool-calling loop with hop limits and persistent trace logging."""
        tools = get_tool_schemas()
        tool_results_log: List[str] = []
        hops = 0

        while hops < MAX_TOOL_HOPS:
            hops += 1
            log_hop(hops, MAX_TOOL_HOPS)

            response = self.llm.chat(messages, tools=tools, tool_choice="auto")
            choice = response["choices"][0]
            message = choice["message"]

            tool_calls = message.get("tool_calls")
            if not tool_calls:
                final_answer = message.get("content", "")
                self.short_term.add("user", user_query)
                self.short_term.add("assistant", final_answer)
                if tool_results_log:
                    self._evolve_memory(user_query, tool_results_log, final_answer)
                explanation = self._generate_explanation(user_query, hops, tool_results_log)
                trace_db.finalize_trace(final_answer, hop_limit_hit=False, explanation=explanation)
                return final_answer

            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                try:
                    arguments = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    arguments = {}

                t_start = time.monotonic()
                if tool_name == "index_repo_prs":
                    result = self.index_repo_prs(
                        repo=arguments.get("repo"),
                        count=arguments.get("count", 5),
                        storage=arguments.get("storage", "permanent")
                    )
                elif tool_name == "index_repo_issues":
                    result = self.index_repo_issues(
                        repo=arguments.get("repo"),
                        count=arguments.get("count", 5),
                        storage=arguments.get("storage", "permanent")
                    )
                else:
                    result = execute_tool(tool_name, arguments)
                latency_ms = (time.monotonic() - t_start) * 1000

                result_status = result.get("status", "unknown")
                log_tool_call(tool_name, arguments, result_status)
                # Persist hop to trace
                trace_db.log_hop(tool_name, arguments, result_status, latency_ms)

                if tool_name == "search_github_prs" and result_status == "empty":
                    repo_arg = arguments.get("repo")
                    indexed = self.memory.get_indexed_repos()
                    
                    repo_arg = arguments.get("repo")
                    indexed = self.memory.get_indexed_repos()
                    
                    if repo_arg and repo_arg not in indexed:
                        # Hard stop for unknown repos - Feature 2: Self-Healing Protocol
                        stop_msg = f"Error: Repository '{repo_arg}' not found in institutional memory."
                        log_error(f"Unknown repo block: {repo_arg}")
                        
                        # Finalize the trace immediately with the failure
                        explanation = self._generate_explanation(user_query, hops, tool_results_log + [f"{tool_name}: REPO_NOT_FOUND"])
                        trace_db.log_hop(tool_name, arguments, "error", 0)
                        trace_db.finalize_trace(stop_msg, explanation=explanation)
                        
                        return stop_msg + " This failure has been logged for deep analysis. Please run 'get_failure_candidates' to diagnose."
                    else:
                        messages.append({"role": "system", "content": "Search returned no results."})

                result_json = json.dumps(result)
                tool_results_log.append(f"{tool_name}: {result_json[:500]}")
                messages.append(
                    {
                        "role": "assistant",
                        "content": message.get("content", ""),
                        "tool_calls": [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(arguments),
                                },
                            }
                        ],
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result_json,
                    }
                )

        error_msg = (
            "System Error: Reached maximum tool execution limit. "
            "Please refine your query."
        )
        log_error(error_msg)
        explanation = self._generate_explanation(user_query, hops, tool_results_log)
        trace_db.finalize_trace(error_msg, hop_limit_hit=True, explanation=explanation)
        return error_msg

    def _generate_explanation(self, query: str, hops: int, tool_results: List[str]) -> str:
        """Feature 5: one-paragraph plain-English explanation of what the agent did."""
        summary_lines = [f"Query: '{query[:100]}'", f"Hops executed: {hops}"]
        if tool_results:
            summary_lines.append("Tool results summary: " + " | ".join(tool_results)[:300])
        prompt = [
            {"role": "system", "content": (
                "You are a DevOps observability assistant. In exactly one paragraph, "
                "explain in plain English what the agent did, which tools it called, "
                "whether they succeeded, and how the final answer was produced. "
                "Be factual and concise."
            )},
            {"role": "user", "content": "\n".join(summary_lines)},
        ]
        try:
            return self.llm.simple_chat(prompt)
        except Exception:
            return "Explanation generation failed."

    def _format_memory_context(self, matches: List[Dict[str, Any]]) -> str:
        """Serialize memory matches to a JSON string for prompting."""
        payload = []
        for m in matches:
            payload.append(
                {
                    "issue": m.get("issue", ""),
                    "fix": m.get("fix") or m.get("resolution", ""),
                    "context": m.get("context", ""),
                    "repo_name": m.get("repo_name", ""),
                    "tags": m.get("tags", []),
                    "score": m.get("score", 0.0),
                }
            )
        return json.dumps(payload)

    def _evolve_memory(
        self, user_query: str, tool_results: List[str], answer: str
    ) -> None:
        """
        Memory Evolution: summarize and persist the new fix.
        Only saves if the answer actually contains a resolution.
        """
        # Skip if the answer is a failure/not found message
        failure_keywords = ["not found", "manual check", "don't know", "empty results", "unable to find"]
        if any(kw in answer.lower() for kw in failure_keywords):
            return

        try:
            summary = self.llm.summarize_for_memory(
                user_query, "\n".join(tool_results), answer
            )
            
            # Additional check on the generated summary fix
            if "not found" in summary.get("fix", "").lower():
                return

            row_id = self.memory.add_memory(summary)
            log_memory_update(summary["issue"], summary["fix"], row_id)
        except Exception as e:
            log_error(f"Memory evolution failed: {e}")

    def index_repo_prs(self, repo: str, count: int = 10, storage: str = "permanent") -> Dict[str, Any]:
        """
        Tool implementation: Fetch recent PRs and index them into selected memory.
        """
        log_info(f"Indexing the {count} latest closed PRs from {repo} into {storage} memory...")
        
        target_memory = self.memory if storage == "permanent" else self.temp_memory
        
        # 1. Fetch PR list
        list_resp = get_closed_prs(repo=repo, count=count)
        if list_resp["status"] != "success":
            return list_resp
            
        results = list_resp["results"]
        indexed_count = 0
        
        for pr in results:
            pr_num = pr["number"]
            # 2. Fetch Diff/Body
            detail = fetch_pr_diff(pr_number=pr_num, repo=repo)
            if detail["status"] != "success":
                continue
                
            # 3. Summarize with LLM
            fact = self.llm.summarize_pr(
                repo_name=repo,
                pr_number=pr_num,
                title=detail["title"],
                description=detail["body"],
                diff=detail["diff"]
            )
            
            # 4. Save to memory (returns existing ID if duplicate)
            new_id = target_memory.add_memory(fact)
            
            from observable_agent_panel.core.observability import log_index_step, console
            # Check if this was a new insertion by looking at the last row id if possible,
            # or just rely on add_memory returning existing ID.
            # We'll use a simple trick: if we didn't track it, we'll assume it might be new.
            # But let's actually just check the count.
            
            # Since we can't easily tell if it was 'new' without changing the return type,
            # let's just log it. The user will see the title.
            log_index_step("PR", pr_num, detail["title"])
            indexed_count += 1
            
        return {
            "status": "success",
            "message": f"Processed {indexed_count} PRs from {repo}. Duplicates were automatically skipped.",
            "repo": repo,
            "indexed_count": indexed_count
        }

    def index_repo_issues(self, repo: str, count: int = 10, storage: str = "permanent") -> Dict[str, Any]:
        """
        Tool implementation: Fetch recent closed Issues (bug reports) and index them.
        """
        log_info(f"Indexing the {count} latest closed issues from {repo} into {storage} memory...")
        
        target_memory = self.memory if storage == "permanent" else self.temp_memory
        
        # 1. Fetch Issues
        list_resp = get_repo_issues(repo=repo, count=count)
        if list_resp["status"] != "success":
            return list_resp
            
        results = list_resp["results"]
        indexed_count = 0
        
        for issue in results:
            issue_num = issue["number"]
            # Summarize Issue
            fact = {
                "issue": issue["title"],
                "fix": "See issue body for details/discussion",
                "context": f"Extracted from {repo} Issue #{issue_num}\n{issue['body'][:500]}",
                "repo_name": repo,
                "tags": ["github", "issue", repo]
            }
            
            # Save to memory (returns existing ID if duplicate)
            target_memory.add_memory(fact)
            indexed_count += 1
            from observable_agent_panel.core.observability import log_index_step
            log_index_step("Issue", issue_num, issue["title"])
            
        return {
            "status": "success",
            "message": f"Processed {indexed_count} issues from {repo}. Duplicates were automatically skipped.",
            "repo": repo,
            "indexed_count": indexed_count
        }
