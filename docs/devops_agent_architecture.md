# DevOps Agent Architecture — Deep Dive

The **DevOps Agent** is the operational core of the system. It handles high-level reasoning, interacts with the semantic knowledge base, and executes tools against the external world (GitHub, Web). 

## 🏗️ System Structure

The agent is organized into modular layers, separating the user interface from the reasoning brain and the tooling hands.

```mermaid
graph TD
    subgraph "🤖 DevOps Agent (`devops_agent/`)"
        direction TB
        
        MAIN["main.py<br/>(System Entry)"]
        CLI["cli.py<br/>(Interactive REPL + Diagnostics)"]
        
        subgraph "Core Intelligence"
            ORCH["orchestrator.py<br/>(Repo-Aware Triage)"]
            LLM["llm_client.py<br/>(Groq / OpenAI API)"]
            
            ORCH <--> LLM
        end
        
        subgraph "Memory Layer"
            STM["short_term.py<br/>(Conversation Buffer)"]
            LTM["long_term.py<br/>(Scoped SQLite Store)"]
            
            ORCH --> STM
            ORCH --> LTM
        end
        
        subgraph "Tooling Layer"
            REG["registry.py<br/>(Tool Schema & Dispatcher)"]
            GH["github_tools.py<br/>(REST API Client)"]
            WEB["web_tools.py<br/>(Search Integration)"]
            
            ORCH --> REG
            REG --> GH
            REG --> WEB
        end
        
        MAIN --> CLI
        CLI --> ORCH
    end
```

## 🔄 Interaction Workflows

### 1. The Knowledge Boundary Workflow
The agent now performs a strict scope check before entering expensive tool loops.

```mermaid
sequenceDiagram
    participant Dev as User
    participant Orch as Orchestrator
    participant Mem as LongTermMemory
    participant Tools as ToolRegistry
    
    Dev->>Orch: "Recent OOM fixes in repo/xyz"
    Orch->>Mem: get_indexed_repos()
    Mem-->>Orch: ["tiangolo/fastapi", "django/django"]
    
    alt If repo/xyz NOT in list
        Orch->>Orch: Hard Stop (Block Registry)
        Orch-->>Dev: "Error: Repository 'repo/xyz' not found in institutional memory."
    else If repo/xyz IS in list
        Orch->>Orch: Proceed with full diagnostic reasoning
    end
```

### 2. Deep Diagnostic Workflow
Engineers can trigger multi-run analysis directly from the CLI.

```mermaid
sequenceDiagram
    participant Eng as SRE Engineer
    participant CLI as cli.py
    participant Ana as analyzer.py (LLM)
    participant DB as traces.db
    
    Eng->>CLI: "--deep-analyze id1 id2"
    CLI->>DB: Fetch trace context for both IDs
    DB-->>CLI: Return hops, results, timing
    CLI->>Ana: deep_failure_analysis(traces)
    Ana-->>CLI: Synthesized Pattern + StackOverflow Queries
    CLI-->>Eng: Rendered Markdown Diagnostic Panel
```

## 📄 Component Definitions

| Module | Responsibility |
|---|---|
| **`orchestrator.py`** | The "Brain." Implements the decision tree for Triage, Routing, and **Knowledge Scoping**. |
| **`llm_client.py`** | The "Vocal Cords." Standardizes communication with high-performance LLMs. |
| **`long_term.py`** | The "Archive." Manages the vector-based SQLite database and tracks **Indexed Repositories**. |
| **`registry.py`** | The "Hands." Dynamically generates schemas for LLM tool-calling and dispatches execution. |
| **`cli.py`** | The "Face." A sophisticated terminal interface with support for **Deep Diagnostics** and **REPL command parsing**. |
