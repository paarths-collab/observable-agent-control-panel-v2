# Quick Start Ã¢â‚¬â€ Observable Agent Control Panel

Welcome to the **Observable Agent Control Panel**. This guide will get you from a fresh clone to a running, observable DevOps agent in under 5 minutes.

## Ã°Å¸â€œâ€¹ Prerequisites
- **Python 3.11+**
- **GROQ API Key**: [Get one here](https://console.groq.com/keys)
- **GitHub Token**: (Optional but recommended) [Create here](https://github.com/settings/tokens)

---

## Ã°Å¸â€ºÂ Ã¯Â¸Â Step 1: Environment Setup

1. **Clone and Navigate**:
   ```bash
   git clone https://github.com/your-org/observable-agent-control-panel
   cd observable-agent-control-panel
   ```

2. **Initialize Virtual Environment**:
   ```powershell
   # Windows PowerShell
   python -m venv .venv
   # IMPORTANT: Always activate before running
   .\.venv\Scripts\Activate.ps1
   ```

3. **Install Dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables**:
   Create a `.env` file in the root directory:
   ```env
   GROQ_API_KEY=your_key_here
   GITHUB_TOKEN=your_github_token_here
   GROQ_MODEL=llama-3.3-70b-versatile
   ```

---

## Ã°Å¸Å¡â‚¬ Step 2: Choose Your Mode

The system can be launched in two distinct modes.

### Option A: Interactive CLI Mode
Best for manual exploration and indexing your first repositories.

```bash
python devops_agent/main.py --mode cli
```
**Key Commands**: 
- `index prs tiangolo/fastapi 10`: Prime the agent's memory.
- `heal`: Trigger the automated 6-step self-healing loop.

### Option B: MCP Server Mode
Best for integration with AI Agents like **Antigravity**, **Cursor**, or **Cline**.
Provides **16 specialized tools** for diagnostics and memory.

```bash
python devops_agent/main.py --mode server
```

---

## Ã°Å¸â€Â Step 3: Connect via MCP

The `mcp_config.json` for Antigravity is located at:
`C:\Users\PaarthGala\.gemini\antigravity\mcp_config.json`

Ensure it contains the following configuration:

```json
{
  "mcpServers": {
    "observable-agent-control-panel": {
      "command": "C:/Users/PaarthGala/Coding/observable-agent-control-panel/.venv/Scripts/python.exe",
      "args": [
        "C:/Users/PaarthGala/Coding/observable-agent-control-panel/devops_agent/main.py",
        "--mode",
        "server"
      ],
      "env": {
        "PYTHONPATH": "C:/Users/PaarthGala/Coding/observable-agent-control-panel"
      }
    }
  }
}
```

---

## Ã°Å¸ÂÂ Step 4: Verify the Workflow (Hardened Boundaries)

Ask your IDE Agent:
> *"What repositories do I have indexed?"*
> or
> *"Diagnose the last failed run."*

**Strict Policy Test**: Try querying an unindexed repository (e.g., `django/django`). The agent is now configured to **hard stop** and report a missing repository error rather than falling back to web search.

---

## Ã°Å¸â€œÂ Important Directories

| Path | Purpose |
|---|---|
| `devops_agent/` | Core reasoning, memory, and tooling logic. |
| `observable_agent_panel/` | MCP server and diagnostic analysis engine. |
| `data/` | **Persistence**: `memory.db` (facts) and `traces.db` (logs). |
| `docs/` | **Guides**: `workflow.md`, `agent_prompt.md`, `architecture` deep-dives. |

---
[← Back to README](../README.md)
