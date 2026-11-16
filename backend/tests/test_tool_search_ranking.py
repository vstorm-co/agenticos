"""Discovery must retain each requested operation, including long MCP descriptions."""

from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext, ToolDefinition
from pydantic_ai.usage import RunUsage

from app.agents.capabilities.tool_search._ranking import rank_tools


def test_search_and_fetch_queries_each_reveal_the_requested_operation() -> None:
    ctx = RunContext(deps=None, model=TestModel(), usage=RunUsage())
    tools = [
        ToolDefinition(name="notion_notion-search", description="Search pages"),
        ToolDefinition(
            name="notion_notion-fetch",
            description=(
                "Retrieve a Notion page by URL or ID. "
                + "Pages contain Markdown, metadata, links and references. " * 60
            ),
        ),
        *[
            ToolDefinition(name=f"notion_notion-{action}", description="Search Notion pages")
            for action in (
                "get-users",
                "update-page",
                "memory-search",
                "search-agents",
                "move-pages",
            )
        ],
    ]

    found = rank_tools(ctx, ["notion search", "notion fetch page"], tools)

    assert list(found[:2]) == ["notion_notion-search", "notion_notion-fetch"]
    assert len(found) == len(set(found))
    assert set(found) <= {tool.name for tool in tools}


def test_an_exact_operation_is_not_outvoted_by_a_broad_second_query() -> None:
    ctx = RunContext(deps=None, model=TestModel(), usage=RunUsage())
    tools = [ToolDefinition(name="docs_fetch", description="Fetch a document. " * 100)]
    tools.extend(
        ToolDefinition(name=f"search_{index}", description="Search a document")
        for index in range(10)
    )

    assert rank_tools(ctx, ["docs_fetch", "search document"], tools)[0] == "docs_fetch"
