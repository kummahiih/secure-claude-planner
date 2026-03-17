"""
plan_server_test.py — Unit tests for plan_server.py

Run with: pytest plan_server_test.py -v
"""

import os
import sys
import json
import pytest
from pathlib import Path
from unittest.mock import patch

# Inject required env vars before importing
os.environ["MCP_API_TOKEN"] = "test-plan-token"
os.environ["PLANS_DIR"] = "/tmp/test-plans"

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from plan_server import app


AUTH = {"Authorization": "Bearer test-plan-token"}
BAD_AUTH = {"Authorization": "Bearer wrong-token"}


@pytest.fixture(autouse=True)
def clean_plans_dir(tmp_path):
    """Use a temp directory for each test."""
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    with patch("plan_server.PLANS_DIR", str(plans_dir)):
        yield plans_dir


@pytest.fixture
def client():
    return TestClient(app)


def _write_plan(plans_dir, plan, filename="plan-2026-03-17-abc12.json"):
    """Helper to write a plan file."""
    path = plans_dir / filename
    path.write_text(json.dumps(plan, indent=2))
    return path


def _sample_plan():
    """Standard 3-task plan for testing."""
    return {
        "id": "plan-test-001",
        "goal": "Test the planner",
        "status": "in_progress",
        "created": "2026-03-17T10:00:00Z",
        "tasks": [
            {
                "id": "t1",
                "name": "First task",
                "files": ["file1.py"],
                "action": "Do the first thing",
                "verify": "Check it works",
                "done": "First thing is done",
                "status": "completed",
            },
            {
                "id": "t2",
                "name": "Second task",
                "files": ["file2.py", "file3.py"],
                "action": "Do the second thing",
                "verify": "Check second thing",
                "done": "Second thing is done",
                "status": "current",
            },
            {
                "id": "t3",
                "name": "Third task",
                "files": ["file3.py"],
                "action": "Do the third thing",
                "verify": "Check third thing",
                "done": "Third thing is done",
                "status": "pending",
            },
        ],
    }


@pytest.fixture
def sample_plan(clean_plans_dir):
    """Write a sample plan file and return its path."""
    return _write_plan(clean_plans_dir, _sample_plan())


# --- Auth tests ---


class TestAuth:
    def test_missing_auth_returns_403(self, client):
        r = client.get("/current")
        assert r.status_code == 403

    def test_wrong_token_returns_401(self, client):
        r = client.get("/current", headers=BAD_AUTH)
        assert r.status_code == 401

    def test_correct_token_passes(self, client, sample_plan):
        r = client.get("/current", headers=AUTH)
        assert r.status_code == 200


# --- GET /health ---


class TestHealth:
    def test_health_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


# --- GET /current ---


