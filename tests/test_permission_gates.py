import pytest
from twin.hooks import Decision, PermissionMode, PermissionPolicy
from twin.tools.base import ToolContext
from twin.sandbox.local import LocalSandbox


@pytest.mark.asyncio
async def test_permission_auto_mode():
    policy = PermissionPolicy(mode=PermissionMode.AUTO)
    ctx = ToolContext(user_id="u1", session_id="s1", run_id="r1", sandbox=None)

    outcome_read = await policy.check("read_file", mutates=False, args={"path": "a.txt"}, ctx=ctx)
    assert outcome_read.decision == Decision.ALLOW

    outcome_write = await policy.check("write_file", mutates=True, args={"path": "a.txt"}, ctx=ctx)
    assert outcome_write.decision == Decision.ALLOW


@pytest.mark.asyncio
async def test_permission_deny_mode():
    policy = PermissionPolicy(mode=PermissionMode.DENY)
    ctx = ToolContext(user_id="u1", session_id="s1", run_id="r1", sandbox=None)

    outcome_read = await policy.check("read_file", mutates=False, args={"path": "a.txt"}, ctx=ctx)
    assert outcome_read.decision == Decision.ALLOW

    outcome_write = await policy.check("write_file", mutates=True, args={"path": "a.txt"}, ctx=ctx)
    assert outcome_write.decision == Decision.DENY
    assert "read-only" in outcome_write.reason


@pytest.mark.asyncio
async def test_permission_ask_mode_approved():
    async def mock_approve(tool_name, args, ctx):
        return True

    policy = PermissionPolicy(mode=PermissionMode.ASK, approve=mock_approve)
    ctx = ToolContext(user_id="u1", session_id="s1", run_id="r1", sandbox=None)

    outcome_read = await policy.check("read_file", mutates=False, args={"path": "a.txt"}, ctx=ctx)
    assert outcome_read.decision == Decision.ALLOW

    outcome_write = await policy.check("write_file", mutates=True, args={"path": "a.txt"}, ctx=ctx)
    assert outcome_write.decision == Decision.ALLOW


@pytest.mark.asyncio
async def test_permission_ask_mode_declined():
    async def mock_decline(tool_name, args, ctx):
        return False

    policy = PermissionPolicy(mode=PermissionMode.ASK, approve=mock_decline)
    ctx = ToolContext(user_id="u1", session_id="s1", run_id="r1", sandbox=None)

    outcome_write = await policy.check("write_file", mutates=True, args={"path": "a.txt"}, ctx=ctx)
    assert outcome_write.decision == Decision.DENY
    assert "declined" in outcome_write.reason


@pytest.mark.asyncio
async def test_permission_ask_mode_missing_callback_fails_safe():
    policy = PermissionPolicy(mode=PermissionMode.ASK, approve=None)
    ctx = ToolContext(user_id="u1", session_id="s1", run_id="r1", sandbox=None)

    outcome_write = await policy.check("write_file", mutates=True, args={"path": "a.txt"}, ctx=ctx)
    assert outcome_write.decision == Decision.DENY
    assert "no approver is configured" in outcome_write.reason
