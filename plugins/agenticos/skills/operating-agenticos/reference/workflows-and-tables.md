# Workflows and Virtual Tables

A workflow is a typed graph of steps started by a trigger. A Virtual Table is structured, revisioned records. Tools are written `agenticos:<tool>`; match on the tool name whatever the server is called.

## Contents

- Design a workflow
- Build a workflow
- Graph shape
- Test and publish a workflow
- Run a published workflow
- Virtual Tables
- Writing records

## Design a workflow

Define the input, the observable output, the entry point, whose authority it runs under and which effects are allowed. Check `agenticos:list_workflow_definitions` for a workflow that already owns the job. Use an agent step for judgment and plain steps for everything deterministic.

The node catalog is the source of truth. `agenticos:list_workflow_nodes` returns every step with its ID, version and category:

| Category | Examples |
|---|---|
| `triggers` | `trigger.manual`, `trigger.schedule`, `trigger.webhook`, `trigger.form`, `trigger.table_record`, `trigger.channel_message`, `trigger.gmail`, `trigger.github`, `core.input` |
| `model`, `decide`, `agent` | `ai.prompt`, `ai.classify`, `ai.extract`, `decide.yes_no`, `agent.run` |
| `logic`, `control` | `logic.if`, `logic.switch`, `control.foreach`, `flow.wait`, `workflow.run` |
| `tables`, `knowledge` | `table.record.upsert`, `table.record.query`, `knowledge.search`, `knowledge.add` |
| `http`, `mcp` | `http.request`, `http.download`, `mcp.call` |
| `slack`, `telegram`, `mattermost`, `email`, `notification` | `slack.message.send`, `telegram.message.send`, `email.send`, `notification.send` |
| `data`, `transform`, `files`, `code` | `data.filter`, `transform.sort`, `file.read`, `code.python.simple` |
| `people`, `error` | `human.approval`, `error.handle` |
| `core` | `core.output`, `webhook.respond` |

Read `agenticos:get_workflow_node` for every step before placing it: its `config_schema`, `input_schema`, `output_schema` and `ports`. Never invent a step, a port or a config key.

- `ai.*` steps take a `model_profile_id`. `decide.*` steps need a decision model, the organization's or a `model_profile_id` of their own: check `decision_capable` in `agenticos:list_models`, and use `ai.classify` or `ai.prompt` when no profile has it.
- A service with no MCP server and no node is reached with `http.request` and a vault secret reference. Credentials never go in a graph.
- A schedule's cron is read in the workflow's own time zone setting, which is UTC unless changed.
- A workflow triggered by table records must not retrigger itself with its own writes.

## Build a workflow

Copy this checklist and track progress:

```
Workflow progress:
- [ ] 1. list_workflow_definitions: nothing existing owns this job
- [ ] 2. list_workflow_nodes, then get_workflow_node for each step used
- [ ] 3. Show the user the proposed graph and any table schema
- [ ] 4. prepare_workflow_draft (new) or update_workflow_draft (existing)
- [ ] 5. check_workflow_draft: graph_valid is true
- [ ] 6. test_workflow_draft with sample input the user approved
- [ ] 7. get_workflow_execution, then get_workflow_execution_steps
- [ ] 8. publish_workflow, only when the user asks
```

For a new automation, `agenticos:prepare_workflow_draft` creates the draft and an optional table in one transaction; a failure leaves neither behind. Use one local UUID as `table_placeholder_id` wherever the graph references the new table, leave `column_ids` unset and bind record values by column label.

A reference to the placeholder table is `{"kind": "table", "table_id": "<placeholder>", "schema_version": 1}`; the server replaces it with the new table. Option UUIDs of a `single_select` column do not exist until the table does, so give a column a step writes free values into the `text` type, or create the table first and read its option IDs.

To change an existing workflow, read `agenticos:get_workflow_definition`, keep the nodes, bindings and notes that are not changing, and save with `agenticos:update_workflow_draft` and the `draft_revision` just read as `expected_revision`. A definition with `can_edit: false`, such as an archived one, cannot be saved.

If step 5 or 7 reports an error, fix the graph, save it and return to step 5.

## Graph shape

```json
{
  "entry_node_id": "<uuid of the trigger node>",
  "nodes": [
    {"id": "<uuid>", "definition_id": "trigger.manual", "definition_version": 1,
     "config": {}, "layout": {"x": 0, "y": 200}, "label": "Manual"},
    {"id": "<uuid>", "definition_id": "core.output", "definition_version": 1,
     "config": {}, "layout": {"x": 300, "y": 200}, "label": "Output"}
  ],
  "edges": [
    {"id": "<uuid>", "source_node_id": "<trigger uuid>", "source_port": "out",
     "target_node_id": "<output uuid>", "target_port": "in"}
  ],
  "bindings": []
}
```

