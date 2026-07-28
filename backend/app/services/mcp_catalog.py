"""A curated catalog of MCP servers an organization can connect in one click.

MCP is the platform's answer to "we cannot write a connector for everything":
a client points at a server and its tools appear in the Builder with no code on
our side. But a picker that starts empty and asks for a URL is a picker nobody
uses, so the common servers are listed here with the metadata needed to connect
them.

This is deliberately a hand-maintained list rather than a mirror of the public
registry. Each entry is a small promise — that we have looked at the server, that
the auth flow works, that the description is honest — and a mirrored registry
cannot make that promise. Adding an entry is cheap; the URL is what varies.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CatalogAuth(StrEnum):
    """How a server authenticates, which is the only thing that really varies."""

    NONE = "none"
    TOKEN = "token"
    OAUTH = "oauth"


@dataclass(frozen=True)
class CatalogEntry:
    """One connectable server."""

    key: str
    name: str
    description: str
    category: str
    auth: CatalogAuth
    # Where the server lives. Empty when the client hosts it themselves and must
    # supply the URL — self-hosted databases, internal services.
    url: str = ""
    docs_url: str = ""
    # What to tell the person pasting a credential. Generic instructions are the
    # main reason token setup fails.
    token_hint: str = ""
    # The brand mark to draw, as `BrandIcon` names them. Empty falls back to a
    # monogram, which is a deliberate look rather than a missing one — every
    # icon set is finite and this catalog is not.
    icon: str = ""


CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        key="github",
        name="GitHub",
        description="Read issues, pull requests and code across an organization's repositories.",
        category="development",
        auth=CatalogAuth.TOKEN,
        url="https://api.githubcopilot.com/mcp/",
        docs_url="https://github.com/github/github-mcp-server",
        token_hint="A fine-grained personal access token with read access to the repositories the agent should see.",
        icon="github",
    ),
    CatalogEntry(
        key="linear",
        name="Linear",
        description="Search and update issues, projects and cycles.",
        category="project-management",
        auth=CatalogAuth.OAUTH,
        url="https://mcp.linear.app/sse",
        docs_url="https://linear.app/docs/mcp",
        icon="linear",
    ),
    CatalogEntry(
        key="notion",
        name="Notion",
        description="Search pages and databases in a Notion workspace.",
        category="knowledge",
        auth=CatalogAuth.OAUTH,
        url="https://mcp.notion.com/mcp",
        docs_url="https://developers.notion.com/docs/mcp",
        icon="notion",
    ),
    CatalogEntry(
        key="sentry",
        name="Sentry",
        description="Look up errors, issues and releases.",
        category="observability",
        auth=CatalogAuth.OAUTH,
        url="https://mcp.sentry.dev/mcp",
        docs_url="https://docs.sentry.io/product/sentry-mcp/",
        icon="sentry",
    ),
    CatalogEntry(
        key="postgres",
        name="PostgreSQL",
        description="Query a database over read-only views. Self-hosted: you supply the URL.",
        category="data",
        auth=CatalogAuth.TOKEN,
        docs_url="https://github.com/modelcontextprotocol/servers/tree/main/src/postgres",
        token_hint="Point this at a server you run against read-only views — never at a primary with write access.",
        icon="postgres",
    ),
    CatalogEntry(
        key="slack",
        name="Slack",
        description="Read channels and threads, search history, post messages.",
        category="communication",
        auth=CatalogAuth.OAUTH,
        url="https://mcp.slack.com/mcp",
        docs_url="https://docs.slack.dev/mcp/",
        icon="slack",
    ),
    CatalogEntry(
        key="atlassian",
        name="Jira & Confluence",
        description="Search issues and pages, read sprints, comment.",
        category="project-management",
        auth=CatalogAuth.OAUTH,
        url="https://mcp.atlassian.com/v1/sse",
        docs_url="https://support.atlassian.com/rovo/docs/getting-started-with-the-atlassian-remote-mcp-server/",
        icon="atlassian",
    ),
    CatalogEntry(
        key="asana",
        name="Asana",
        description="Read and update tasks, projects and portfolios.",
        category="project-management",
        auth=CatalogAuth.OAUTH,
        url="https://mcp.asana.com/sse",
        docs_url="https://developers.asana.com/docs/mcp-server",
        icon="asana",
    ),
    CatalogEntry(
        key="intercom",
        name="Intercom",
        description="Search conversations, contacts and help-centre articles.",
        category="support",
        auth=CatalogAuth.OAUTH,
        url="https://mcp.intercom.com/sse",
        docs_url="https://developers.intercom.com/docs/guides/mcp",
        icon="intercom",
    ),
    CatalogEntry(
        key="stripe",
        name="Stripe",
        description="Look up customers, subscriptions, invoices and payments.",
        category="finance",
        auth=CatalogAuth.TOKEN,
        url="https://mcp.stripe.com",
        docs_url="https://docs.stripe.com/mcp",
        token_hint=(
            "A restricted API key. Give it read scopes only unless an agent is meant to move "
            "money — this server can act, and the approval gate does not cover MCP tools."
        ),
        icon="stripe",
    ),
    CatalogEntry(
        key="paypal",
        name="PayPal",
        description="Read orders, invoices, disputes and transactions.",
        category="finance",
        auth=CatalogAuth.OAUTH,
        url="https://mcp.paypal.com/sse",
        docs_url="https://developer.paypal.com/tools/mcp-server/",
        icon="paypal",
    ),
    CatalogEntry(
        key="cloudflare-docs",
        name="Cloudflare docs",
        description="Search Cloudflare's product documentation. No credentials needed.",
        category="development",
        auth=CatalogAuth.NONE,
        url="https://docs.mcp.cloudflare.com/mcp",
        docs_url="https://developers.cloudflare.com/agents/model-context-protocol/mcp-servers-for-cloudflare/",
        icon="cloudflare",
    ),
    CatalogEntry(
        key="gitlab",
        name="GitLab",
        description="Read merge requests, issues and pipelines. Self-hosted: you supply the URL.",
        category="development",
        auth=CatalogAuth.TOKEN,
        docs_url="https://docs.gitlab.com/user/gitlab_duo/model_context_protocol/mcp_server/",
        token_hint="A project or group access token with read_api scope.",
        icon="gitlab",
    ),
    CatalogEntry(
        key="supabase",
        name="Supabase",
        description="Query a project's tables and read its schema over the management API.",
        category="data",
        auth=CatalogAuth.TOKEN,
        docs_url="https://supabase.com/docs/guides/getting-started/mcp",
        token_hint=(
            "A personal access token. Point it at a read-only project or a branch — the server "
            "can run SQL."
        ),
        icon="supabase",
    ),
    CatalogEntry(
        key="grafana",
        name="Grafana",
        description="Query dashboards, panels and alert rules. Self-hosted: you supply the URL.",
        category="observability",
        auth=CatalogAuth.TOKEN,
        docs_url="https://github.com/grafana/mcp-grafana",
        token_hint="A service-account token with Viewer permissions on the folders it should see.",
        icon="grafana",
    ),
    CatalogEntry(
        key="elasticsearch",
        name="Elasticsearch",
        description="Search indices and read mappings. Self-hosted: you supply the URL.",
        category="data",
        auth=CatalogAuth.TOKEN,
        docs_url="https://github.com/elastic/mcp-server-elasticsearch",
        token_hint="An API key scoped to the indices the agent should read, and no others.",
        icon="elastic",
    ),
    CatalogEntry(
        key="hubspot",
        name="HubSpot",
        description="Read and update contacts, companies, deals and tickets.",
        category="sales",
        auth=CatalogAuth.OAUTH,
        icon="hubspot",
    ),
    CatalogEntry(
        key="airtable",
        name="Airtable",
        description="Read and write bases, tables and records.",
        category="data",
        auth=CatalogAuth.TOKEN,
        token_hint="A personal access token scoped to the bases the agent should see.",
        icon="airtable",
    ),
    CatalogEntry(
        key="zapier",
        name="Zapier",
        description="Run Zaps and reach the apps behind them.",
        category="automation",
        auth=CatalogAuth.OAUTH,
        icon="zapier",
    ),
    CatalogEntry(
        key="make",
        name="Make",
        description="Run scenarios and manage a Make account.",
        category="automation",
        auth=CatalogAuth.TOKEN,
        icon="make",
    ),
    CatalogEntry(
        key="n8n",
        name="n8n",
        description="Access and run workflows. Self-hosted: you supply the URL.",
        category="automation",
        auth=CatalogAuth.TOKEN,
        icon="n8n",
    ),
    CatalogEntry(
        key="clickup",
        name="ClickUp",
        description="Tasks, docs and goals across spaces.",
        category="project-management",
        auth=CatalogAuth.OAUTH,
        icon="clickup",
    ),
    CatalogEntry(
        key="trello",
        name="Trello",
        description="Boards, lists and cards.",
        category="project-management",
        auth=CatalogAuth.OAUTH,
        icon="trello",
    ),
    CatalogEntry(
        key="todoist",
        name="Todoist",
        description="Search, complete and manage tasks.",
        category="project-management",
        auth=CatalogAuth.OAUTH,
        icon="todoist",
    ),
    CatalogEntry(
        key="calendly",
        name="Calendly",
        description="Event types, availability and bookings.",
        category="productivity",
        auth=CatalogAuth.OAUTH,
        icon="calendly",
    ),
    CatalogEntry(
        key="zoom",
        name="Zoom",
        description="Search, recap and act on meetings.",
        category="communication",
        auth=CatalogAuth.OAUTH,
        icon="zoom",
    ),
    CatalogEntry(
        key="miro",
        name="Miro",
        description="Read and create content on boards.",
        category="design",
        auth=CatalogAuth.OAUTH,
        icon="miro",
    ),
    CatalogEntry(
        key="lucid",
        name="Lucid",
        description="Diagram, ideate and align teams.",
        category="design",
        auth=CatalogAuth.OAUTH,
        icon="lucid",
    ),
    CatalogEntry(
        key="excalidraw",
        name="Excalidraw",
        description="Create hand-drawn style diagrams.",
        category="design",
        auth=CatalogAuth.NONE,
        icon="excalidraw",
    ),
    CatalogEntry(
        key="box",
        name="Box",
        description="Search, edit and get insights on Box content.",
        category="storage",
        auth=CatalogAuth.OAUTH,
        icon="box",
    ),
    CatalogEntry(
        key="dropbox",
        name="Dropbox",
        description="Search, organize and act on Dropbox content.",
        category="storage",
        auth=CatalogAuth.OAUTH,
        icon="dropbox",
    ),
    CatalogEntry(
        key="shopify",
        name="Shopify",
        description="Build, manage and analyze a store.",
        category="commerce",
        auth=CatalogAuth.OAUTH,
        icon="shopify",
    ),
    CatalogEntry(
        key="mailchimp",
        name="Mailchimp",
        description="Create and analyze marketing campaigns.",
        category="marketing",
        auth=CatalogAuth.OAUTH,
        icon="mailchimp",
    ),
    CatalogEntry(
        key="resend",
        name="Resend",
        description="Send transactional and marketing email.",
        category="marketing",
        auth=CatalogAuth.TOKEN,
        token_hint="An API key. Sending is a side effect — scope it to one domain.",
        icon="resend",
    ),
    CatalogEntry(
        key="posthog",
        name="PostHog",
        description="Query and manage product analytics.",
        category="analytics",
        auth=CatalogAuth.TOKEN,
        icon="posthog",
    ),
    CatalogEntry(
        key="mixpanel",
        name="Mixpanel",
        description="Analyze and query events.",
        category="analytics",
        auth=CatalogAuth.TOKEN,
        icon="mixpanel",
    ),
    CatalogEntry(
        key="snowflake",
        name="Snowflake",
        description="Retrieve structured and unstructured data.",
        category="data",
        auth=CatalogAuth.TOKEN,
        token_hint="Point it at a read-only role — this server can run SQL.",
        icon="snowflake",
    ),
    CatalogEntry(
        key="databricks",
        name="Databricks",
        description="Unity Catalog and Mosaic AI, over managed servers.",
        category="data",
        auth=CatalogAuth.TOKEN,
        icon="databricks",
    ),
    CatalogEntry(
        key="bigquery",
        name="Google BigQuery",
        description="Analytical queries over a warehouse.",
        category="data",
        auth=CatalogAuth.OAUTH,
        icon="bigquery",
    ),
    CatalogEntry(
        key="pagerduty",
        name="PagerDuty",
        description="Incidents, services and on-call schedules.",
        category="observability",
        auth=CatalogAuth.OAUTH,
        icon="pagerduty",
    ),
    CatalogEntry(
        key="postman",
        name="Postman",
        description="API collections and specs, as context for a coding agent.",
        category="development",
        auth=CatalogAuth.TOKEN,
        icon="postman",
    ),
    CatalogEntry(
        key="vercel",
        name="Vercel",
        description="Analyze, debug and manage projects and deployments.",
        category="development",
        auth=CatalogAuth.OAUTH,
        icon="vercel",
    ),
    CatalogEntry(
        key="netlify",
        name="Netlify",
        description="Create, deploy and manage sites.",
        category="development",
        auth=CatalogAuth.OAUTH,
        icon="netlify",
    ),
    CatalogEntry(
        key="railway",
        name="Railway",
        description="Deploy, manage and debug apps and infrastructure.",
        category="development",
        auth=CatalogAuth.TOKEN,
        icon="railway",
    ),
    CatalogEntry(
        key="replit",
        name="Replit",
        description="Turn ideas into apps and websites.",
        category="development",
        auth=CatalogAuth.OAUTH,
        icon="replit",
    ),
    CatalogEntry(
        key="huggingface",
        name="Hugging Face",
        description="The Hub, and thousands of Gradio apps.",
        category="development",
        auth=CatalogAuth.TOKEN,
        icon="huggingface",
    ),
    CatalogEntry(
        key="gitbook",
        name="GitBook",
        description="Create, edit and manage documentation.",
        category="knowledge",
        auth=CatalogAuth.TOKEN,
        icon="gitbook",
    ),
    CatalogEntry(
        key="figma",
        name="Figma",
        description="Generate diagrams and code from Figma context.",
        category="design",
        auth=CatalogAuth.OAUTH,
        icon="figma",
    ),
    CatalogEntry(
        key="webflow",
        name="Webflow",
        description="Manage CMS, pages, assets and sites.",
        category="marketing",
        auth=CatalogAuth.OAUTH,
        icon="webflow",
    ),
    CatalogEntry(
        key="wix",
        name="Wix",
        description="Manage and build sites and apps.",
        category="marketing",
        auth=CatalogAuth.OAUTH,
        icon="wix",
    ),
    CatalogEntry(
        key="wordpress",
        name="WordPress.com",
        description="Manage WordPress.com sites.",
        category="marketing",
        auth=CatalogAuth.OAUTH,
        icon="wordpress",
    ),
    CatalogEntry(
        key="semrush",
        name="Semrush",
        description="SEO, competitor research and traffic analysis.",
        category="marketing",
        auth=CatalogAuth.TOKEN,
        icon="semrush",
    ),
    CatalogEntry(
        key="similarweb",
        name="Similarweb",
        description="Web, app and market data.",
        category="marketing",
        auth=CatalogAuth.TOKEN,
        icon="similarweb",
    ),
    CatalogEntry(
        key="typeform",
        name="Typeform",
        description="Create forms and analyze responses.",
        category="productivity",
        auth=CatalogAuth.OAUTH,
        icon="typeform",
    ),
    CatalogEntry(
        key="surveymonkey",
        name="SurveyMonkey",
        description="Design surveys, collect responses, analyze results.",
        category="productivity",
        auth=CatalogAuth.OAUTH,
        icon="surveymonkey",
    ),
    CatalogEntry(
        key="deepl",
        name="DeepL",
        description="Translate text and documents.",
        category="productivity",
        auth=CatalogAuth.TOKEN,
        icon="deepl",
    ),
    CatalogEntry(
        key="elevenlabs",
        name="ElevenLabs",
        description="Create and manage voice agents.",
        category="media",
        auth=CatalogAuth.TOKEN,
        icon="elevenlabs",
    ),
    CatalogEntry(
        key="xero",
        name="Xero",
        description="Read financials from any conversation.",
        category="finance",
        auth=CatalogAuth.OAUTH,
        icon="xero",
    ),
    CatalogEntry(
        key="custom",
        name="Custom server",
        description="Any MCP server reachable by URL. Its tools are introspected on connect.",
        category="other",
        auth=CatalogAuth.TOKEN,
        token_hint="Optional. Leave blank for a server that needs no authentication.",
    ),
)

BY_KEY: dict[str, CatalogEntry] = {entry.key: entry for entry in CATALOG}


def get_entry(key: str) -> CatalogEntry | None:
    return BY_KEY.get(key)
