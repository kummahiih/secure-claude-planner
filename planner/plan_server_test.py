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
from plan_server import app, PLANS_DIR


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


@pytest.fixture
def sample_plan(clean_plans_dir):
    """Write a sample plan file and return its path."""
    plan = {
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
    path = clean_plans_dir / "plan-2026-03-17-abc12.json"
    path.write_text(json.dumps(plan, indent=2))
    return path


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


# --- GET /current ---


class TestGetCurrent:
    def test_returns_current_task(self, client, sample_plan):
        r = client.get("/current", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["plan_id"] == "plan-test-001"
        assert data["task"]["id"] == "t2"
        assert data["task"]["name"] == "Second task"
        assert "status" not in data["task"]  # status not exposed

    def test_no_plan_returns_404(self, client, clean_plans_dir):
        r = client.get("/current", headers=AUTH)
        assert r.status_code == 404

    def test_all_completed_returns_null_task(self, client, clean_plans_dir):
        plan = {
            "id": "plan-done",
            "goal": "Done",
            "status": "in_progress",
            "created": "2026-03-17T10:00:00Z",
            "tasks": [
                {
                    "id": "t1", "name": "Only task", "files": [],
                    "action": "x", "verify": "x", "done": "x",
                    "status": "completed",
                }
            ],
        }
        (clean_plans_dir / "plan-2026-03-17-done1.json").write_text(json.dumps(plan))
        r = client.get("/current", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["task"] is None
        assert "completed" in r.json()["message"].lower()


# --- GET /list ---


class TestListTasks:
    def test_returns_all_tasks_summary(self, client, sample_plan):
        r = client.get("/list", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert len(data["tasks"]) == 3
        assert data["tasks"][0]["status"] == "completed"
        assert data["tasks"][1]["status"] == "current"
        # Summary should not include action/verify/done
        assert "action" not in data["tasks"][0]

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

        # Verify file was updated
        plan = json.loads(sample_plan.read_text())
        assert plan["tasks"][1]["status"] == "completed"
        assert plan["tasks"][2]["status"] == "current"

    def test_complete_last_task(self, client, clean_plans_dir):
        plan = {
            "id": "plan-last",
            "goal": "Last task test",
            "status": "in_progress",
            "created": "2026-03-17T10:00:00Z",
            "tasks": [
                {
                    "id": "t1", "name": "Only task", "files": [],
                    "action": "x", "verify": "x", "done": "x",
                    "status": "current",
                }
            ],
        }
        (clean_plans_dir / "plan-2026-03-17-last1.json").write_text(json.dumps(plan))
        r = client.post("/complete", json={"task_id": "t1"}, headers=AUTH)
        assert r.status_code == 200
        assert "completed" in r.json()["message"].lower()

        # Plan status should be completed
        saved = json.loads((clean_plans_dir / "plan-2026-03-17-last1.json").read_text())
        assert saved["status"] == "completed"

    def test_wrong_task_id_returns_400(self, client, sample_plan):
        r = client.post("/complete", json={"task_id": "t1"}, headers=AUTH)
        assert r.status_code == 400
        assert "mismatch" in r.json()["detail"].lower()

    def test_no_plan_returns_404(self, client, clean_plans_dir):
        r = client.post("/complete", json={"task_id": "t1"}, headers=AUTH)
        assert r.status_code == 404


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


# --- POST /plan ---


class TestCreatePlan:
    def test_creates_plan(self, client, clean_plans_dir):
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

        # Verify file exists
        plan_files = list(clean_plans_dir.glob("plan-*.json"))
        assert len(plan_files) == 1
        plan = json.loads(plan_files[0].read_text())
        assert plan["tasks"][0]["status"] == "current"
        assert plan["tasks"][1]["status"] == "pending"

    def test_empty_tasks_returns_400(self, client, clean_plans_dir):
        r = client.post(
            "/plan",
            json={"goal": "Empty", "tasks": []},
            headers=AUTH,
        )
        assert r.status_code == 400

    def test_too_many_tasks_returns_400(self, client, clean_plans_dir):
        tasks = [
            {"name": f"Task {i}", "files": [], "action": "x", "verify": "x", "done": "x"}
            for i in range(11)
        ]
        r = client.post("/plan", json={"goal": "Too many", "tasks": tasks}, headers=AUTH)
        assert r.status_code == 400


# --- PATCH /task ---


class TestUpdateTask:
    def test_updates_action(self, client, sample_plan):
        r = client.patch(
            "/task",
            json={"task_id": "t2", "field": "action", "value": "Updated action"},
            headers=AUTH,
        )
        assert r.status_code == 200
        plan = json.loads(sample_plan.read_text())
        assert plan["tasks"][1]["action"] == "Updated action"

    def test_updates_files_as_json(self, client, sample_plan):
        r = client.patch(
            "/task",
            json={"task_id": "t2", "field": "files", "value": '["new.py", "other.py"]'},
            headers=AUTH,
        )
        assert r.status_code == 200
        plan = json.loads(sample_plan.read_text())
        assert plan["tasks"][1]["files"] == ["new.py", "other.py"]

    def test_cannot_update_status(self, client, sample_plan):
        r = client.patch(
            "/task",
            json={"task_id": "t2", "field": "status", "value": "completed"},
            headers=AUTH,
        )
        assert r.status_code == 400

    def test_unknown_task_returns_404(self, client, sample_plan):
        r = client.patch(
            "/task",
            json={"task_id": "t99", "field": "name", "value": "x"},
            headers=AUTH,
        )
        assert r.status_code == 404


# --- Health check ---


class TestHealth:
    def test_health_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


# --- Isolation checks ---


class TestIsolation:
    def test_rejects_real_api_key(self):
        from plan_server import verify_isolation

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-real", "MCP_API_TOKEN": "t"}, clear=False):
            with pytest.raises(SystemExit):
                verify_isolation()

    def test_rejects_missing_mcp_token(self):
        from plan_server import verify_isolation

        env = {k: v for k, v in os.environ.items() if k != "MCP_API_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit):
                verify_isolation()
