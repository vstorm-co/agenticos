"""The graph a workflow's draft and published versions actually store.

`model.py` is the shape (nodes, edges, bindings, scope boundaries);
`validate.py` is what a graph must satisfy before it can be published;
`errors.py` is the one refusal shape validation raises. Nothing here executes
a graph - see the module docstring of `app.workflows`.
"""
