"""Agents built from published specs.

There is exactly one way to get a runnable agent: :func:`app.agents.factory.build_agent`,
fed by an :class:`app.agents.spec.AgentSpec`. Surfaces reach it through
`app.services.agent_runner`; nothing here is imported as a ready-made agent.
"""
