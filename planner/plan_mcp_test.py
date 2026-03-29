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
        "task": {"id": "t1", "name": "First", "files": ["a.py"],
                 "action": "do", "verify": "check", "done": "done"},
    }
    result = await _dispatch("plan_current", {})
    data = json.loads(result)
    assert data["task"]["id"] == "t1"
    assert data["plan_id"] == "plan-001"


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


@pytest.mark.asyncio
@patch("plan_mcp.requests.get")
async def test_current_connection_failure(mock_get):
    mock_get.side_effect = Exception("Connection refused")
    with pytest.raises(Exception, match="Connection refused"):
        await _dispatch("plan_current", {})


# --- plan_list ---


@pytest.mark.asyncio
@patch("plan_mcp.requests.get")
async def test_list_success(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "plan_id": "plan-001",
        "plan_goal": "Test",
        "tasks": [
            {"id": "t1", "name": "First", "status": "completed"},
            {"id": "t2", "name": "Second", "status": "current"},
        ],
    }
    result = await _dispatch("plan_list", {})
    data = json.loads(result)
    assert len(data["tasks"]) == 2
    assert data["tasks"][1]["status"] == "current"


@pytest.mark.asyncio
@patch("plan_mcp.requests.get")
async def test_list_no_plan(mock_get):
    mock_get.return_value.status_code = 404
    result = await _dispatch("plan_list", {})
    data = json.loads(result)
    assert "no active plan" in data["message"].lower()


@pytest.mark.asyncio
@patch("plan_mcp.requests.get")
async def test_list_server_error(mock_get):
    mock_get.return_value.status_code = 500
    mock_get.return_value.text = "boom"
    with pytest.raises(RuntimeError, match="500"):
        await _dispatch("plan_list", {})


# --- plan_complete ---


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_complete_success(mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "completed": "t1",
        "next": {"id": "t2", "name": "Second", "files": ["b.py"],
                 "action": "do", "verify": "check", "done": "done"},
    }
    result = await _dispatch("plan_complete", {"task_id": "t1"})
    data = json.loads(result)
    assert data["completed"] == "t1"
    assert data["next"]["id"] == "t2"


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_complete_wrong_id(mock_post):
    mock_post.return_value.status_code = 400
    mock_post.return_value.json.return_value = {"detail": "Task ID mismatch: current is t2, got wrong"}
    with pytest.raises(ValueError, match="mismatch"):
        await _dispatch("plan_complete", {"task_id": "wrong"})


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_complete_no_plan(mock_post):
    mock_post.return_value.status_code = 404
    with pytest.raises(FileNotFoundError):
        await _dispatch("plan_complete", {"task_id": "t1"})


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_complete_server_error(mock_post):
    mock_post.return_value.status_code = 500
    mock_post.return_value.text = "crash"
    with pytest.raises(RuntimeError, match="500"):
        await _dispatch("plan_complete", {"task_id": "t1"})


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_complete_all_done(mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "completed": "t3",
        "message": "All tasks completed",
    }
    result = await _dispatch("plan_complete", {"task_id": "t3"})
    data = json.loads(result)
    assert data["completed"] == "t3"
    assert "completed" in data["message"].lower()


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
    assert data["reason"] == "Need decision"


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_block_wrong_id(mock_post):
    mock_post.return_value.status_code = 400
    mock_post.return_value.json.return_value = {"detail": "Task ID mismatch"}
    with pytest.raises(ValueError, match="mismatch"):
        await _dispatch("plan_block", {"task_id": "wrong", "reason": "x"})


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_block_no_plan(mock_post):
    mock_post.return_value.status_code = 404
    with pytest.raises(FileNotFoundError):
        await _dispatch("plan_block", {"task_id": "t1", "reason": "x"})


# --- plan_block with context ---


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_block_with_context(mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "blocked": "t1",
        "reason": "Need decision",
    }
    result = await _dispatch(
        "plan_block",
        {"task_id": "t1", "reason": "Need decision", "context": "Wrote 50% of the code"},
    )
    data = json.loads(result)
    assert data["blocked"] == "t1"
    # Verify context was passed in the request body
    call_kwargs = mock_post.call_args
    assert call_kwargs.kwargs["json"]["context"] == "Wrote 50% of the code"


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_block_without_context_omits_key(mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"blocked": "t1", "reason": "x"}
    await _dispatch("plan_block", {"task_id": "t1", "reason": "x"})
    call_kwargs = mock_post.call_args
    assert "context" not in call_kwargs.kwargs["json"]


