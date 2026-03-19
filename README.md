# Secure Claude Planner

Plan state management server for the [secure-claude](../../) cluster. Provides a REST API for creating, querying, and advancing structured task plans.

Task structure inspired by [get-shit-done](https://github.com/gsd-build/get-shit-done) (MIT).

## What's Inside

```
secure-claude-planner/
├── planner/
│   ├── plan_server.py          # FastAPI REST server (10 startup isolation checks)
│   └── plan_server_test.py     # 42 server tests
├── docs/
│   ├── CONTEXT.md              # Architecture and plan format spec
│   └── PLAN.md                 # Development roadmap
└── README.md
```

## Plan Format

Plans are JSON files with a goal and 2–10 tasks:

```json
{
  "id": "plan-20260317-120000",
  "goal": "Add input validation to /read endpoint",
  "status": "in_progress",
  "tasks": [
    {
      "id": "t1",
      "name": "Add validation to handler",
      "files": ["fileserver/main.go"],
      "action": "Add three guard clauses before filesystem call...",
      "verify": "go build ./... compiles clean",
      "done": "Handler has all three guard clauses",
      "status": "current"
    }
  ]
}
```

Task statuses: `pending` → `current` → `completed` (or `blocked`).
One current task at a time. Completing a task advances the next pending task.

## REST API

| Method | Path | Description |
| :--- | :--- | :--- |
| GET | /health | Health check |
| GET | /plans | List all plans |
| GET | /plans/current | Get the active plan's current task |
| POST | /plans | Create a new plan |
| PUT | /plans/{id}/tasks/{task_id} | Update a task |
| POST | /plans/{id}/tasks/{task_id}/complete | Mark task completed |
| POST | /plans/{id}/tasks/{task_id}/block | Mark task blocked |

All endpoints require `Authorization: Bearer <MCP_API_TOKEN>`.

## Local Development

```bash
cd planner && python -m pytest
```

## Documentation

- [docs/CONTEXT.md](docs/CONTEXT.md) — Architecture, isolation model, API details
- [docs/PLAN.md](docs/PLAN.md) — Development roadmap

## Part of Secure Claude

This repo is a git submodule of [secure-claude](../../). See the parent repo for cluster setup, Docker orchestration, and operational commands.