- Every `id` is a unique UUID generated for this graph. `definition_version` comes from the catalog.
- Edges connect ports by ID. Most ports are listed in the node definition's `ports`. Branching steps name their own output ports in config, and those do not appear in `ports`: `ai.classify` (`categories[].name`), `logic.switch` (`rules[].name`), `logic.split` and `error.handle` (`branches[].name`), `human.approval` (`choices[].id`). They sit beside the static ports that are listed, such as the `other` port of `ai.classify`.
- Branches that continue to a shared step rejoin through `logic.merge`. Only one `core.output` may run in a run; the validator refuses a graph where two can.
- A binding feeds one `target_field` of one node from a `source`: `node_output` (another node's port, narrowed by `field_path`), `template` (text with node outputs in it), `literal`, `table` or `file`.
- One key of an open object is bound as `field/key`: a record step's column is `values/<Column label>`.
- A branching step hands its result on through the merge: after `ai.classify` → `logic.merge`, the category is the merge's `out` port at `field_path: ["value", "category"]`.
- Labels are unique in a graph. Space nodes about 300 apart on `x` so the canvas is readable.
- A node `policy` sets `timeout_seconds`, `retry` and `on_error`; `route` sends a settled failure out of the node's `error` port.

## Test and publish a workflow

- `agenticos:check_workflow_draft` validates structure without running anything. It always reports `integration_verified: false`; it proves the graph, not the integrations.
- `agenticos:test_workflow_draft` executes the draft. Test mode still calls real APIs and writes real data. Use sample input the user approved for those effects, and `entry_node_id` to pick an entry.
- A `queued` or `running` execution is not success. Poll `agenticos:get_workflow_execution`, then read `agenticos:get_workflow_execution_steps` and check the actual records or remote effects.
- A timeout does not prove a send or write failed. Inspect before retrying.
- `agenticos:publish_workflow` activates the configured triggers, including unattended ones. Describe what becomes active first. Unattended authority needs a member session: if a key is refused, the user finishes publishing in the console. One-time signing secrets are shown in the console, not returned.

## Run a published workflow

1. `agenticos:get_workflow_input_schema` returns each Manual or API entry's `entry_node_id` and `input_schema`.
2. `agenticos:run_workflow` with that `entry_node_id` and matching `fields`.
3. The result is the admitted run, not its outcome. Poll `agenticos:get_workflow_execution` and read the steps.

Form and Called by a workflow entries cannot be started this way.

## Virtual Tables

Use a table for structured state an automation reads and writes. It does not replace a knowledge base or a transcript, and secrets never belong in one.

1. `agenticos:list_virtual_tables` (`q` searches name and description) before creating another.
2. `agenticos:get_virtual_table` for column IDs, types, option IDs and `schema_version`.
3. `agenticos:query_virtual_table` with a `query` object holding `filters` (`column_id`, `op`, `value`), `search`, `sort` and `limit`. Follow `has_more`.

`agenticos:create_virtual_table` makes a private table. Publishing an agent or workflow does not share it; sharing is done in the console.

`agenticos:update_virtual_table_schema` submits the entire column list against `expected_version`. Keep every existing column with its `id`; a column left out is archived. Add a column by sending it without an `id`.

Managed task boards are tables too. Change them with the task tools, not the record tools.

## Writing records

| Goal | Tool | Needs |
|---|---|---|
| Add one record | `agenticos:add_virtual_table_record` | values keyed by column UUID |
| Create or update by source identity | `agenticos:upsert_virtual_table_record` | `external_id`; `expected_revision` when the record exists |
| Change some cells | `agenticos:update_virtual_table_record` | `expected_revision`; omitted cells stay, `null` clears |
| Delete | `agenticos:delete_virtual_table_record` | `expected_revision` |

- The write fields are nested: `update: {expected_revision, values}` on an update, `record: {expected_revision, values}` on an upsert.
- `agenticos:virtual_table_record_exists` checks an `external_id`. A refusal does not mean the record is absent.
- An upsert of a record that already exists needs its `expected_revision`, and no tool looks a record up by `external_id`: page `agenticos:query_virtual_table` and match `external_id` in the results to get the ID and revision.
- Invalid values are refused, never converted. Fix the value to the column's type.
- For syncing from another system, always use `external_id` so reruns are idempotent.
