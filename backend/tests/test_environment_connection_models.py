"""The two rows behind test connections and isolated runs, read in memory.

`test_id` is the one place that decides which column an override's test side
is read from, so both kinds are pinned here; a repr names a row by ids, never
by anything a vault holds.
"""

import uuid

from app.db.models.agent_environment import AgentEnvironmentConnection
from app.db.models.intercepted_tool_call import InterceptedToolCall


def test_each_kind_reads_its_own_test_column():
    connection, secret = uuid.uuid4(), uuid.uuid4()
    mcp = AgentEnvironmentConnection(
        kind="mcp", production_id=uuid.uuid4(), test_connection_id=connection, test_secret_id=secret
    )
    vault = AgentEnvironmentConnection(
        kind="secret",
        production_id=uuid.uuid4(),
        test_connection_id=connection,
        test_secret_id=secret,
    )

    assert (mcp.test_id, vault.test_id) == (connection, secret)


def test_the_rows_name_themselves_by_ids():
    production = uuid.uuid4()
    override = AgentEnvironmentConnection(kind="secret", production_id=production)
    held = InterceptedToolCall(tool_name="send_email", outcome="blocked")

    assert str(production) in repr(override)
    assert "send_email" in repr(held) and "blocked" in repr(held)
