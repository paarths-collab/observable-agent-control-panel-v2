"""
Web tools for Observable Agent Control Panel.
Includes StackExchange (Stack Overflow) search integration.
Now supports ASYNC execution.
"""

import httpx
from typing import Any, Dict, List

async def search_stackexchange(query: str) -> Dict[str, Any]:
    """
    Async: Search StackOverflow for threads matching the query.
    Returns a list of top 5 results.
    """
    url = "https://api.stackexchange.com/2.3/search/advanced"
    params = {
        "order": "desc",
        "sort": "relevance",
        "q": query,
        "site": "stackoverflow",
        "pagesize": 5,
        "filter": "default"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            
            results = []
            for item in data.get("items", []):
                results.append({
                    "title": item.get("title"),
                    "link": item.get("link"),
                    "score": item.get("score"),
                    "answer_count": item.get("answer_count"),
                    "is_answered": item.get("is_answered"),
                    "tags": item.get("tags")
                })
                
            return {
                "status": "success",
                "query": query,
                "results": results,
                "count": len(results)
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"StackExchange search failed: {str(e)}"
            }
