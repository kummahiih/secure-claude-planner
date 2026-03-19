# Planner Context

Implementation details specific to secure-claude-planner.

For cluster-level architecture, security model, and token isolation matrix,
see [docs/CONTEXT.md](../../../docs/CONTEXT.md) in the parent repo.
For the MCP wrapper that connects Claude Code to this server, see
[docs/CONTEXT.md](../../agent/docs/CONTEXT.md) in the agent repo.

---

## Plan File Format

### JSON structure

```json
{
  "id": "plan-YYYY-MM-DD-HHMMSS",
  "goal": "High-level description of what to achieve",
  "status": "in_progress",
  "tasks": [
    {
      "id": "t1",
      "name": "Short task name",
      "files": ["path/to/relevant/file.py"],
      "action": "Detailed description of what to do",
      "verify": "How to verify the task is done correctly",
      "done": "Definition of done",
      "status": "current"
    }
  ]
}
```

### Task status lifecycle

`pending` → `current` → `completed` or `blocked`

Only one task can be `current` at a time. When a task is completed, the server
automatically advances the next `pending` task to `current`.

### Plan file naming

`plan-YYYY-MM-DD-<5-char-hmac>.json` — HMAC derived from plan ID and MCP_API_TOKEN.

---

## Isolation Model

The plan-server is deliberately limited in what it can access:

| Resource | Access |
| :--- | :--- |
| /plans | Read/write (plan state files) |
| /workspace | **No access** |
| /gitdir | **No access** |
| Secrets (API keys) | **No access** (only MCP_API_TOKEN for auth) |

Plans are infrastructure artifacts stored in the parent repo's `plans/` directory,
not agent-modifiable code.

### Startup isolation checks

10 checks run at startup in plan_server.py, verifying that the server cannot
reach workspace, gitdir, or API credentials.

### Authentication

All REST endpoints require `Authorization: Bearer <MCP_API_TOKEN>`. A separate
`PLAN_API_TOKEN` is planned as a future improvement.
