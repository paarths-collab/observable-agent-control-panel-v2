# Observable Agent Control Panel

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white)
![Protocol](https://img.shields.io/badge/Protocol-MCP-green)
![Tests](https://img.shields.io/badge/Tests-73%20passing-brightgreen)
![Context](https://img.shields.io/badge/Context-Semantic%20Memory-red)
![Observability](https://img.shields.io/badge/Observability-Traces%20%2B%20Root%20Cause-blueviolet)

<br/>

### 📽️ [View the Demo](demo/octaclaw_demo.mp4)

*(Click above to play the demo video)*

</div>

> **The DevOps agent is the thing being monitored. The Observable Agent Control Panel is the monitoring system. Every decision the agent makes — which tool it called, why it routed that way, whether it got the right answer — is logged, analyzed, and diagnosed. When it fails, you don't guess why. The panel tells you exactly what broke, why it broke, and what to fix.**

---

## Project Structure

This repository contains **two distinct components** that work together:

```
observable-agent-control-panel/
├── devops_agent/               ← The agent being monitored
│   ├── core/
│   │   ├── orchestrator.py     # LLM reasoning + tool routing
│   │   └── llm_client.py       # Groq/OpenAI client
│   ├── memory/
│   │   ├── long_term.py        # SQLite + semantic embeddings
│   │   └── short_term.py       # In-session turn context
│   ├── tools/
│   │   ├── registry.py         # Pluggable tool dispatcher
│   │   ├── github_tools.py     # GitHub REST API tools
│   │   └── web_tools.py        # StackExchange search
│   ├── cli.py                  # Interactive terminal interface
│   └── main.py                 # Entry point
│
├── observable_agent_panel/     ← The monitoring system
│   ├── core/
│   │   ├── analyzer.py         # Failure analysis + root cause engine
│   │   ├── trace_db.py         # SQLite trace persistence
│   │   └── observability.py    # Metrics + alerting
│   └── server.py               # MCP server (16 tools for IDE agents)
│
├── tests/                      # 73 tests, all passing
├── docs/                       # Integration docs + agent prompt
└── data/                       # Persistent SQLite databases
```

---

## 📚 Documentation

Detailed guides and architecture deep-dives are available in the `docs/` directory:

| Document | Description |
|---|---|
| [**Quick Start**](docs/quickstart.md) | Get the system running in under 5 minutes. |
| [**Workflow Guide**](docs/workflow.md) | End-to-end operational workflow and logic. |
| [**IDE Integration**](docs/ide_integration.md) | Connect to Antigravity, Cursor, or Cline via MCP. |
| [**Agent Prompt**](docs/agent_prompt.md) | The system prompt to turn any IDE agent into a reliability engineer. |
| [**DevOps Agent Architecture**](docs/devops_agent_architecture.md) | Deep dive into the orchestrator, memory, and tool registry. |
| [**Control Panel Architecture**](docs/observable_agent_panel_architecture.md) | Deep dive into the monitoring, analysis, and self-healing engine. |

---

## How the Two Components Relate

```mermaid
graph TB
    subgraph "👤 Engineer / IDE Agent (Antigravity)"
        DEV["Ask a DevOps question<br/>or trigger self-healing loop"]
    end

    subgraph "🔍 Observable Agent Control Panel"
        direction TB
        SRV["server.py<br/>MCP Server — 16 tools"]
        ANA["analyzer.py<br/>Root Cause Engine"]
        TDB["trace_db.py<br/>SQLite Trace Store"]
        SRV --> ANA
        SRV --> TDB
    end

    subgraph "🤖 DevOps Agent (The Monitored System)"
        direction TB
        ORCH["orchestrator.py<br/>LLM Reasoning + Routing"]
        LTM["long_term.py<br/>Semantic Memory (SQLite + Embeddings)"]
        STM["short_term.py<br/>Turn Context"]
        REG["tools/registry.py<br/>Tool Dispatcher"]
        GHT["github_tools.py<br/>REST API"]
        WEB["web_tools.py<br/>StackExchange"]
        ORCH --> LTM
        ORCH --> STM
        ORCH --> REG
        REG --> GHT
        REG --> WEB
    end

    subgraph "💾 Persistent Storage"
        DB1[(devops_agent.db<br/>Memory)]
        DB2[(traces.db<br/>Run Logs)]
    end

    DEV -->|"MCP tool call"| SRV
    SRV -->|"search_memory / index_repo"| LTM
    SRV -->|"execute_tool"| REG
    ORCH -->|"Every decision logged"| TDB
    TDB --> DB2
    LTM --> DB1
    ANA -->|"compare_runs<br/>propose_fix<br/>verify_fix"| DEV
    SRV -.->|"Monitors & Observes"| ORCH
```

---

## 🔭 Observability Layer (What Gets Logged)

Every DevOps agent run produces a complete trace record:

| Field | What It Captures |
|---|---|
| `run_id` | Unique UUID for the run |
| `query` | The exact question asked |
| `similarity_score` | How well memory matched (0–1) |
| `routing_decision` | `memory_only` / `tools_only` / `hybrid` |
| `hops` | Every tool called: name, status, latency |
| `hop_limit_hit` | Whether the agent ran out of attempts |
| `outcome` | Human rating: `y` / `n` / unrated |
| `memory_facts_used` | Which memory entries grounded the answer |

---

## 🔄 Self-Healing Agent Loop

When Antigravity connects via MCP, it follows a 6-step automated loop:

```
Observe → Diagnose → Propose Fix → Human Approves → Apply → Verify
```

| Step | MCP Tool | What Happens |
|---|---|---|
| 1. Find failures | `get_failure_candidates` | Locates runs with `outcome=n` or tool errors |
| 2. Diagnose | `compare_runs` + `get_trace_detail` | Root cause: KNOWLEDGE GAP, TOOL FAILURE, ROUTING SHIFT |
| 3. Propose | `propose_fix` | Rule-based fix proposal, no LLM needed |
| 4. Approve | Human confirms | Gate — no action without explicit approval |
| 5. Apply | `index_repo_prs` / tool retry | Fix executed |
| 6. Verify | `verify_fix` | Returns `FIXED` or `NOT_FIXED`, max 3 attempts |

See [`docs/agent_prompt.md`](docs/agent_prompt.md) to paste the full protocol into Antigravity.

---

## 🛠️ MCP Tools Reference (16 Tools)

### GitHub & Web
| Tool | Description |
|---|---|
| `search_github_prs(query, repo)` | Find closed PRs by keyword — uses REST pulls endpoint, no Search API |
| `fetch_pr_diff(pr_number, repo)` | Get a PR's full diff and description |
| `search_stackexchange(query)` | Search StackOverflow (5 results with tags + answer count) |

### Memory
| Tool | Description |
|---|---|
| `search_memory(query, top_k)` | Semantic search over indexed engineering knowledge |
| `index_repo_prs(repo, count)` | Index closed PRs into long-term memory |
| `index_repo_issues(repo, count)` | Index closed issues into long-term memory |

### Observability
| Tool | Description |
|---|---|
| `get_recent_traces(count)` | List recent agent runs with run_ids and metadata |
| `get_trace_detail(run_id)` | Full hop-by-hop trace for one run |
| `analyze_performance()` | Tool success rates and failure counts |
| `get_anomaly_alerts()` | Active system warnings (failure spikes, low similarity) |
| `compare_runs(id_a, id_b)` | Diff two runs + rule-based root cause analysis |

### Self-Healing
| Tool | Description |
|---|---|
| `get_failure_candidates(limit)` | Find recent failed runs |
| `propose_fix(run_id, root_cause)` | Generate a rule-based fix proposal |
| `verify_fix(original_id, new_id)` | Confirm whether a fix worked |

---

## ⚡ Quick Start

### 1. Install & configure
```bash
git clone https://github.com/your-org/observable-agent-control-panel
cd observable-agent-control-panel
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cp .env.sample .env
# Fill in GROQ_API_KEY and GITHUB_TOKEN
```

### 2. Run the DevOps Agent (CLI)
```powershell
# Run from the root directory
python -m devops_agent.main --mode cli
```

### 3. Connect Antigravity via MCP
The `mcp_config.json` is already at `C:\Users\PaarthGala\.gemini\antigravity\mcp_config.json`.  
Go to **Antigravity → Agent Panel → `...` → Manage MCP Servers → Refresh**.

### 4. Start the self-healing loop
Ask Antigravity:
> *"Diagnose the last agent failure and fix it"*

It will call `get_failure_candidates` → `compare_runs` → `propose_fix` → ask for approval → apply → `verify_fix`.

### 🛡️ Hardened Boundaries (New)
To ensure the integrity of the institutional memory, the system now implements **Strict MCP Isolation**:
1. **No External Fallbacks**: The `web_search` and `browser` tools are physically blocked at the registry level. 
2. **Hard Repo-Not-Found Stop**: If a query targets an unindexed repository, the agent performs a hard stop rather than hallucinating or searching the web.
3. **Encoding-Safe Transport**: The MCP layer is hardened against Windows encoding errors (forcing UTF-8 and zero-stdout-pollution) to ensure reliable communication with IDE agents.

---

## 🧪 Tests

```bash
.venv\Scripts\activate
python -m pytest tests/ -v
# 73 passed
```

| Suite | Tests | Coverage |
|---|---|---|
| `test_analyzer.py` | 16 | Root cause engine, alerts, trace diff |
| `test_mcp_tools.py` | 18 | Self-healing loop tools |
| `test_orchestrator.py` | 12 | Routing, memory, tool hops |
| `test_trace_db.py` | 13 | SQLite persistence lifecycle |
| `test_memory.py` | 4 | Semantic search, deduplication |
| `test_tools.py` | 3 | GitHub REST + StackExchange |
| `test_observability_integration.py` | 6 | End-to-end trace pipeline |
| `test_duplicates.py` | 1 | Memory dedup guard |

---

## 🗺️ Project Roadmap & Execution Plan

The project follows a structured evolution from a raw DevOps assistant to a fully observable, self-healing control plane.

```mermaid
timeline
    title Project Evolution Plan
    Phase 1 : Foundations : Split Architecture : Semantic Memory : GitHub Tooling
    Phase 2 : Observability : Trace Persistence : Deterministic Root Cause : Failure Detection
    Phase 3 : Self-Healing : MCP Integration : Fix Proposals : Automated Verification
    Phase 4 : Optimization : Performance Audits : Token Minimization : Enterprise Hardening
```

---

## 🧠 How it Works: The Intelligent Workflow

The system operates on a **Deterministic-First, LLM-Second** triage loop designed for maximum reliability and token efficiency.

```mermaid
graph LR
    A[User Query] --> B{Semantic Triage}
    B -- Match Found --> C[Answer from Memory]
    B -- No Match --> D[Tooling Loop]
    D --> E[GitHub/Web Data Fetch]
    E --> F[LLM Synthesis]
    C --> G[Log to Trace DB]
    F --> G
    G --> H{Audit Layer}
    H -- Success --> I[Final Answer]
    H -- Failure --> J[Self-Healing Loop]
```

---

## 🚀 Deployment Options

| Mode | Command | Interaction | Best For |
|---|---|---|---|
| **CLI Mode** | `python devops_agent/main.py --mode cli` | Interactive Terminal | Manual indexing, rapid prototyping, direct interaction. |
| **Server Mode** | `python devops_agent/main.py --mode server` | Headless MCP Stdio | Integration into IDEs (Antigravity, Cursor, Cline). |

---

## 📁 Documentation

| File | Focus |
|---|---|
| [`docs/workflow.md`](docs/workflow.md) | **Start Here**: Core logic, decision loops, and component map |
| [`docs/devops_agent_architecture.md`](docs/devops_agent_architecture.md) | Deep-dive into the Reasoning & Tooling engine |
| [`docs/observable_agent_panel_architecture.md`](docs/observable_agent_panel_architecture.md) | Deep-dive into the Monitoring & Analysis engine |
| [`docs/agent_prompt.md`](docs/agent_prompt.md) | Full Self-Healing protocol for IDE Agents |
| [`docs/quickstart.md`](docs/quickstart.md) | Installation and environment setup guide |
