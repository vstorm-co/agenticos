---
name: pydantic-ai-import
description: Bring an agent written with Pydantic AI into AgenticOS - read its code, map it to a draft, say what did not translate.
category: engineering
---

# Importing a Pydantic AI agent

The person pastes code or drops a file. Read it before saying anything.

## Find

- **Instructions** - `instructions=` or `system_prompt=` on the `Agent(...)`, and
  any `@agent.instructions` / `@agent.system_prompt` functions (their text, and
  what dynamic values they insert).
- **Model** - the first argument or `model=`: provider and model name.
- **Tools** - `@agent.tool`, `@agent.tool_plain`, `tools=[...]`, toolsets and
  MCP servers (`MCPServerStdio`, `MCPServerStreamableHTTP`).
- **Output** - `output_type=`: plain text or a structured model.
- **Dependencies** - `deps_type=` and what the tools read from it.

## Map

- Instructions → the draft's instructions; dynamic values → `{{variables}}`.
- Model → the closest model profile the organization has (list them); else say
  which provider key to add.
- Each tool → a capability when one does the same thing (list capabilities
  first): web search, fetching pages, running code, files, charts, knowledge
  search. An MCP server → an MCP connection the person adds.
- Custom Python tools with no capability → say so; they become an MCP server of
  the company's own, or are dropped.

## Then

Create the draft with what maps, and answer with a table: *came across* /
*needs you* / *did not translate, and why*. Link the draft in the Builder.
