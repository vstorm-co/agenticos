"""Builtin workflow node packages.

Each subpackage registers one or more `NodeDefinition`s in its `__init__.py`,
the same layout `app.agents.capabilities` enforces for a capability:
`__init__.py` for registration, `_handler.py` for the logic, `README.md` for
why it exists. `tests/test_workflow_node_layout.py` enforces the shape, and
`app.workflows._registry.load_builtins` is what makes a package here reachable
at all - importing it is what runs its `register()` calls.
"""
