---
name: platform-tables
description: "Build useful AgenticOS tables with typed columns, rich-text notes, real user/agent references, views, default Kanban and conflict-safe writes. Reuse managed Task boards for TODOs and connect records to workflows and Apps."
category: data
---

# Design records around a decision

Use this skill for designing a substantial data model or repairing confusing views, not for listing, creating or updating ordinary records. Current MCP descriptions and schemas own the API contract.

Decide what one row represents, which source owns it, who can see it and which decision the view should support. Reuse existing operational data. For commitments, use the managed task system rather than inventing a parallel TODO schema.

Keep properties people filter or compare in typed columns. Put narrative, checklists and acceptance criteria in rich text. Use actual person, agent and record relations instead of names as identifiers. Distinguish responsibility, who acts next, a deadline and a scheduled start. Defaults should help without inventing facts.

Choose a small set of states with clear meanings and transitions. Use English column names and choices unless requested otherwise; leave authored content in its original language. Validate the model with one realistic record before bulk work.

Use Kanban for progression, a grid for comparison and a list for document-like records. Each saved view should answer a distinct question. Respect dependent workflows and retained history when evolving a schema. Show the resulting view and verify it against the person's intended decision. Obtain write parameters and concurrency rules from the selected MCP operation, not a copied recipe.