# --- plan_unblock ---


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_unblock_success(mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "unblocked": "t2",
        "task": {"id": "t2", "name": "Fix it", "files": ["b.py"],
                 "action": "do", "verify": "check", "done": "done"},
        "blockers": ["Need decision"],
        "resume_context": "Wrote 50% of the code",
    }
    result = await _dispatch("plan_unblock", {"task_id": "t2"})
    data = json.loads(result)
    assert data["unblocked"] == "t2"
    assert data["resume_context"] == "Wrote 50% of the code"
    assert data["blockers"] == ["Need decision"]


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_unblock_not_blocked(mock_post):
    mock_post.return_value.status_code = 400
    mock_post.return_value.json.return_value = {"detail": "Task t2 is not blocked (status: current)"}
    with pytest.raises(ValueError, match="not blocked"):
        await _dispatch("plan_unblock", {"task_id": "t2"})


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_unblock_task_not_found(mock_post):
    mock_post.return_value.status_code = 404
    with pytest.raises(FileNotFoundError):
        await _dispatch("plan_unblock", {"task_id": "t99"})


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_unblock_server_error(mock_post):
    mock_post.return_value.status_code = 500
    mock_post.return_value.text = "crash"
    with pytest.raises(RuntimeError, match="500"):
        await _dispatch("plan_unblock", {"task_id": "t2"})


# --- plan_create ---


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_create_success(mock_post):
    mock_post.return_value.status_code = 201
    mock_post.return_value.json.return_value = {
        "plan_id": "plan-20260317-120000",
        "filename": "plan-2026-03-17-ab1cd.json",
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
    assert data["current_task"] == "t1"


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_create_empty_tasks(mock_post):
    mock_post.return_value.status_code = 400
    mock_post.return_value.json.return_value = {"detail": "Plan must have at least one task"}
    with pytest.raises(ValueError, match="at least one"):
        await _dispatch("plan_create", {"goal": "Empty", "tasks": []})


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_create_server_error(mock_post):
    mock_post.return_value.status_code = 500
    mock_post.return_value.text = "crash"
    with pytest.raises(RuntimeError, match="500"):
        await _dispatch("plan_create", {"goal": "X", "tasks": [{"name": "T", "files": [], "action": "x", "verify": "x", "done": "x"}]})


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
    assert data["field"] == "action"


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


@pytest.mark.asyncio
@patch("plan_mcp.requests.patch")
async def test_update_unknown_task(mock_patch):
    mock_patch.return_value.status_code = 404
    mock_patch.return_value.json.return_value = {"detail": "Task t99 not found"}
    with pytest.raises(ValueError, match="t99"):
        await _dispatch(
            "plan_update_task",
            {"task_id": "t99", "field": "name", "value": "x"},
        )


@pytest.mark.asyncio
@patch("plan_mcp.requests.patch")
async def test_update_server_error(mock_patch):
    mock_patch.return_value.status_code = 500
    mock_patch.return_value.text = "crash"
    with pytest.raises(RuntimeError, match="500"):
        await _dispatch(
            "plan_update_task",
            {"task_id": "t1", "field": "name", "value": "x"},
        )


# --- Unknown tool ---


@pytest.mark.asyncio
async def test_unknown_tool():
    with pytest.raises(ValueError, match="Unknown tool"):
        await _dispatch("nonexistent_tool", {})


# --- call_tool wrapper: success returns isError=False ---


@pytest.mark.asyncio
@patch("plan_mcp.requests.get")
async def test_call_tool_success(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "plan_id": "p", "plan_goal": "g", "task": None, "message": "All done"
    }
    result = await call_tool("plan_current", {})
    assert result.isError is False
    assert len(result.content) > 0


# --- call_tool wrapper: error returns isError=True ---


@pytest.mark.asyncio
@patch("plan_mcp.requests.get")
async def test_call_tool_server_error(mock_get):
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


@pytest.mark.asyncio
@patch("plan_mcp.requests.get")
async def test_call_tool_connection_failure(mock_get):
    mock_get.side_effect = Exception("Connection refused")
    result = await call_tool("plan_current", {})
    assert result.isError is True
    assert "Connection refused" in result.content[0].text


@pytest.mark.asyncio
@patch("plan_mcp.requests.post")
async def test_call_tool_complete_error(mock_post):
    mock_post.return_value.status_code = 400
    mock_post.return_value.json.return_value = {"detail": "Task ID mismatch"}
    result = await call_tool("plan_complete", {"task_id": "wrong"})
    assert result.isError is True
    assert "mismatch" in result.content[0].text
