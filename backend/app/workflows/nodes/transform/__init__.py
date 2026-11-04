"""The Transform steps - registration and nothing else. See `_handler.py` and `README.md`."""

from pydantic import BaseModel

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, NodeHandler, Port
from app.workflows.nodes._transform import ItemsInput, ItemsOutput
from app.workflows.nodes.transform import _handler as steps

_STEPS: tuple[
    tuple[str, str, str, type[BaseModel] | None, type[BaseModel], type[BaseModel], NodeHandler], ...
] = (
    (
        "edit_fields",
        "Edit fields",
        "Set, rename or remove fields on every item of a list.",
        steps.EditFieldsConfig,
        ItemsInput,
        ItemsOutput,
        steps.edit_fields,
    ),
    (
        "sort",
        "Sort",
        "Sort the items of a list by one or more fields.",
        steps.SortConfig,
        ItemsInput,
        ItemsOutput,
        steps.sort,
    ),
    (
        "limit",
        "Limit",
        "Keep the first or the last items of a list.",
        steps.LimitConfig,
        ItemsInput,
        ItemsOutput,
        steps.limit,
    ),
    (
        "remove_duplicates",
        "Remove duplicates",
        "Keep one of each set of items equal on some fields.",
        steps.RemoveDuplicatesConfig,
        ItemsInput,
        ItemsOutput,
        steps.remove_duplicates,
    ),
    (
        "aggregate",
        "Aggregate",
        "Collect a field's values across the items into one list.",
        steps.AggregateConfig,
        ItemsInput,
        steps.AggregateOutput,
        steps.aggregate,
    ),
    (
        "split_out",
        "Split out",
        "Turn a list inside each item into items of their own.",
        steps.SplitOutConfig,
        ItemsInput,
        ItemsOutput,
        steps.split_out,
    ),
    (
        "summarize",
        "Summarize",
        "Count, sum or average the items, by group.",
        steps.SummarizeConfig,
        ItemsInput,
        ItemsOutput,
        steps.summarize,
    ),
    (
        "date_time",
        "Date & time",
        "Now, or a moment moved and written out in a timezone.",
        steps.DateTimeConfig,
        steps.DateTimeInput,
        steps.DateTimeOutput,
        steps.date_time,
    ),
    (
        "crypto",
        "Crypto",
        "Hash or encode text, or make an id or a random value.",
        steps.CryptoConfig,
        steps.CryptoInput,
        steps.CryptoOutput,
        steps.crypto,
    ),
)

for key, name, description, config, node_input, output, handler in _STEPS:
    register(
        NodeDefinition(
            id=f"transform.{key}",
            version=1,
            name=name,
            category="transform",
            description=description,
            kind="action",
            config_schema=config,
            input_schema=node_input,
            output_schema=output,
            ports=(
                Port(id="in", label="In", kind="input", schema=None),
                Port(id="out", label="Out", kind="output", schema=output),
            ),
            effect_kind="pure",
            retry_guarantee="idempotent",
            handler=handler,
        )
    )