class TestGetCurrent:
    def test_returns_current_task(self, client, sample_plan):
        r = client.get("/current", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["plan_id"] == "plan-test-001"
        assert data["plan_goal"] == "Test the planner"
        assert data["task"]["id"] == "t2"
        assert data["task"]["name"] == "Second task"
        assert data["task"]["files"] == ["file2.py", "file3.py"]
        assert data["task"]["action"] == "Do the second thing"
        assert data["task"]["verify"] == "Check second thing"
        assert data["task"]["done"] == "Second thing is done"

    def test_current_task_does_not_expose_status(self, client, sample_plan):
        r = client.get("/current", headers=AUTH)
        assert "status" not in r.json()["task"]

    def test_no_plan_returns_404(self, client, clean_plans_dir):
        r = client.get("/current", headers=AUTH)
        assert r.status_code == 404

    def test_all_completed_returns_null_task(self, client, clean_plans_dir):
        plan = _sample_plan()
        for t in plan["tasks"]:
            t["status"] = "completed"
        _write_plan(clean_plans_dir, plan, "plan-2026-03-17-done1.json")
        # Plan with all tasks completed still has status "in_progress"
        # so it's found, but no current task
        r = client.get("/current", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["task"] is None
        assert "completed" in r.json()["message"].lower()

    def test_completed_plan_is_skipped(self, client, clean_plans_dir):
        plan = _sample_plan()
        plan["status"] = "completed"
        _write_plan(clean_plans_dir, plan, "plan-2026-03-17-old01.json")
        r = client.get("/current", headers=AUTH)
        assert r.status_code == 404

    def test_picks_most_recent_plan(self, client, clean_plans_dir):
        old_plan = _sample_plan()
        old_plan["id"] = "plan-old"
        _write_plan(clean_plans_dir, old_plan, "plan-2026-03-16-old01.json")

        new_plan = _sample_plan()
        new_plan["id"] = "plan-new"
        _write_plan(clean_plans_dir, new_plan, "plan-2026-03-17-new01.json")

        r = client.get("/current", headers=AUTH)
        assert r.json()["plan_id"] == "plan-new"


# --- GET /list ---


class TestListTasks:
    def test_returns_all_tasks_summary(self, client, sample_plan):
        r = client.get("/list", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["plan_id"] == "plan-test-001"
        assert len(data["tasks"]) == 3
        assert data["tasks"][0] == {"id": "t1", "name": "First task", "status": "completed"}
        assert data["tasks"][1] == {"id": "t2", "name": "Second task", "status": "current"}
        assert data["tasks"][2] == {"id": "t3", "name": "Third task", "status": "pending"}

    def test_summary_does_not_include_action(self, client, sample_plan):
        r = client.get("/list", headers=AUTH)
        for t in r.json()["tasks"]:
            assert "action" not in t
            assert "verify" not in t
            assert "done" not in t
            assert "files" not in t

    def test_no_plan_returns_404(self, client, clean_plans_dir):
        r = client.get("/list", headers=AUTH)
        assert r.status_code == 404


# --- POST /complete ---


class TestComplete:
    def test_completes_current_and_advances(self, client, sample_plan):
        r = client.post("/complete", json={"task_id": "t2"}, headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["completed"] == "t2"
        assert data["next"]["id"] == "t3"
        assert data["next"]["name"] == "Third task"

        # Verify file was updated
        plan = json.loads(sample_plan.read_text())
        assert plan["tasks"][1]["status"] == "completed"
        assert plan["tasks"][2]["status"] == "current"

    def test_complete_last_task_marks_plan_completed(self, client, clean_plans_dir):
        plan = {
            "id": "plan-last",
            "goal": "Last task test",
            "status": "in_progress",
            "created": "2026-03-17T10:00:00Z",
            "tasks": [
                {
                    "id": "t1", "name": "Only task", "files": ["x.py"],
                    "action": "x", "verify": "x", "done": "x",
                    "status": "current",
                }
            ],
        }
        path = _write_plan(clean_plans_dir, plan, "plan-2026-03-17-last1.json")
        r = client.post("/complete", json={"task_id": "t1"}, headers=AUTH)
        assert r.status_code == 200
        assert "completed" in r.json()["message"].lower()

        saved = json.loads(path.read_text())
        assert saved["status"] == "completed"
        assert saved["tasks"][0]["status"] == "completed"

    def test_wrong_task_id_returns_400(self, client, sample_plan):
        r = client.post("/complete", json={"task_id": "t1"}, headers=AUTH)
        assert r.status_code == 400
        assert "mismatch" in r.json()["detail"].lower()

    def test_no_plan_returns_404(self, client, clean_plans_dir):
        r = client.post("/complete", json={"task_id": "t1"}, headers=AUTH)
        assert r.status_code == 404

    def test_no_current_task_returns_400(self, client, clean_plans_dir):
        plan = _sample_plan()
        for t in plan["tasks"]:
            t["status"] = "completed"
        _write_plan(clean_plans_dir, plan)
        r = client.post("/complete", json={"task_id": "t1"}, headers=AUTH)
        assert r.status_code == 400
        assert "no current task" in r.json()["detail"].lower()

    def test_complete_skips_blocked_when_advancing(self, client, clean_plans_dir):
        plan = _sample_plan()
        plan["tasks"][2]["status"] = "blocked"
        _write_plan(clean_plans_dir, plan)
        r = client.post("/complete", json={"task_id": "t2"}, headers=AUTH)
        assert r.status_code == 200
        # t3 is blocked, no pending tasks to advance
        assert "completed" in r.json().get("message", "").lower() or "next" not in r.json()


# --- POST /block ---


class TestBlock:
    def test_blocks_current_task(self, client, sample_plan):
        r = client.post(
            "/block",
            json={"task_id": "t2", "reason": "Need design decision"},
            headers=AUTH,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["blocked"] == "t2"
        assert data["reason"] == "Need design decision"

        plan = json.loads(sample_plan.read_text())
        assert plan["tasks"][1]["status"] == "blocked"
        assert "Need design decision" in plan["tasks"][1]["blockers"]

    def test_wrong_task_id_returns_400(self, client, sample_plan):
        r = client.post(
            "/block",
            json={"task_id": "t1", "reason": "wrong"},
            headers=AUTH,
        )
        assert r.status_code == 400

    def test_no_plan_returns_404(self, client, clean_plans_dir):
        r = client.post(
            "/block",
            json={"task_id": "t1", "reason": "no plan"},
            headers=AUTH,
        )
        assert r.status_code == 404


# --- POST /plan ---


class TestCreatePlan:
    def test_creates_plan_with_correct_structure(self, client, clean_plans_dir):
        r = client.post(
            "/plan",
            json={
                "goal": "Build something",
                "tasks": [
                    {
                        "name": "Task one",
                        "files": ["a.py"],
                        "action": "Do it",
                        "verify": "Check it",
                        "done": "It's done",
                    },
                    {
                        "name": "Task two",
                        "files": ["b.py"],
                        "action": "Do more",
                        "verify": "Check more",
                        "done": "More is done",
                    },
                ],
            },
            headers=AUTH,
        )
        assert r.status_code == 201
        data = r.json()
        assert data["tasks_created"] == 2
        assert data["current_task"] == "t1"
        assert "plan_id" in data
        assert "filename" in data

        # Verify file on disk
        plan_files = list(clean_plans_dir.glob("plan-*.json"))
        assert len(plan_files) == 1
        plan = json.loads(plan_files[0].read_text())
        assert plan["goal"] == "Build something"
        assert plan["status"] == "in_progress"
        assert plan["tasks"][0]["status"] == "current"
        assert plan["tasks"][1]["status"] == "pending"
        assert plan["tasks"][0]["id"] == "t1"
        assert plan["tasks"][1]["id"] == "t2"

    def test_empty_tasks_returns_400(self, client, clean_plans_dir):
        r = client.post(
            "/plan",
            json={"goal": "Empty", "tasks": []},
            headers=AUTH,
        )
        assert r.status_code == 400

    def test_too_many_tasks_returns_400(self, client, clean_plans_dir):
        tasks = [
            {"name": f"Task {i}", "files": ["x.py"], "action": "x", "verify": "x", "done": "x"}
            for i in range(11)
        ]
        r = client.post("/plan", json={"goal": "Too many", "tasks": tasks}, headers=AUTH)
        assert r.status_code == 400

    def test_single_task_plan(self, client, clean_plans_dir):
        r = client.post(
            "/plan",
            json={
                "goal": "One thing",
                "tasks": [
                    {"name": "Only task", "files": ["x.py"], "action": "do", "verify": "check", "done": "done"}
                ],
            },
            headers=AUTH,
        )
        assert r.status_code == 201
        assert r.json()["tasks_created"] == 1

    def test_plan_filename_uses_hmac(self, client, clean_plans_dir):
        r = client.post(
            "/plan",
            json={
                "goal": "HMAC test",
                "tasks": [
                    {"name": "T", "files": [], "action": "x", "verify": "x", "done": "x"}
                ],
            },
            headers=AUTH,
        )
        assert r.status_code == 201
        filename = r.json()["filename"]
        assert filename.startswith("plan-")
        assert filename.endswith(".json")
        # Should have date and 5-char hex: plan-YYYY-MM-DD-xxxxx.json
        parts = filename.replace(".json", "").split("-")
        assert len(parts) == 5  # plan, YYYY, MM, DD, hex
        assert len(parts[4]) == 5  # 5-char hex from HMAC


# --- PATCH /task ---


class TestUpdateTask:
    def test_updates_action(self, client, sample_plan):
        r = client.patch(
            "/task",
            json={"task_id": "t2", "field": "action", "value": "Updated action"},
            headers=AUTH,
        )
        assert r.status_code == 200
        assert r.json() == {"updated": "t2", "field": "action"}

        plan = json.loads(sample_plan.read_text())
        assert plan["tasks"][1]["action"] == "Updated action"

    def test_updates_name(self, client, sample_plan):
        r = client.patch(
            "/task",
            json={"task_id": "t1", "field": "name", "value": "Renamed task"},
            headers=AUTH,
        )
        assert r.status_code == 200
        plan = json.loads(sample_plan.read_text())
        assert plan["tasks"][0]["name"] == "Renamed task"

    def test_updates_verify(self, client, sample_plan):
        r = client.patch(
            "/task",
            json={"task_id": "t3", "field": "verify", "value": "New verify"},
            headers=AUTH,
        )
        assert r.status_code == 200
        plan = json.loads(sample_plan.read_text())
        assert plan["tasks"][2]["verify"] == "New verify"

    def test_updates_done(self, client, sample_plan):
        r = client.patch(
            "/task",
            json={"task_id": "t2", "field": "done", "value": "New done condition"},
            headers=AUTH,
        )
        assert r.status_code == 200
        plan = json.loads(sample_plan.read_text())
        assert plan["tasks"][1]["done"] == "New done condition"

    def test_updates_files_as_json(self, client, sample_plan):
        r = client.patch(
            "/task",
            json={"task_id": "t2", "field": "files", "value": '["new.py", "other.py"]'},
            headers=AUTH,
        )
        assert r.status_code == 200
        plan = json.loads(sample_plan.read_text())
        assert plan["tasks"][1]["files"] == ["new.py", "other.py"]

    def test_files_invalid_json_returns_400(self, client, sample_plan):
        r = client.patch(
            "/task",
            json={"task_id": "t2", "field": "files", "value": "not-json"},
            headers=AUTH,
        )
        assert r.status_code == 400

    def test_cannot_update_status(self, client, sample_plan):
        r = client.patch(
            "/task",
            json={"task_id": "t2", "field": "status", "value": "completed"},
            headers=AUTH,
        )
        assert r.status_code == 400
        assert "Cannot update" in r.json()["detail"]

    def test_unknown_task_returns_404(self, client, sample_plan):
        r = client.patch(
            "/task",
            json={"task_id": "t99", "field": "name", "value": "x"},
            headers=AUTH,
        )
        assert r.status_code == 404

    def test_invalid_field_returns_400(self, client, sample_plan):
        r = client.patch(
            "/task",
            json={"task_id": "t2", "field": "id", "value": "hacked"},
            headers=AUTH,
        )
        assert r.status_code == 400


# --- Isolation checks ---


class TestIsolation:
    def test_rejects_anthropic_api_key(self):
        from plan_server import verify_isolation
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-real"}, clear=False):
            with pytest.raises(SystemExit):
                verify_isolation()

    def test_rejects_claude_api_token(self):
        from plan_server import verify_isolation
        with patch.dict(os.environ, {"CLAUDE_API_TOKEN": "leaked"}, clear=False):
            with pytest.raises(SystemExit):
                verify_isolation()

    def test_rejects_dynamic_agent_key(self):
        from plan_server import verify_isolation
        with patch.dict(os.environ, {"DYNAMIC_AGENT_KEY": "leaked"}, clear=False):
            with pytest.raises(SystemExit):
                verify_isolation()

    def test_rejects_missing_mcp_token(self):
        from plan_server import verify_isolation
        env = {k: v for k, v in os.environ.items() if k != "MCP_API_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit):
                verify_isolation()

    def test_rejects_forbidden_paths(self):
        from plan_server import verify_isolation
        for path in ["/workspace", "/gitdir", "/docs", "/app/server.py", "/app/files_mcp.py"]:
            with patch("os.path.exists", side_effect=lambda p, fp=path: p == fp or p == os.environ.get("PLANS_DIR", "/plans")), \
                 patch("os.path.isdir", side_effect=lambda p: p in [os.environ.get("PLANS_DIR", "/plans"), "/app"]):
                with pytest.raises(SystemExit):
                    verify_isolation()

    def test_rejects_env_files(self):
        from plan_server import verify_isolation
        with patch("os.path.isdir", return_value=True), \
             patch("os.path.exists", return_value=False), \
             patch("os.walk", return_value=[("/app", [], [".secrets.env"])]):
            with pytest.raises(SystemExit):
                verify_isolation()
