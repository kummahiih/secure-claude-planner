# secure-claude-planner: Subrepo Proposal (DRAFT v2)

**Status:** Proposal for discussion — no code yet.

**Idea credits:** Task structure inspired by [get-shit-done](https://github.com/gsd-build/get-shit-done) (MIT).

---

## What This Is

A lightweight planning tool that gives Claude a plan-before-code workflow.
It runs as a separate container (plan-server) with a REST API, accessed
by Claude Code through a stdio MCP wrapper (plan_mcp.py) inside claude-server.

Two modes of use:
- `plan.sh` → `/plan` endpoint → Claude produces a plan (no code)
- `query.sh` → `/ask` endpoint → Claude works on the current task (existing, unchanged)

---

## Architecture

```
claude-server:8000 (FastAPI + Claude Code)
  ├─> files_mcp.py → HTTPS REST → mcp-server:8443  (/workspace)
  ├─> git_mcp.py   → git subprocess (/gitdir)
  ├─> docs_mcp.py  → local read (/docs)
  └─> plan_mcp.py  → HTTPS REST → plan-server:8443  (/plans)

plan-server:8443 (FastAPI, Python)
  └─> /plans (bind mount → parent repo plans/)
```

This mirrors the existing fileserver pattern:
- plan_mcp.py is a stdio MCP server inside claude-server (like files_mcp.py)
- plan-server is a separate container on int_net (like mcp-server)
- Communication is HTTPS REST with MCP_API_TOKEN auth (like mcp-server)
- Claude Code cannot reach plan-server directly — only through plan_mcp.py via mcp-watchdog

---

## Subrepo Structure

```
secure-claude-planner/
├── planner/
│   ├── plan_server.py        # FastAPI REST server (runs in plan-server container)
│   ├── plan_mcp.py           # MCP stdio wrapper (runs in claude-server container)
│   ├── plan_server_test.py   # Unit tests for REST server
│   ├── plan_mcp_test.py      # Unit tests for MCP wrapper
│   └── requirements.txt      # FastAPI, mcp SDK, etc.
```

Two Python files, mirroring the files_mcp.py + main.go split:
- **plan_server.py** — REST API that reads/writes JSON plan files in /plans
- **plan_mcp.py** — stdio MCP server that wraps plan_server.py REST endpoints

---

## Container: plan-server

| Property | Value |
| :--- | :--- |
| Image | Dockerfile.plan (new, in parent repo) |
| Base | python:3.12-slim |
| Network | int_net only |
| Port | 8443 (internal, TLS) |
| Volume | ../plans:/plans:rw |
| Auth | MCP_API_TOKEN (Bearer, same as mcp-server) |
| User | UID 1000 (non-root) |
| TLS | Internal CA cert (same as other services) |

### Isolation checks (same pattern as other containers)

- Forbidden env vars: ANTHROPIC_API_KEY, CLAUDE_API_TOKEN, DYNAMIC_AGENT_KEY
- Required env vars: MCP_API_TOKEN
- No .env files in image
- /plans directory exists and is writable

### What plan-server does NOT have

- No access to /workspace (can't read or write agent code)
- No access to /gitdir (can't touch git)
- No access to /docs
- No Claude Code, no Node.js
- No ext_net (no internet)

---

## JSON Task Format

A plan is a single JSON file. One file per plan. Stored in `plans/`
in the parent repo.

### Example: `plans/current.json`

```json
{
  "id": "phase3-test-runner",
  "goal": "Create test runner MCP tool that runs pytest and go test in sibling containers",
  "status": "in_progress",
  "created": "2025-07-15T10:00:00Z",
  "tasks": [
    {
      "id": "t1",
      "name": "Create test-runner directory structure",
      "files": ["cluster/test-runner/run_tests_mcp.py"],
      "action": "Create the MCP stdio server skeleton. Follow the same pattern as git_mcp.py — use mcp library, define tools, register with server.",
      "verify": "File exists and passes python -c 'import run_tests_mcp'",
      "done": "MCP server skeleton with no tools yet, importable without errors",
      "status": "completed"
    },
    {
      "id": "t2",
      "name": "Add pytest runner tool",
      "files": ["cluster/test-runner/run_tests_mcp.py"],
      "action": "Add run_python_tests tool that invokes docker run with pytest. Mount cluster/agent/claude/ read-only. Return JSON test results. Use subprocess with timeout.",
      "verify": "Tool returns structured JSON with pass/fail counts when invoked",
      "done": "run_python_tests tool exists, returns structured output, has timeout",
      "status": "current",
      "blockers": []
    },
    {
      "id": "t3",
      "name": "Add go test runner tool",
      "files": ["cluster/test-runner/run_tests_mcp.py"],
      "action": "Add run_go_tests tool. Same pattern as pytest runner but mounts fileserver/ and runs go test -json.",
      "verify": "Tool returns structured JSON with pass/fail for Go tests",
      "done": "run_go_tests tool exists, returns structured output",
      "status": "pending"
    }
  ]
}
```

### Task status values

- `pending` — not started
- `current` — the task Claude should work on now
- `in_progress` — Claude started but didn't finish
- `completed` — done and verified
- `blocked` — can't proceed, see `blockers` field

### Design choices

- **JSON, not XML.** Parsed by Python's json module. No schema validation
  library needed — plan_server.py validates on read/write.
- **Flat task list, not nested phases.** Phases are separate plan files.
  Keep each plan small (2-5 tasks). Start a new plan for a new phase.
- **`files` field is key.** Tells Claude which files to read, keeping
  context focused.
- **`verify` and `done` borrowed from GSD.** Verify = how to check.
  Done = what success looks like.
- **One `current` task at a time.** The server enforces this.

---

## REST API (plan_server.py)

Mirrors the simplicity of the Go fileserver's REST API.

| Method | Path | Description |
| :--- | :--- | :--- |
| GET | /current | Returns the current task from the active plan |
| GET | /list | Returns summary of all tasks (id, name, status) |
| POST | /complete | Marks current task as completed, advances next |
| POST | /block | Marks current task as blocked with reason |
| POST | /plan | Creates a new plan |
| PATCH | /task | Updates a field on a specific task |

All endpoints require Bearer MCP_API_TOKEN.
All responses are JSON.

### GET /current

Response (200):
```json
{
  "plan_id": "phase3-test-runner",
  "plan_goal": "Create test runner MCP tool...",
  "task": {
    "id": "t2",
    "name": "Add pytest runner tool",
    "files": ["cluster/test-runner/run_tests_mcp.py"],
    "action": "Add run_python_tests tool...",
    "verify": "Tool returns structured JSON...",
    "done": "run_python_tests tool exists..."
  }
}
```

Response when no current task (200):
```json
{
  "plan_id": "phase3-test-runner",
  "plan_goal": "Create test runner MCP tool...",
  "task": null,
  "message": "All tasks completed"
}
```

Response when no plan loaded (404):
```json
{
  "error": "No active plan found"
}
```

### GET /list

Response (200):
```json
{
  "plan_id": "phase3-test-runner",
  "plan_goal": "Create test runner MCP tool...",
  "tasks": [
    {"id": "t1", "name": "Create test-runner directory structure", "status": "completed"},
    {"id": "t2", "name": "Add pytest runner tool", "status": "current"},
    {"id": "t3", "name": "Add go test runner tool", "status": "pending"}
  ]
}
```

### POST /complete

Request:
```json
{"task_id": "t2"}
```

Response (200):
```json
{
  "completed": "t2",
  "next": {
    "id": "t3",
    "name": "Add go test runner tool",
    "files": ["cluster/test-runner/run_tests_mcp.py"],
    "action": "Add run_go_tests tool...",
    "verify": "Tool returns structured JSON...",
    "done": "run_go_tests tool exists..."
  }
}
```

Returns 400 if task_id doesn't match current task.

### POST /block

Request:
```json
{"task_id": "t2", "reason": "Need Docker socket access design decision first"}
```

Response (200):
```json
{"blocked": "t2", "reason": "Need Docker socket access design decision first"}
```

Does NOT auto-advance. Blocked = human intervention needed.

### POST /plan

Request:
```json
{
  "goal": "Create test runner MCP tool...",
  "tasks": [
    {
      "name": "Create test-runner directory structure",
      "files": ["cluster/test-runner/run_tests_mcp.py"],
      "action": "Create the MCP stdio server skeleton...",
      "verify": "File exists and passes import",
      "done": "MCP server skeleton importable"
    }
  ]
}
```

Response (201):
```json
{
  "plan_id": "plan-20250715-100000",
  "tasks_created": 3,
  "current_task": "t1"
}
```

Server generates plan_id (timestamp-based) and task IDs (t1, t2, ...).
First task is automatically set to `current`.

### PATCH /task

Request:
```json
{"task_id": "t2", "field": "action", "value": "Updated action text..."}
```

Response (200):
```json
{"updated": "t2", "field": "action"}
```

Allowed fields: name, files, action, verify, done.
Cannot update status through this endpoint (use /complete or /block).

---

## MCP Tool Surface (plan_mcp.py)

Six tools, each wrapping one REST endpoint. Same pattern as files_mcp.py.

| MCP Tool | REST Endpoint | Description |
| :--- | :--- | :--- |
| plan_current | GET /current | Get the current task |
| plan_list | GET /list | Summary of all tasks |
| plan_complete | POST /complete | Mark current task done |
| plan_block | POST /block | Mark current task blocked |
| plan_create | POST /plan | Create a new plan |
| plan_update_task | PATCH /task | Update a task field |

---

## Integration with secure-claude

### New files in parent repo

```
cluster/
├── planner/                        ← git submodule → secure-claude-planner
│   └── planner/
│       ├── plan_server.py
│       ├── plan_mcp.py
│       ├── plan_server_test.py
│       ├── plan_mcp_test.py
│       └── requirements.txt
├── Dockerfile.plan                 ← new (in parent repo, like other Dockerfiles)
plans/                              ← new directory for plan state files
plan.sh                             ← new (copy of query.sh, hits /plan)
```

### docker-compose.yml additions

```yaml
plan-server:
  build:
    context: .
    dockerfile: cluster/Dockerfile.plan
  networks:
    - int_net
  environment:
    - MCP_API_TOKEN=${MCP_API_TOKEN}
  volumes:
    - ../plans:/plans:rw
  # TLS cert from internal CA (same pattern as other services)
```

### .mcp.json addition (build-time)

```json
{
  "mcpServers": {
    "planner": {
      "command": "python",
      "args": ["/app/plan_mcp.py"],
      "env": {
        "PLAN_SERVER_URL": "https://plan-server:8443",
        "MCP_API_TOKEN": "${MCP_API_TOKEN}"
      }
    }
  }
}
```

### New scripts and endpoints

- **Dockerfile.plan** — Python 3.12-slim, COPY planner source, TLS cert, non-root user
- **plan.sh** — Copy of query.sh, POSTs to /plan instead of /ask
- **PLAN_SYSTEM_PROMPT** — Added to runenv.py (or new planenv.py)
- **/plan endpoint** — Copy of /ask in server.py with different system prompt

---

## Volume Mount Summary (full cluster, updated)

### claude-server (no new mounts — plan_mcp.py talks over network)

| Host path | Container path | Mode | Purpose |
| :--- | :--- | :--- | :--- |
| ./workspace → ./agent | /workspace | ro | Worktree (existing) |
| ../.git/modules/cluster/agent | /gitdir | rw | Git data (existing) |
| ../docs | /docs | ro | Documentation (existing) |

### mcp-server (unchanged)

| Host path | Container path | Mode | Purpose |
| :--- | :--- | :--- | :--- |
| ./workspace → ./agent | /workspace | rw | Go fileserver (existing) |
| /dev/null | /workspace/.git | ro | Shadow .git (existing) |

### plan-server (new)

| Host path | Container path | Mode | Purpose |
| :--- | :--- | :--- | :--- |
| ../plans | /plans | rw | Plan state files |

---

## System Prompts

### PLAN_SYSTEM_PROMPT (for `/plan` endpoint)

```
You are a planning agent. Your job is to break down the user's request
into small, atomic tasks.

You have access to these MCP tools:
- docs tools: list_docs, read_doc — read project documentation
- planner tools: plan_create, plan_update_task, plan_list — manage plans

Workflow:
1. Read relevant docs to understand the codebase and architecture
2. Break the request into 2-5 small tasks
3. Each task should touch 1-3 files
4. Include specific verify and done criteria for every task
5. Call plan_create to save your plan

Rules:
- Do NOT write code. Do NOT use fileserver or git tools.
- Each task should be completable in a single Claude Code session.
- Name the specific files each task will modify.
- The verify field should be a concrete check, not "it works".
- The done field should be an unambiguous completion condition.
```

### SYSTEM_PROMPT additions (for `/ask` endpoint)

Add to the existing system prompt:

```
Before starting work, call plan_current to check if there is an active task.
If there is a current task:
- Work only on that task. Do not skip ahead.
- Read the files listed in the task using fileserver tools.
- Follow the action description.
- Verify your work matches the verify criteria.
- When done, call plan_complete with the task ID.
- If you cannot proceed, call plan_block with the reason.
If there is no active plan, proceed normally with the user's query.
```

---

## Plan File Lifecycle

1. You run `plan.sh sonnet "build the test runner from Phase 3 of PLAN.md"`
2. Claude reads docs (PLAN.md, CONTEXT.md) via docs MCP
3. Claude calls plan_create with 3-5 tasks
4. Plan saved to /plans/current.json via plan-server
5. You review: `cat plans/current.json | python -m json.tool`
6. You run `query.sh sonnet "work on the current task"`
7. Claude calls plan_current → gets task t1
8. Claude does the work using fileserver + git tools
9. Claude calls plan_complete → t1 done, t2 becomes current
10. Repeat query.sh for each task (or automate later in Phase 4)

---

## Security Considerations

### What's safe

- plan-server is on int_net only, no internet
- Auth via MCP_API_TOKEN (same as mcp-server)
- TLS on all communication
- plan_mcp.py goes through mcp-watchdog
- Plan files are JSON — no code execution risk
- plan-server has no access to /workspace, /gitdir, or secrets

### What to think about

- plan-server shares MCP_API_TOKEN with mcp-server. If they should
  have separate tokens, run.sh needs to generate a PLAN_API_TOKEN.
  Separate tokens = better isolation, more complexity.
- plans/ directory is writable by plan-server. If the agent can
  manipulate plans to skip work or mark things done falsely, that's
  a correctness issue not a security issue (no privilege escalation).

---

## Open Questions

1. **Plan history retention:** Currently completed plans stay as files in `plans/`.
   Should there be an `archive/` subdirectory, or just let them accumulate?

2. **Plan editing by human:** You can edit plan JSON files directly in `plans/`,
   but there's no CLI tool for it yet. Is `cat` + text editor enough, or would
   a `plan.sh edit` subcommand be useful?

3. **Timeout tuning:** The `/plan` endpoint reuses the 120s timeout from `/ask`.
   Planning queries might need less time (no code writing). Worth a separate timeout?

4. **Test runner integration:** When Phase 3 (test runner) lands, should
   `plan_complete` automatically trigger a test run before marking done?
   Or keep that as a system prompt instruction?

5. **Multi-plan awareness:** Current design finds the most recent non-completed
   plan. If you create a new plan while one is active, the old one becomes
   invisible. Should `/plan` refuse to create if an active plan exists?

---

## What This Proposal Deliberately Leaves Out

- Automatic test running after task completion (Phase 3 + Phase 4)
- Multi-plan management (one active plan at a time is enough to start)
- Plan diffing or history tracking
- Web UI for plan review
- Any complexity that isn't needed on day one