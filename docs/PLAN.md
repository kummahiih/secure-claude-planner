# Planner Development Plan

Planner-specific tasks and roadmap.

For overall project phases and risk register, see
[docs/PLAN.md](../../../docs/PLAN.md) in the parent repo.

---

## Completed

### Phase 2.5 — Plan Server

- Python FastAPI REST API for plan CRUD
- JSON task format: goal, tasks with files/action/verify/done, auto-advancing
- Plans stored in parent repo plans/ directory
- 42 server tests
- 10 startup isolation checks
- No access to /workspace, /gitdir, or secrets

---

## Upcoming

### Improve plan validation

- [ ] Schema validation for incoming plan JSON (reject malformed plans early)
- [ ] Limit task count range enforcement (2–10 tasks)
- [ ] Validate task field completeness (files, action, verify, done all required)

### ~~Separate authentication~~ — Done (2026-03-28)

- [X] Introduce PLAN_API_TOKEN distinct from MCP_API_TOKEN
- [X] Update plan_mcp.py wrapper in agent repo to use the new token

### Observability

- [ ] Structured logging for plan state transitions
- [ ] Plan completion metrics (tasks completed vs blocked per plan)

---

## Out of Scope (this sprint)

- Plan versioning or history (plans are currently last-write-wins)
- Multi-plan concurrency (one active plan at a time by design)
- Web UI for plan review (plans are reviewed via `cat plans/*.json`)
