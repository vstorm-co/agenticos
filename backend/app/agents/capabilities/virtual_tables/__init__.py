"""Virtual Tables capability - read and write the tables an agent is granted."""

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.virtual_tables._capability import (
    TableGrant,
    VirtualTables,
    VirtualTablesConfig,
)

__all__ = ["TableGrant", "VirtualTables", "VirtualTablesConfig"]


def _reads(tool_id: str, description: str) -> CapabilityToolInfo:
    return CapabilityToolInfo(id=tool_id, description=description, side_effecting=False)


def _writes(tool_id: str, description: str) -> CapabilityToolInfo:
    return CapabilityToolInfo(id=tool_id, description=description, side_effecting=True)


@register(
    id="virtual_tables",
    name="Tables",
    category="data",
    description="Read and write the Virtual Tables this agent is granted.",
    # Per tool, because the capability both reads and writes: gating the whole of
    # it would make an agent ask permission to list its tables, and not gating it
    # would let a delete run unattended.
    tools=(
        _reads("list_tables", "List the tables this agent may use, with what it may do in each."),
        _reads(
            "table_exists", "Check whether a granted table still exists, is live and can be read."
        ),
        _reads(
            "describe_table",
            "Describe a table's live columns: id, label, type, and options for a select.",
        ),
        _writes("create_table", "Create a new table with the given columns."),
        _reads(
            "record_exists",
            "Check whether a record with this external id exists, without reading it.",
        ),
        _reads("list_records", "List a table's records, optionally filtered and sorted."),
        _reads("get_record", "Read one record by its id or by its external id."),
        _writes("create_record", "Add a record to a table."),
        _writes(
            "upsert_record", "Create the record with this external id, or update it if it exists."
        ),
        _writes("update_record", "Change some of a record's cells; `null` clears one."),
        _writes("delete_record", "Delete a record. Its history is kept."),
    ),
    config_schema=VirtualTablesConfig,
    scopes=("tables:read",),
)
def _build(ctx: CapabilityBuildContext) -> VirtualTables | None:
    """Build the capability, or nothing when it grants no table and may create none.

    An agent with the capability and no grant would advertise tools that can only
    refuse - worse than not having them, because the model keeps trying.
    """
    config = ctx.config if isinstance(ctx.config, VirtualTablesConfig) else VirtualTablesConfig()
    if not config.tables and not config.allow_create:
        return None
    return VirtualTables(
        grants={grant.table_id: frozenset(grant.operations) for grant in config.tables},
        allow_create=config.allow_create,
    )
