import { describe, expect, it } from "vitest";

import type { CapabilityGuide } from "@/hooks/use-capability-guide";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import type { CapabilityCatalogEntry, McpServerRef } from "@/types/agents";
import type { McpCatalogEntry } from "@/types/mcp";
import { CAPABILITY_PANEL_LIMIT, capabilityRows, connectedAppNames } from "./agent-capabilities";

function entry(
  overrides: Partial<CapabilityCatalogEntry> & { id: string },
): CapabilityCatalogEntry {
  return {
    name: overrides.id,
    category: "general",
    description: `${overrides.id} description`,
    side_effecting: false,
    scopes: [],
    tools: [{ id: `${overrides.id}-tool`, name: overrides.id, description: "Does it." }],
    contracts: [],
    config_schema: null,
    requires_secret: null,
    voice: "never",
    recommended: null,
    ...overrides,
  };
}

function guideFor(guides: Record<string, CapabilityGuide>) {
  return (id: string) => guides[id];
}

const KNOWLEDGE_GUIDE: CapabilityGuide = {
  name: "Knowledge",
  does: "Answers from your documents.",
  examples: ["Find the refund policy"],
  needs: "A collection.",
  never: "Never invents a source.",
};

describe("capabilityRows", () => {
  it("names the published capabilities in spec order, in plain words", () => {
    const rows = capabilityRows(
      ["knowledge", "artifacts"],
      [entry({ id: "knowledge" }), entry({ id: "artifacts" })],
      guideFor({ knowledge: KNOWLEDGE_GUIDE }),
    );
    expect(rows).toHaveLength(2);
    expect(rows[0]).toEqual({
      id: "knowledge",
      name: "Knowledge",
      does: "Answers from your documents.",
      example: "Find the refund policy",
    });
    // No guide entry yet: the registry's own words, and no example to invent.
    expect(rows[1]).toEqual({
      id: "artifacts",
      name: "artifacts",
      does: "artifacts description",
      example: null,
    });
  });

  it(`caps the panel at ${CAPABILITY_PANEL_LIMIT}`, () => {
    const ids = ["a", "b", "c", "d", "e"];
    const rows = capabilityRows(
      ids,
      ids.map((id) => entry({ id })),
      guideFor({}),
    );
    expect(rows.map((row) => row.id)).toEqual(["a", "b", "c"]);
  });

  it("skips a published id the catalog no longer names", () => {
    const rows = capabilityRows(["gone", "knowledge"], [entry({ id: "knowledge" })], guideFor({}));
    expect(rows.map((row) => row.id)).toEqual(["knowledge"]);
  });

  it("skips a capability with no tools - a guardrail, not something to ask for", () => {
    const rows = capabilityRows(
      ["guardrails", "knowledge"],
      [entry({ id: "guardrails", tools: [] }), entry({ id: "knowledge" })],
      guideFor({}),
    );
    expect(rows.map((row) => row.id)).toEqual(["knowledge"]);
  });

  it("treats a missing binding list as no capabilities", () => {
    expect(capabilityRows(null, [entry({ id: "knowledge" })], guideFor({}))).toEqual([]);
    expect(capabilityRows(undefined, [entry({ id: "knowledge" })], guideFor({}))).toEqual([]);
  });
});

function connection(overrides: Partial<McpConnectionRecord> & { id: string }): McpConnectionRecord {
  return {
    name: overrides.id,
    url: "https://example.com/mcp",
    has_auth_token: false,
    allowed_tools: null,
    is_enabled: true,
    include_instructions: false,
    auth_type: "bearer",
    oauth_authorized: false,
    authorized: true,
    last_status: null,
    last_error: null,
    last_checked_at: null,
    visibility: "org",
    catalog_key: null,
    label: null,
    is_default: false,
    last_tools: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

function catalogServer(overrides: Partial<McpCatalogEntry> & { key: string }): McpCatalogEntry {
  return {
    name: overrides.key,
    description: "A server.",
    category: "productivity",
    auth: "oauth",
    url: null,
    docs_url: null,
    token_hint: null,
    icon: null,
    reviewed: true,
    verified: false,
    check: null,
    custom: false,
    connection_ids: null,
    ...overrides,
  };
}

describe("connectedAppNames", () => {
  const refs: McpServerRef[] = [
    { account: "organization", connection_id: "gmail", allowed_tools: null, approval: "writes" },
    { account: "personal", catalog_key: "notion", allowed_tools: null, approval: "writes" },
    { account: "platform", allowed_tools: null, approval: "writes" },
  ];

  it("names the org connection and the person's own app, not the platform", () => {
    expect(
      connectedAppNames(
        refs,
        [connection({ id: "gmail", name: "Gmail" })],
        [catalogServer({ key: "notion", name: "Notion" })],
      ),
    ).toEqual(["Gmail", "Notion"]);
  });

  it("falls back to the catalog key where the catalog no longer names the app", () => {
    expect(
      connectedAppNames(
        [{ account: "personal", catalog_key: "notion", allowed_tools: null, approval: "writes" }],
        [],
        [],
      ),
    ).toEqual(["notion"]);
  });

  it("skips an org connection the caller cannot see rather than showing its id", () => {
    expect(
      connectedAppNames(
        [
          {
            account: "organization",
            connection_id: "hidden",
            allowed_tools: null,
            approval: "writes",
          },
        ],
        [],
        [],
      ),
    ).toEqual([]);
  });

  it("names each app once", () => {
    const twice: McpServerRef[] = [
      { account: "organization", connection_id: "gmail", allowed_tools: null, approval: "writes" },
      {
        account: "organization",
        connection_id: "gmail",
        allowed_tools: ["read"],
        approval: "writes",
      },
    ];
    expect(connectedAppNames(twice, [connection({ id: "gmail", name: "Gmail" })], [])).toEqual([
      "Gmail",
    ]);
  });

  it("treats missing bindings as no apps", () => {
    expect(connectedAppNames(null, [], [])).toEqual([]);
    expect(connectedAppNames(undefined, [], [])).toEqual([]);
  });
});
