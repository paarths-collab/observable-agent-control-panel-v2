"""
GitHub tool implementations for Observable Agent Control Panel.
All external API calls go through here.
Now supports ASYNC execution and ROTATING API KEYS.
"""

import os
import httpx
import asyncio
from typing import Dict, List, Optional

# --- Token Rotation Logic ---
_TOKENS = os.getenv("GITHUB_TOKENS", os.getenv("GITHUB_TOKEN", "")).split(",")
_TOKENS = [t.strip() for t in _TOKENS if t.strip()]
_CURRENT_TOKEN_IDX = 0

def _get_current_token() -> str:
    if not _TOKENS: return ""
    return _TOKENS[_CURRENT_TOKEN_IDX]

def _rotate_token() -> bool:
    """Rotate to the next token in the pool. Returns False if we've looped back."""
    global _CURRENT_TOKEN_IDX
    if not _TOKENS or len(_TOKENS) <= 1:
        return False
    
    _CURRENT_TOKEN_IDX = (_CURRENT_TOKEN_IDX + 1) % len(_TOKENS)
    return _CURRENT_TOKEN_IDX != 0

def _headers(media_type: str = "json") -> Dict[str, str]:
    """Build request headers; inject active token from pool."""
    accept_val = f"application/vnd.github.v3+{media_type}"
    if media_type == "diff":
        accept_val = "application/vnd.github.v3.diff"
    
    h = {"Accept": accept_val}
    token = _get_current_token()
    if token:
        h["Authorization"] = f"token {token}"
    return h

# --- Repository Context ---
_DEFAULT_REPO = os.getenv("TARGET_REPO", "tiangolo/fastapi")
_CURRENT_REPO = _DEFAULT_REPO
_STORED_REPOS = [_DEFAULT_REPO] if _DEFAULT_REPO else []

def get_current_repo() -> str:
    return _CURRENT_REPO

def set_current_repo(repo: str) -> None:
    global _CURRENT_REPO
    _CURRENT_REPO = repo
    if repo not in _STORED_REPOS:
        _STORED_REPOS.append(repo)

def get_stored_repos() -> List[str]:
    return _STORED_REPOS

# --- Async Tool Implementations ---

async def search_github_prs(query: str, repo: Optional[str] = None) -> Dict:
    """Async: Search closed PRs in the target repository."""
    repo = repo or get_current_repo()
    url = f"https://api.github.com/repos/{repo}/pulls"
    params = {"state": "closed", "per_page": 50, "sort": "updated", "direction": "desc"}
    
    async with httpx.AsyncClient() as client:
        for _ in range(len(_TOKENS) or 1):
            try:
                resp = await client.get(url, headers=_headers(), params=params, timeout=20.0, follow_redirects=True)
                
                # Handle Rate Limiting with Rotation
                if resp.status_code in (403, 429) and _rotate_token():
                    continue
                
                resp.raise_for_status()
                prs = resp.json()
                
                query_terms = query.lower().split()
                matched = []
                for pr in prs:
                    title = (pr.get("title") or "").lower()
                    body = (pr.get("body") or "").lower()
                    if any(term in title or term in body for term in query_terms):
                        matched.append({
                            "number": pr.get("number"),
                            "title": pr.get("title"),
                            "url": pr.get("html_url"),
                            "state": pr.get("state"),
                        })

                if not matched:
                    return {"status": "empty", "message": f"No PRs found for '{query}' in {repo}.", "results": []}

                return {"status": "success", "total_count": len(matched), "results": matched[:5]}

            except httpx.HTTPError as e:
                return {"status": "error", "message": f"GitHub API request failed: {str(e)}", "results": []}
    
    return {"status": "error", "message": "All tokens in pool exhausted or rate-limited.", "results": []}

async def fetch_pr_diff(pr_number: int, repo: Optional[str] = None) -> Dict:
    """Async: Fetch PR metadata and diff text."""
    repo = repo or get_current_repo()
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    MAX_DIFF_LENGTH = 3000

    async with httpx.AsyncClient() as client:
        for _ in range(len(_TOKENS) or 1):
            try:
                # 1. Get metadata
                resp = await client.get(url, headers=_headers(media_type="json"), timeout=20.0, follow_redirects=True)
                if resp.status_code in (403, 429) and _rotate_token(): continue
                resp.raise_for_status()
                pr_data = resp.json()

                # 2. Get diff
                diff_resp = await client.get(url, headers=_headers(media_type="diff"), timeout=20.0, follow_redirects=True)
                if diff_resp.status_code in (403, 429) and _rotate_token(): continue
                diff_resp.raise_for_status()
                raw_diff = diff_resp.text

                truncated = False
                if len(raw_diff) > MAX_DIFF_LENGTH:
                    raw_diff = raw_diff[:MAX_DIFF_LENGTH]
                    truncated = True

                return {
                    "status": "success",
                    "pr_number": pr_number,
                    "title": pr_data.get("title"),
                    "body": pr_data.get("body", ""),
                    "diff": raw_diff,
                    "truncated": truncated,
                    "original_length": len(diff_resp.text),
                }

            except httpx.HTTPError as e:
                return {"status": "error", "message": f"GitHub API request failed: {str(e)}", "diff": ""}

    return {"status": "error", "message": "All tokens in pool exhausted.", "diff": ""}

async def get_closed_prs(repo: Optional[str] = None, count: int = 10) -> Dict:
    """Async: Fetch list of recent closed PRs."""
    repo = repo or get_current_repo()
    url = f"https://api.github.com/repos/{repo}/pulls?state=closed&per_page={count}"
    
    async with httpx.AsyncClient() as client:
        for _ in range(len(_TOKENS) or 1):
            try:
                resp = await client.get(url, headers=_headers(), timeout=20.0, follow_redirects=True)
                if resp.status_code in (403, 429) and _rotate_token(): continue
                resp.raise_for_status()
                prs = resp.json()
                
                results = [{"number": pr.get("number"), "title": pr.get("title"), "url": pr.get("html_url")} for pr in prs]
                return {"status": "success", "repo": repo, "results": results}
            except httpx.HTTPError as e:
                return {"status": "error", "message": f"Failed to fetch closed PRs: {str(e)}"}
    return {"status": "error", "message": "All tokens exhausted."}

async def get_repo_issues(repo: Optional[str] = None, count: int = 10) -> Dict:
    """Async: Fetch list of recent closed issues."""
    repo = repo or get_current_repo()
    url = f"https://api.github.com/repos/{repo}/issues?state=closed&per_page={count}"
    
    async with httpx.AsyncClient() as client:
        for _ in range(len(_TOKENS) or 1):
            try:
                resp = await client.get(url, headers=_headers(), timeout=20.0, follow_redirects=True)
                if resp.status_code in (403, 429) and _rotate_token(): continue
                resp.raise_for_status()
                issues = resp.json()
                
                results = []
                for issue in issues:
                    if "pull_request" in issue: continue
                    results.append({
                        "number": issue.get("number"),
                        "title": issue.get("title"),
                        "body": issue.get("body", ""),
                        "url": issue.get("html_url")
                    })
                return {"status": "success", "repo": repo, "results": results[:count]}
            except httpx.HTTPError as e:
                return {"status": "error", "message": f"Failed to fetch issues: {str(e)}"}
    return {"status": "error", "message": "All tokens exhausted."}
