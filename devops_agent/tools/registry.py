"""
Tool registry for Observable Agent Control Panel.
Defines Pydantic schemas and maps tool names to Python functions.
"""

from typing import Any, Callable, Dict, List
from pydantic import BaseModel, Field
from devops_agent.tools.github_tools import search_github_prs, fetch_pr_diff, get_closed_prs
from devops_agent.tools.local_tools import read_local_error_log, fetch_project_docs, syntax_check_python
from devops_agent.tools.web_tools import search_stackexchange


# ---------------------------------------------------------------------------
# Pydantic Schemas (idiot-proof descriptions for Groq)
# ---------------------------------------------------------------------------

class SearchGithubPRsInput(BaseModel):
    """Input schema for search_github_prs."""
    query: str = Field(
        ...,
        description=(
            "The search query string to find closed Pull Requests. "
            "Example: 'Webpack OOM' or 'memory leak fix'. "
            "Must be specific to find relevant PRs."
        ),
    )
    repo: str = Field(
        "tiangolo/fastapi",
        description=(
            "Optional target repository in 'owner/repo' format. "
            "Defaults to 'tiangolo/fastapi'."
        ),
    )


class FetchPRDiffInput(BaseModel):
    """Input schema for fetch_pr_diff."""
    pr_number: int = Field(
        ...,
        description=(
            "The integer Pull Request number to fetch the diff for. "
            "The 'pr_number' MUST be an integer, not a string. "
            "Example: 892."
        ),
    )
    repo: str = Field(
        "tiangolo/fastapi",
        description=(
            "Optional target repository in 'owner/repo' format. "
            "Defaults to 'tiangolo/fastapi'."
        ),
    )


class IndexRepoPRsInput(BaseModel):
    """Input schema for index_repo_prs."""
    repo: str = Field(
        ...,
        description="The GitHub repository to index in 'owner/repo' format (e.g., 'tiangolo/fastapi')."
    )
    count: int = Field(
        10,
        description="Number of recent closed items to index (default 10, max 50)."
    )
    storage: str = Field(
        "permanent",
        description="Where to save the indexed PRs. 'permanent' (all sessions) or 'temp' (current session only)."
    )


class ReadLocalErrorLogInput(BaseModel):
    """Input schema for read_local_error_log."""
    filepath: str = Field(
        ...,
        description=(
            "Path to a local .log file to read. The content is truncated to 3000 chars."
        ),
    )


class FetchProjectDocsInput(BaseModel):
    """Input schema for fetch_project_docs."""
    filepath: str = Field(
        "architecture.md",
        description=(
            "Path to a local documentation file (e.g., architecture.md)."
        ),
    )


class SearchStackexchangeInput(BaseModel):
    """Input schema for search_stackexchange."""
    query: str = Field(..., description="The search query for StackOverflow threads.")

class SyntaxCheckPythonInput(BaseModel):
    """Input schema for syntax_check_python."""
    code: str = Field(
        ...,
        description=(
            "Python source code to syntax-check using ast.parse()."
        ),
    )


class SearchStackexchangeInput(BaseModel):
    """Input schema for search_stackexchange."""
    query: str = Field(
        ...,
        description=(
            "Search query for StackExchange (Stack Overflow)."
        ),
    )



# ---------------------------------------------------------------------------
# Tool Registry Mapping
# ---------------------------------------------------------------------------

TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "search_github_prs": {
        "function": search_github_prs,
        "schema": {
            "type": "function",
            "function": {
                "name": "search_github_prs",
                "description": (
                    "Searches closed Pull Requests in a GitHub repository "
                    "for a given query string. Returns PR titles, numbers, "
                    "and URLs. Use this to find prior fixes for similar bugs."
                ),
                "parameters": SearchGithubPRsInput.model_json_schema(),
            },
        },
    },
    "fetch_pr_diff": {
        "function": fetch_pr_diff,
        "schema": {
            "type": "function",
            "function": {
                "name": "fetch_pr_diff",
                "description": (
                    "Fetches the code diff and description for a specific Pull Request number. "
                    "The diff is truncated to 3,000 characters to prevent "
                    "context overflow. Use after search_github_prs to inspect "
                    "the actual code changes of a promising PR."
                ),
                "parameters": FetchPRDiffInput.model_json_schema(),
            },
        },
    },
    "index_repo_prs": {
        "function": None,  # Implemented in Orchestrator
        "schema": {
            "type": "function",
            "function": {
                "name": "index_repo_prs",
                "description": (
                    "Extracts recent closed PRs from a repository, summarizes them using AI, "
                    "and saves them into memory for future fast-retrieval. "
                    "Use this to 'teach' the agent about a new repository's history."
                ),
                "parameters": IndexRepoPRsInput.model_json_schema(),
            },
        },
    },
    "read_local_error_log": {
        "function": read_local_error_log,
        "schema": {
            "type": "function",
            "function": {
                "name": "read_local_error_log",
                "description": (
                    "Reads a local .log file and returns its content truncated to 3000 chars."
                ),
                "parameters": ReadLocalErrorLogInput.model_json_schema(),
            },
        },
    },
    "fetch_project_docs": {
        "function": fetch_project_docs,
        "schema": {
            "type": "function",
            "function": {
                "name": "fetch_project_docs",
                "description": (
                    "Reads a local documentation file (e.g., architecture.md)."
                ),
                "parameters": FetchProjectDocsInput.model_json_schema(),
            },
        },
    },
    "syntax_check_python": {
        "function": syntax_check_python,
        "schema": {
            "type": "function",
            "function": {
                "name": "syntax_check_python",
                "description": (
                    "Performs a syntax-only check on Python code using ast.parse()."
                ),
                "parameters": SyntaxCheckPythonInput.model_json_schema(),
            },
        },
    },
    "search_stackexchange": {
        "function": search_stackexchange,
        "schema": {
            "type": "function",
            "function": {
                "name": "search_stackexchange",
                "description": (
                    "Searches StackExchange (Stack Overflow) for relevant threads."
                ),
                "parameters": SearchStackexchangeInput.model_json_schema(),
            },
        },
    },
    "index_repo_issues": {
        "function": None,
        "schema": {
            "type": "function",
            "function": {
                "name": "index_repo_issues",
                "description": (
                    "Extracts recent closed issues (bug reports) from a repository and "
                    "saves them into memory. Use this to 'teach' the agent about known "
                    "bugs and errors in a repository."
                ),
                "parameters": IndexRepoPRsInput.model_json_schema(), # Reuse same schema
            },
        },
    },
}


def get_tool_schemas() -> List[Dict[str, Any]]:
    """Return a list of all tool schemas for LLM injection."""
    return [entry["schema"] for entry in TOOL_REGISTRY.values()]

def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a registered tool by name with the provided JSON arguments.
    Returns the raw tool result dict.
    """
    # Explicitly block unauthorized fallbacks - Feature 2: Self-Healing Protocol
    BLOCKED_TOOLS = ["web_search", "browser", "search_web", "google_search"]
    if tool_name in BLOCKED_TOOLS:
        return {
            "status": "error",
            "message": f"Web search is disabled. Use MCP institutional memory tools only (registry count: {len(TOOL_REGISTRY)}).",
        }

    if tool_name not in TOOL_REGISTRY:
        return {
            "status": "error",
            "message": f"Tool '{tool_name}' not found in registry.",
        }

    tool_entry = TOOL_REGISTRY[tool_name]
    func = tool_entry["function"]
    
    if func is None:
         return {
            "status": "error",
            "message": f"Tool '{tool_name}' requires orchestrator context and cannot be run standalone.",
        }

    try:
        # Validate arguments against Pydantic schema
        if tool_name == "search_github_prs":
            validated = SearchGithubPRsInput(**arguments)
            result = func(query=validated.query, repo=validated.repo)
        elif tool_name == "fetch_pr_diff":
            validated = FetchPRDiffInput(**arguments)
            result = func(pr_number=validated.pr_number, repo=validated.repo)
        elif tool_name == "read_local_error_log":
            validated = ReadLocalErrorLogInput(**arguments)
            result = func(filepath=validated.filepath)
        elif tool_name == "fetch_project_docs":
            validated = FetchProjectDocsInput(**arguments)
            result = func(filepath=validated.filepath)
        elif tool_name == "syntax_check_python":
            validated = SyntaxCheckPythonInput(**arguments)
            result = func(code=validated.code)
        elif tool_name == "search_stackexchange":
            validated = SearchStackexchangeInput(**arguments)
            result = func(query=validated.query)
        else:
            result = func(**arguments)
        return result
    except Exception as e:
        return {
            "status": "error",
            "message": f"Tool execution failed: {str(e)}",
        }
