"""Workflows: typed node contracts, a registry and graph validation.

A workflow is a graph of typed nodes an organization composes visually. This
package defines what a node *is* - a :class:`~app.workflows.contracts.definition.NodeDefinition`,
declared once in code and looked up by `(id, version)` - and what a graph must
satisfy before it can be published: see `app.workflows.graph.validate.validate_graph`.

Mirrors `app.agents.capabilities` deliberately: a developer who already knows
how to add a capability already knows the shape of adding a node.

No execution lives here. `app.workflows.contracts.results.NodeResult` is the
typed answer a handler returns; interpreting `Waiting`/`Uncertain` and actually
running a graph is a durable-execution engine this package does not contain.
"""
