"""The typed contracts a workflow node is written against.

`results.py` is what a handler returns; `io.py` is what a binding may point a
node's input at; `definition.py` is what a node declares about itself when it
registers. Nothing here executes anything - see `app.workflows._registry` for
where a definition becomes reachable, and `app.workflows.graph` for what makes
a graph of them valid.
"""
