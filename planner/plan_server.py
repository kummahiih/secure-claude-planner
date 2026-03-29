"""
plan_server.py — FastAPI REST server for plan state management.

Runs in the plan-server container. Reads/writes JSON plan files in /plans.
Authenticated with MCP_API_TOKEN (Bearer).

REST endpoints:
  GET  /current  — current task
  GET  /list     — summary of all tasks
  POST /complete — mark current task done, advance next
  POST /block    — mark current task blocked
  POST /plan     — create a new plan
  PATCH /task    — update a field on a specific task
  GET  /health   — health check
"""

import os
import sys
import json
import hmac
import hashlib
import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("plan_server")


# --- Configuration ---

PLANS_DIR = os.environ.get("PLANS_DIR", "/plans")
PLAN_API_TOKEN = os.environ.get("PLAN_API_TOKEN", "") or os.environ.get("MCP_API_TOKEN", "")

if not PLAN_API_TOKEN:
    logger.error("PLAN_API_TOKEN not set — refusing to start")
    sys.exit(1)


# --- Auth ---

app = FastAPI(title="Secure Claude Plan Server")
security = HTTPBearer()


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not secrets.compare_digest(credentials.credentials, PLAN_API_TOKEN):
        logger.warning("Failed authentication attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


# --- Request/Response models ---

class TaskInput(BaseModel):
    name: str
    files: list[str]
    action: str
    verify: str
    done: str


class PlanCreateRequest(BaseModel):
    goal: str
    tasks: list[TaskInput]


class CompleteRequest(BaseModel):
    task_id: str


class BlockRequest(BaseModel):
    task_id: str
    reason: str
    context: Optional[str] = None


class UnblockRequest(BaseModel):
    task_id: str


class TaskUpdateRequest(BaseModel):
    task_id: str
    field: str
    value: str


# --- Plan file helpers ---

VALID_TASK_STATUSES = {"pending", "current", "in_progress", "completed", "blocked"}
UPDATABLE_FIELDS = {"name", "files", "action", "verify", "done"}


def _plan_filename(plan_id: str) -> str:
    """Generate filename: plan-YYYY-MM-DD-<hex>.json"""
    tag = hmac.new(
        PLAN_API_TOKEN.encode(), plan_id.encode(), hashlib.sha256
    ).hexdigest()[:5]
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"plan-{date_str}-{tag}.json"


def _current_plan_path() -> Optional[Path]:
    """Find the active plan (status != 'completed'). Returns None if no active plan."""
    plans_dir = Path(PLANS_DIR)
    if not plans_dir.is_dir():
        return None

    # Look for plans, most recent first
    plan_files = sorted(plans_dir.glob("plan-*.json"), reverse=True)
    for pf in plan_files:
        try:
            plan = json.loads(pf.read_text())
            if plan.get("status") != "completed":
                return pf
        except (json.JSONDecodeError, OSError):
            continue
    return None


def _load_plan(path: Path) -> dict:
    return json.loads(path.read_text())


def _save_plan(path: Path, plan: dict) -> None:
    path.write_text(json.dumps(plan, indent=2) + "\n")


def _get_current_task(plan: dict) -> Optional[dict]:
    for task in plan.get("tasks", []):
        if task["status"] == "current":
            return task
    return None


def _task_response(task: dict) -> dict:
    """Return task fields relevant for Claude (no status)."""
    return {
        "id": task["id"],
        "name": task["name"],
        "files": task["files"],
        "action": task["action"],
        "verify": task["verify"],
        "done": task["done"],
    }


# --- Endpoints ---

@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/current")
async def get_current(token: str = Depends(verify_token)):
    plan_path = _current_plan_path()
    if not plan_path:
        raise HTTPException(status_code=404, detail="No active plan found")

    plan = _load_plan(plan_path)
    task = _get_current_task(plan)

    result = {
        "plan_id": plan["id"],
        "plan_goal": plan["goal"],
        "task": _task_response(task) if task else None,
    }
    if not task:
        result["message"] = "All tasks completed"
    return result


@app.get("/list")
async def list_tasks(token: str = Depends(verify_token)):
    plan_path = _current_plan_path()
    if not plan_path:
        raise HTTPException(status_code=404, detail="No active plan found")

    plan = _load_plan(plan_path)
    return {
        "plan_id": plan["id"],
        "plan_goal": plan["goal"],
        "tasks": [
            {"id": t["id"], "name": t["name"], "status": t["status"]}
            for t in plan.get("tasks", [])
        ],
    }


@app.post("/complete")
async def complete_task(req: CompleteRequest, token: str = Depends(verify_token)):
    plan_path = _current_plan_path()
    if not plan_path:
        raise HTTPException(status_code=404, detail="No active plan found")

    plan = _load_plan(plan_path)
    current = _get_current_task(plan)

    if not current:
        raise HTTPException(status_code=400, detail="No current task to complete")
    if current["id"] != req.task_id:
        raise HTTPException(
            status_code=400,
            detail=f"Task ID mismatch: current is {current['id']}, got {req.task_id}",
        )

    # Mark completed
    current["status"] = "completed"

    # Advance next pending → current
    next_task = None
    for task in plan["tasks"]:
        if task["status"] == "pending":
            task["status"] = "current"
            next_task = task
            break

    # Check if all tasks are done
    all_done = all(t["status"] == "completed" for t in plan["tasks"])
    if all_done:
        plan["status"] = "completed"

    _save_plan(plan_path, plan)

    result = {"completed": req.task_id}
    if next_task:
        result["next"] = _task_response(next_task)
    else:
        result["message"] = "All tasks completed"
    return result


@app.post("/block")
async def block_task(req: BlockRequest, token: str = Depends(verify_token)):
    plan_path = _current_plan_path()
    if not plan_path:
        raise HTTPException(status_code=404, detail="No active plan found")

    plan = _load_plan(plan_path)
    current = _get_current_task(plan)

    if not current:
        raise HTTPException(status_code=400, detail="No current task to block")
    if current["id"] != req.task_id:
        raise HTTPException(
            status_code=400,
            detail=f"Task ID mismatch: current is {current['id']}, got {req.task_id}",
        )

    current["status"] = "blocked"
    current["blockers"] = [req.reason]
    current["resume_context"] = req.context or ""
    _save_plan(plan_path, plan)

    return {"blocked": req.task_id, "reason": req.reason}


@app.post("/unblock")
async def unblock_task(req: UnblockRequest, token: str = Depends(verify_token)):
    plan_path = _current_plan_path()
    if not plan_path:
        raise HTTPException(status_code=404, detail="No active plan found")

    plan = _load_plan(plan_path)

    # Reject if another task is already current
    current = _get_current_task(plan)
    if current:
        raise HTTPException(
            status_code=400,
            detail=f"Task {current['id']} is already current; complete or block it first",
        )

    # Find the blocked task
    target = None
    for task in plan["tasks"]:
        if task["id"] == req.task_id:
            target = task
            break

    if not target:
        raise HTTPException(status_code=404, detail=f"Task {req.task_id} not found")
    if target["status"] != "blocked":
        raise HTTPException(
            status_code=400,
            detail=f"Task {req.task_id} is not blocked (status: {target['status']})",
        )

    target["status"] = "current"
    _save_plan(plan_path, plan)

    return {
        "unblocked": req.task_id,
        "task": _task_response(target),
        "blockers": target.get("blockers", []),
        "resume_context": target.get("resume_context", ""),
    }


@app.post("/plan", status_code=201)
async def create_plan(req: PlanCreateRequest, token: str = Depends(verify_token)):
    if not req.tasks:
        raise HTTPException(status_code=400, detail="Plan must have at least one task")
    if len(req.tasks) > 10:
        raise HTTPException(status_code=400, detail="Plan must have at most 10 tasks")

    plan_id = f"plan-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    filename = _plan_filename(plan_id)

    tasks = []
    for i, t in enumerate(req.tasks, 1):
        task = {
            "id": f"t{i}",
            "name": t.name,
            "files": t.files,
            "action": t.action,
            "verify": t.verify,
            "done": t.done,
            "status": "current" if i == 1 else "pending",
        }
        tasks.append(task)

    plan = {
        "id": plan_id,
        "goal": req.goal,
        "status": "in_progress",
        "created": datetime.now(timezone.utc).isoformat(),
        "tasks": tasks,
    }

    plan_path = Path(PLANS_DIR) / filename
    _save_plan(plan_path, plan)
    logger.info(f"Created plan {plan_id} with {len(tasks)} tasks at {plan_path}")

    return {
        "plan_id": plan_id,
        "filename": filename,
        "tasks_created": len(tasks),
        "current_task": "t1",
    }


@app.patch("/task")
async def update_task(req: TaskUpdateRequest, token: str = Depends(verify_token)):
    if req.field not in UPDATABLE_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot update field '{req.field}'. Allowed: {sorted(UPDATABLE_FIELDS)}",
        )

    plan_path = _current_plan_path()
    if not plan_path:
        raise HTTPException(status_code=404, detail="No active plan found")

    plan = _load_plan(plan_path)

    target = None
    for task in plan["tasks"]:
        if task["id"] == req.task_id:
            target = task
            break

    if not target:
        raise HTTPException(status_code=404, detail=f"Task {req.task_id} not found")

    # Handle files field as JSON list
    if req.field == "files":
        try:
            target["files"] = json.loads(req.value)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="files must be a JSON array")
    else:
        target[req.field] = req.value

    _save_plan(plan_path, plan)
    return {"updated": req.task_id, "field": req.field}


