"""
LLM client wrapper for Groq API.
Handles chat completions and tool-calling interactions.
Now supports ASYNC execution.
"""

import os
import json
import asyncio
from typing import Any, Dict, List, Optional
from groq import AsyncGroq

# Model config
MODEL_NAME = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
MAX_TOKENS = int(os.getenv("GROQ_MAX_TOKENS", "4096"))
TEMPERATURE = float(os.getenv("GROQ_TEMPERATURE", "0.2"))


class LLMClient:
    """Async Groq client with tool support."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Groq API key is required. Set GROQ_API_KEY environment variable."
            )
        self.client = AsyncGroq(api_key=self.api_key)

    async def _call_with_retry(self, func, *args, **kwargs) -> Any:
        """Execute async call with exponential backoff for 429 errors."""
        max_retries = 3
        base_delay = 5.0
        for i in range(max_retries):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                if "429" in str(e) and i < max_retries - 1:
                    wait = base_delay * (2 ** i)
                    from observable_agent_panel.core.observability import log_info
                    log_info(f"Rate limited (429). Retrying in {wait:.1f}s...")
                    await asyncio.sleep(wait)
                    continue
                raise e

    async def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
        model_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Async: Send messages to Groq LLM with retry support.
        """
        kwargs: Dict[str, Any] = {
            "model": model_override or MODEL_NAME,
            "messages": messages,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        response = await self._call_with_retry(self.client.chat.completions.create, **kwargs)
        return response.model_dump()

    async def simple_chat(self, messages: List[Dict[str, str]], model_override: Optional[str] = None) -> str:
        """
        Async: Convenience: chat without tools, return assistant text.
        """
        resp = await self.chat(messages, model_override=model_override)
        choice = resp["choices"][0]
        return choice["message"].get("content", "")

    async def summarize_for_memory(self, user_query: str, tool_results: str, answer: str) -> Dict[str, Any]:
        """
        Async: Distill interaction into a memory JSON using a lighter model.
        """
        # Use lighter model for background tasks to save tokens
        model = "llama-3.1-8b-instant" 
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a compression engine. Summarize the bug and fix "
                    "into a JSON object with exactly four keys: 'issue', 'fix', "
                    "'context', and 'tags'. The 'tags' value must be a JSON array. "
                    "Be concise but specific. Output ONLY raw JSON, no markdown."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User Query: {user_query}\n"
                    f"Tool Results: {tool_results[:2000]}\n"
                    f"Final Answer: {answer}\n"
                    f"\nSummarize into JSON: "
                    f"{{\"issue\": \"...\", \"fix\": \"...\", "
                    f"\"context\": \"...\", \"tags\": [\"...\"]}}"
                ),
            },
        ]
        raw_resp = await self.simple_chat(messages, model_override=model)
        raw = raw_resp.strip()
        # Clean markdown
        if raw.startswith("```json"): raw = raw[7:]
        if raw.startswith("```"): raw = raw[3:]
        if raw.endswith("```"): raw = raw[:-3]
        raw = raw.strip()

        try:
            parsed = json.loads(raw)
            tags = parsed.get("tags", [])
            if not isinstance(tags, list): tags = [str(tags)]
            return {
                "issue": parsed.get("issue", user_query),
                "fix": parsed.get("fix", answer),
                "context": parsed.get("context", ""),
                "tags": tags,
            }
        except json.JSONDecodeError:
            return {"issue": user_query, "fix": answer, "context": "", "tags": []}

    async def summarize_pr(self, repo_name: str, pr_number: int, title: str, description: str, diff: str) -> Dict[str, Any]:
        """
        Async: Summarize a GitHub PR into memory fact using lighter model.
        """
        model = "llama-3.1-8b-instant"
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a DevOps intelligence engine. Analyze the provided GitHub PR "
                    "and extract the core issue and fix. Output a JSON object with: "
                    "'issue', 'fix', 'context', and 'tags' (array). "
                    "Output ONLY raw JSON."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Repo: {repo_name}\n"
                    f"PR #{pr_number}: {title}\n"
                    f"Description: {description[:1000]}\n"
                    f"Diff Snippet: {diff[:2000]}\n"
                ),
            },
        ]
        raw_resp = await self.simple_chat(messages, model_override=model)
        raw = raw_resp.replace("```json", "").replace("```", "").strip()

        try:
            parsed = json.loads(raw)
            return {
                "issue": parsed.get("issue", title),
                "fix": parsed.get("fix", "See PR diff"),
                "context": f"Extracted from {repo_name} PR #{pr_number}",
                "repo_name": repo_name,
                "tags": parsed.get("tags", []),
            }
        except Exception:
            return {
                "issue": title,
                "fix": "Review PR diff",
                "context": f"Extracted from {repo_name} PR #{pr_number}",
                "repo_name": repo_name,
                "tags": ["github", "pr", repo_name],
            }
