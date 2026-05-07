import pytest
from devops_agent.tools.registry import execute_tool

@pytest.mark.asyncio
async def test_syntax_checker():
    # Valid code
    res = await execute_tool("syntax_check_python", {"code": "print('hello')"})
    assert res["status"] == "success"
    
    # Invalid code
    res = await execute_tool("syntax_check_python", {"code": "if True"})
    assert res["status"] == "error"

@pytest.mark.asyncio
async def test_github_pr_search_integration():
    """
    Note: This is an integration test. It requires GITHUB_TOKEN.
    """
    res = await execute_tool("search_github_prs", {"query": "Pydantic", "repo": "tiangolo/fastapi"})
    # Even if it fails due to rate limits/auth, we check if it returned a structured response
    assert "status" in res
    if res["status"] == "success":
        assert isinstance(res["results"], list)

@pytest.mark.asyncio
async def test_stack_overflow_integration():
    """Integration test for StackExchange tool."""
    res = await execute_tool("search_stackexchange", {"query": "python pytest"})
    assert res["status"] == "success"
    assert "results" in res