# --- Isolation checks (copy-pasted, will refactor later) ---

def verify_isolation():
    """Minimal isolation checks for plan-server container."""
    violations = []

    # Forbidden env vars
    for var in ["ANTHROPIC_API_KEY", "CLAUDE_API_TOKEN", "DYNAMIC_AGENT_KEY", "MCP_API_TOKEN"]:
        if var in os.environ:
            violations.append(f"FORBIDDEN env var present: {var}")

    # Required env vars
    if "PLAN_API_TOKEN" not in os.environ:
        violations.append("REQUIRED env var missing: PLAN_API_TOKEN")

    # Plans dir must exist
    if not os.path.isdir(PLANS_DIR):
        violations.append(f"PLANS_DIR not found: {PLANS_DIR}")

    # Must not have workspace or agent code
    for path in ["/workspace", "/gitdir", "/docs", "/app/server.py", "/app/files_mcp.py"]:
        if os.path.exists(path):
            violations.append(f"FORBIDDEN path exists: {path}")

    # .env file scan
    for root_dir in ["/app", "/plans"]:
        if not os.path.isdir(root_dir):
            continue
        for dirpath, _dirnames, filenames in os.walk(root_dir):
            for f in filenames:
                if f.endswith(".env") or f == ".env":
                    violations.append(f".env file found: {os.path.join(dirpath, f)}")

    if violations:
        logger.error("=== ISOLATION CHECK FAILED for role=plan-server ===")
        for v in violations:
            logger.error(f"  ✗ {v}")
        logger.error(f"=== {len(violations)} violation(s) — refusing to start ===")
        sys.exit(1)
    else:
        logger.info(f"Isolation checks passed for role=plan-server ({5 + 4 + 1} checks)")


if __name__ == "__main__":
    import uvicorn
    verify_isolation()
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8443,
        ssl_keyfile="/app/certs/plan.key",
        ssl_certfile="/app/certs/plan.crt",
    )
