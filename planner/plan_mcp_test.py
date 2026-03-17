"""
plan_mcp_test.py — Unit tests for plan_mcp.py

Same pattern as files_mcp_test.py: mock requests, test _dispatch and call_tool.

Run with: pytest plan_mcp_test.py -v
"""

import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock

# Inject env vars before importing
os.environ["MCP_API_TOKEN"] = "test-plan-token"
os.environ["PLAN_SERVER_URL"] = "https://plan-server:8443"

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from plan_mcp import _dispatch, call_tool


# --- plan_current ---


@pytest.mark.asyncio
@patch("plan_mcp.requests.get")
async def test_current_success(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "plan_id": "plan-001",
        "plan_goal": "Test",
        "task": {"id": "t1", "name": "First"},
    }
    result = await _dispatch("plan_current", {})
    data = json.loads(result)
    assert data["task"]["id"] == "t1"


@pytest.mark.asyncio
@patch("plan_mcp.requests.get")
async def test_current_no_plan(mock_get):
    mock_get.return_value.status_code = 404
    result = await _dispatch("plan_current", {})
    data = json.loads(result)
    assert "no active plan" in data["message"].lower()


@pytest.mark.asyncio
@patch("plan_mcp.requests.get")
async def test_current_server_error(mock_get):
    mock_get.return_value.status_code = 500
    mock_get.return_value.text = "Internal error"
    with pytest.raises(RuntimeError, match="500"):
        await _dispatch("plan_current", {})


# --- plan_list ---


@pytest.mark.asyncio
@patch("plan_mcp.requests.get")
async def test_list_success(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "plan_id": "plan-001",
        "plan_goal": "Test",
        "tasks": [{"id": "t1", "name": "First", "status": "current"}],
    }
    result = await _dispatch("plan_list", {})
    data = json.loads(result)
    assert len(data["tasks"]) == 1


@pytest.mark.asyncio
@patch("plan_mcp.requests.get")
async def test_list_no_plan(mock_get):
    mock_get.return_value.status_code = 404
    result = await _dispatch("plan_list", {})
    data = json.loads(result)
    assert "no active plan" in data["message"].lower()


# --- plan_complete ---


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_complete_success(mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "completed": "t1",
        "next": {"id": "t2", "name": "Second"},
    }
    result = await _dispatch("plan_complete", {"task_id": "t1"})
    data = json.loads(result)
    assert data["completed"] == "t1"
    assert data["next"]["id"] == "t2"


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_complete_wrong_id(mock_post):
    mock_post.return_value.status_code = 400
    mock_post.return_value.json.return_value = {"detail": "Task ID mismatch"}
    with pytest.raises(ValueError, match="mismatch"):
        await _dispatch("plan_complete", {"task_id": "wrong"})


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_complete_no_plan(mock_post):
    mock_post.return_value.status_code = 404
    with pytest.raises(FileNotFoundError):
        await _dispatch("plan_complete", {"task_id": "t1"})


# --- plan_block ---


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_block_success(mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "blocked": "t1",
        "reason": "Need decision",
    }
    result = await _dispatch("plan_block", {"task_id": "t1", "reason": "Need decision"})
    data = json.loads(result)
    assert data["blocked"] == "t1"


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_block_wrong_id(mock_post):
    mock_post.return_value.status_code = 400
    mock_post.return_value.json.return_value = {"detail": "Task ID mismatch"}
    with pytest.raises(ValueError, match="mismatch"):
        await _dispatch("plan_block", {"task_id": "wrong", "reason": "x"})


# --- plan_create ---


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_create_success(mock_post):
    mock_post.return_value.status_code = 201
    mock_post.return_value.json.return_value = {
        "plan_id": "plan-001",
        "tasks_created": 2,
        "current_task": "t1",
    }
    result = await _dispatch(
        "plan_create",
        {
            "goal": "Test",
            "tasks": [
                {"name": "A", "files": ["a.py"], "action": "do", "verify": "check", "done": "done"},
                {"name": "B", "files": ["b.py"], "action": "do", "verify": "check", "done": "done"},
            ],
        },
    )
    data = json.loads(result)
    assert data["tasks_created"] == 2


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_create_empty_tasks(mock_post):
    mock_post.return_value.status_code = 400
    mock_post.return_value.json.return_value = {"detail": "Plan must have at least one task"}
    with pytest.raises(ValueError, match="at least one"):
        await _dispatch("plan_create", {"goal": "Empty", "tasks": []})


# --- plan_update_task ---


@pytest.mark.asyncio
@patch("plan_mcp.requests.patch")
async def test_update_success(mock_patch):
    mock_patch.return_value.status_code = 200
    mock_patch.return_value.json.return_value = {"updated": "t1", "field": "action"}
    result = await _dispatch(
        "plan_update_task",
        {"task_id": "t1", "field": "action", "value": "new action"},
    )
    data = json.loads(result)
    assert data["updated"] == "t1"


@pytest.mark.asyncio
@patch("plan_mcp.requests.patch")
async def test_update_bad_field(mock_patch):
    mock_patch.return_value.status_code = 400
    mock_patch.return_value.json.return_value = {"detail": "Cannot update field 'status'"}
    with pytest.raises(ValueError, match="status"):
        await _dispatch(
            "plan_update_task",
            {"task_id": "t1", "field": "status", "value": "completed"},
        )


# --- Unknown tool ---


@pytest.mark.asyncio
async def test_unknown_tool():
    with pytest.raises(ValueError, match="Unknown tool"):
        await _dispatch("nonexistent_tool", {})


# --- call_tool wrapper ---


@pytest.mark.asyncio
@patch("plan_mcp.requests.get")
async def test_call_tool_success(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "plan_id": "p", "plan_goal": "g", "task": None, "message": "All done"
    }
    result = await call_tool("plan_current", {})
    assert result.isError is False


@pytest.mark.asyncio
@patch("plan_mcp.requests.get")
async def test_call_tool_error(mock_get):
    mock_get.return_value.status_code = 500
    mock_get.return_value.text = "boom"
    result = await call_tool("plan_current", {})
    assert result.isError is True
    assert "500" in result.content[0].text


@pytest.mark.asyncio
async def test_call_tool_unknown():
    result = await call_tool("nonexistent", {})
    assert result.isError is True
    assert "Unknown tool" in result.content[0].text


# --- Connection failure ---


@pytest.mark.asyncio
@patch("plan_mcp.requests.get")
async def test_connection_failure(mock_get):
    mock_get.side_effect = Exception("Connection refused")
    result = await call_tool("plan_current", {})
    assert result.isError is True
    assert "Connection refused" in result.content[0].text
