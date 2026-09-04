"""Backfill `catalog_key` on MCP connections made from a catalog entry.

A binding to each person's own account finds that person's connection by
`catalog_key`, and so does the Builder when it groups the organization's
connections under a server. The column existed and the API accepted it, but no
console flow ever sent it: the personal connect form omitted it on purpose, and
both OAuth starts dropped it - so every connection ever made from the console
held `NULL`, and a personal Notion connected months ago could never be matched
to the binding that asked for it. The console sends the key now; this fills in
what it did not.

Matched on the URL the connection was created with, against the curated catalog
as it stood when this revision was written - a snapshot rather than an import,
so the migration reads the same in a year as it does today. A connection whose
URL matches no entry is somebody's own server and keeps `NULL`, which is what
`NULL` means. Only rows still holding `NULL` are touched, so a key somebody set
by hand stands.

Downgrade leaves the column as it is: the value is true whichever way the chain
runs, and nothing before this revision breaks on a key being present.

Revision ID: 0071_mcp_connection_catalog_key
Revises: 0070_mcp_registry_servers
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0071_mcp_connection_catalog_key"
down_revision: str | None = "0070_mcp_registry_servers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (catalog key, server URL) for every curated entry with a fixed URL, at the time
# of writing. Entries the client hosts themselves have no URL to match on.
CATALOG_URLS: tuple[tuple[str, str], ...] = (
    ("activepieces", "https://mcp.activepieces.com/mcp"),
    ("airtable", "https://mcp.airtable.com/mcp"),
    ("amplitude", "https://mcp.amplitude.com/mcp"),
    ("apify", "https://mcp.apify.com"),
    ("asana", "https://mcp.asana.com/sse"),
    ("atlassian", "https://mcp.atlassian.com/v1/sse"),
    ("attio", "https://mcp.attio.com/mcp"),
    ("box", "https://mcp.box.com/mcp"),
    ("brightdata", "https://mcp.brightdata.com/mcp"),
    ("buildkite", "https://mcp.buildkite.com/mcp"),
    ("calcom", "https://mcp.cal.com/mcp"),
    ("canva", "https://mcp.canva.com/mcp"),
    ("circleci", "https://mcp.circleci.com/v1/mcp"),
    ("clerk", "https://mcp.clerk.com/mcp"),
    ("clickup", "https://mcp.clickup.com/mcp"),
    ("cloudflare-docs", "https://docs.mcp.cloudflare.com/mcp"),
    ("contentful", "https://mcp.contentful.com/mcp"),
    ("datadog", "https://mcp.datadoghq.com/api/unstable/mcp-server/mcp"),
    ("deepwiki", "https://mcp.deepwiki.com/mcp"),
    ("dropbox", "https://mcp.dropbox.com/mcp"),
    ("egnyte", "https://mcp-server.egnyte.com/mcp"),
    ("exa", "https://mcp.exa.ai/mcp"),
    ("excalidraw", "https://mcp.excalidraw.com/mcp"),
    ("figma", "https://mcp.figma.com/mcp"),
    ("firecrawl", "https://mcp.firecrawl.dev/mcp"),
    ("fireflies", "https://mcp.fireflies.ai/mcp"),
    ("gitbook", "https://mcp.gitbook.com/mcp"),
    ("github", "https://api.githubcopilot.com/mcp/"),
    ("grafana", "https://mcp.grafana.com/mcp"),
    ("honeycomb", "https://mcp.honeycomb.io/mcp"),
    ("huggingface", "https://huggingface.co/mcp"),
    ("intercom", "https://mcp.intercom.com/sse"),
    ("klaviyo", "https://mcp.klaviyo.com/mcp"),
    ("langsmith", "https://api.smith.langchain.com/mcp"),
    ("linear", "https://mcp.linear.app/sse"),
    ("logfire", "https://logfire-us.pydantic.dev/mcp"),
    ("lucid", "https://mcp.lucid.app/mcp"),
    ("lusha", "https://mcp.lusha.com/mcp"),
    ("miro", "https://mcp.miro.com/mcp"),
    ("mixpanel", "https://mcp.mixpanel.com/mcp"),
    ("monday", "https://mcp.monday.com/mcp"),
    ("neon", "https://mcp.neon.tech/mcp"),
    ("netlify", "https://mcp.netlify.com/mcp"),
    ("newrelic", "https://mcp.newrelic.com/mcp"),
    ("notion", "https://mcp.notion.com/mcp"),
    ("pagerduty", "https://mcp.pagerduty.com/mcp"),
    ("paypal", "https://mcp.paypal.com/sse"),
    ("pipedream", "https://remote.mcp.pipedream.net"),
    ("pipedrive", "https://mcp.pipedrive.com/mcp"),
    ("posthog", "https://mcp.posthog.com/mcp"),
    ("postman", "https://mcp.postman.com/mcp"),
    ("qdrant", "https://mcp.qdrant.tech/mcp"),
    ("railway", "https://mcp.railway.app/mcp"),
    ("render", "https://mcp.render.com/mcp"),
    ("resend", "https://mcp.resend.com/mcp"),
    ("sanity", "https://mcp.sanity.io/mcp"),
    ("semgrep", "https://mcp.semgrep.ai/mcp"),
    ("sentry", "https://mcp.sentry.dev/mcp"),
    ("similarweb", "https://mcp.similarweb.com/mcp"),
    ("slack", "https://mcp.slack.com/mcp"),
    ("smithery", "https://mcp.smithery.ai/mcp"),
    ("statsig", "https://api.statsig.com/v1/mcp"),
    ("storyblok", "https://mcp.storyblok.com/mcp"),
    ("stripe", "https://mcp.stripe.com"),
    ("supabase", "https://mcp.supabase.com/mcp"),
    ("supermemory", "https://mcp.supermemory.ai/mcp"),
    ("surveymonkey", "https://mcp.surveymonkey.com/mcp"),
    ("tally", "https://api.tally.so/mcp"),
    ("tavily", "https://mcp.tavily.com/mcp"),
    ("vapi", "https://mcp.vapi.ai/mcp"),
    ("vercel", "https://mcp.vercel.com/"),
    ("webflow", "https://mcp.webflow.com/mcp"),
    ("wix", "https://mcp.wix.com/mcp"),
    ("workos", "https://mcp.workos.com/mcp"),
    ("xero", "https://mcp.xero.com/mcp"),
)


def upgrade() -> None:
    connections = sa.table(
        "mcp_connections",
        sa.column("catalog_key", sa.String),
        sa.column("url", sa.String),
    )
    for key, url in CATALOG_URLS:
        op.execute(
            connections.update()
            .where(connections.c.catalog_key.is_(None), connections.c.url == url)
            .values(catalog_key=key)
        )


def downgrade() -> None:
    pass
