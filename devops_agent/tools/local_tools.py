"""
Local tool implementations for OctaClaw MCP.
Custom actions and safe local utilities.
Now supports ASYNC interface.
"""

import ast
from typing import Dict

MAX_TEXT_LENGTH = 3000


def _truncate(text: str, max_len: int = MAX_TEXT_LENGTH) -> Dict:
    original_length = len(text)
    truncated = False
    if original_length > max_len:
        text = text[:max_len]
        truncated = True
    return {"text": text, "truncated": truncated, "original_length": original_length}


async def read_local_error_log(filepath: str) -> Dict:
    """
    Async: Read a local log file and truncate to MAX_TEXT_LENGTH.
    """
    try:
        # Note: In a real high-perf app, we'd use aiofiles here.
        # Keeping it simple for the demo as disk I/O is local.
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        if not content.strip():
            return {
                "status": "empty",
                "message": f"Log file is empty: {filepath}",
                "path": filepath,
                "content": "",
            }

        trunc = _truncate(content)
        return {
            "status": "success",
            "path": filepath,
            "content": trunc["text"],
            "truncated": trunc["truncated"],
            "original_length": trunc["original_length"],
        }
    except FileNotFoundError:
        return {
            "status": "error",
            "message": f"File not found: {filepath}",
            "path": filepath,
            "content": "",
        }
    except OSError as e:
        return {
            "status": "error",
            "message": f"Failed to read file: {str(e)}",
            "path": filepath,
            "content": "",
        }


async def fetch_project_docs(filepath: str) -> Dict:
    """
    Async: Read a local documentation file (e.g., architecture.md).
    """
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        if not content.strip():
            return {
                "status": "empty",
                "message": f"Doc file is empty: {filepath}",
                "path": filepath,
                "content": "",
            }

        trunc = _truncate(content)
        return {
            "status": "success",
            "path": filepath,
            "content": trunc["text"],
            "truncated": trunc["truncated"],
            "original_length": trunc["original_length"],
        }
    except FileNotFoundError:
        return {
            "status": "error",
            "message": f"File not found: {filepath}",
            "path": filepath,
            "content": "",
        }
    except OSError as e:
        return {
            "status": "error",
            "message": f"Failed to read file: {str(e)}",
            "path": filepath,
            "content": "",
        }


async def syntax_check_python(code: str) -> Dict:
    """
    Async: Perform a syntax-only check on Python code using ast.parse().
    """
    try:
        ast.parse(code)
        return {
            "status": "success",
            "result": "Syntax OK",
        }
    except SyntaxError as e:
        return {
            "status": "error",
            "result": f"SyntaxError: {e}",
        }
