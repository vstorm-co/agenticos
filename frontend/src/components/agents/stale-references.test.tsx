import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { StaleReferences, staleReferences } from "./stale-references";
import type { AgentSpec } from "@/types/agents";

function spec(overrides: Partial<AgentSpec> = {}): AgentSpec {
  return {
    name: "Support",
    instructions: "Be brief.",
    model_settings: {},
    capabilities: [],
    collection_ids: [],
    skill_ids: [],
    context_ids: [],
    mcp_servers: [],
    ...overrides,
  } as AgentSpec;
}

const KB = { id: "kb-1" };
const FILE = { id: "ctx-1" };
const SKILL = { id: "sk-1" };
const CONNECTION = { id: "c1" };
const NOTION = { key: "notion" };

const KNOWN = {
  collections: [KB],
  contextFiles: [FILE],
  contextTotal: 1,
  skills: [SKILL],
  skillTotal: 1,
  connections: [CONNECTION],
  catalog: [NOTION],
};

describe("staleReferences", () => {
  it("finds nothing when every reference resolves", () => {
    const whole = spec({
      collection_ids: ["kb-1"],
      context_ids: ["ctx-1"],
      skill_ids: ["sk-1"],
      mcp_servers: [
        { account: "organization", connection_id: "c1", allowed_tools: null },
        { account: "personal", catalog_key: "notion", allowed_tools: null },
      ],
    });

    expect(staleReferences(whole, KNOWN)).toEqual({
      collection_ids: [],
      context_ids: [],
      skill_ids: [],
      mcp_servers: [],
    });
  });

  it("names a deleted collection, file, skill and connection each under its kind", () => {
    const stale = spec({
      collection_ids: ["kb-1", "kb-gone"],
      context_ids: ["ctx-gone"],
      skill_ids: ["sk-gone"],
      mcp_servers: [
        { account: "organization", connection_id: "c-gone", allowed_tools: null },
        { account: "personal", catalog_key: "gone", allowed_tools: null },
      ],
    });

    expect(staleReferences(stale, KNOWN)).toEqual({
      collection_ids: ["kb-gone"],
      context_ids: ["ctx-gone"],
      skill_ids: ["sk-gone"],
      mcp_servers: stale.mcp_servers,
    });
  });

  it("declares nothing stale from one page of a longer list", () => {
    // The Builder loads a hundred context files and skills; an organization with
    // more than that has ids this page cannot see, and "not on this page" is not
    // "deleted".
    const stale = spec({ context_ids: ["ctx-unseen"], skill_ids: ["sk-unseen"] });

    expect(staleReferences(stale, { ...KNOWN, contextTotal: 150, skillTotal: 150 })).toEqual({
      collection_ids: [],
      context_ids: [],
      skill_ids: [],
      mcp_servers: [],
    });
  });
});

describe("StaleReferences", () => {
  it("renders nothing for a draft whose references all resolve", () => {
    const { container } = render(
      <StaleReferences spec={spec({ collection_ids: ["kb-1"] })} onRemove={vi.fn()} {...KNOWN} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("says what is stale and clears exactly that in one edit", async () => {
    // The refusal used to be the first anybody heard of it, and it named a uuid
    // nothing on screen explained - on an agent whose knowledge capability was
    // off, so the panel that would have listed it never opened.
    const onRemove = vi.fn();
    const draft = spec({
      collection_ids: ["kb-1", "kb-gone"],
      context_ids: ["ctx-gone", "ctx-also-gone"],
      skill_ids: ["sk-1"],
      mcp_servers: [
        { account: "organization", connection_id: "c1", allowed_tools: null },
        { account: "personal", catalog_key: "gone", allowed_tools: null },
      ],
    });
    render(<StaleReferences spec={draft} onRemove={onRemove} {...KNOWN} />);

    expect(screen.getByRole("status")).toHaveTextContent(
      "1 knowledge collection, 2 context files, and 1 MCP server",
    );
    await userEvent.click(screen.getByRole("button", { name: "Remove them" }));

    expect(onRemove).toHaveBeenCalledWith({
      collection_ids: ["kb-1"],
      context_ids: [],
      skill_ids: ["sk-1"],
      mcp_servers: [{ account: "organization", connection_id: "c1", allowed_tools: null }],
    });
  });

  it("cannot be cleared by a viewer who cannot edit", () => {
    render(
      <StaleReferences
        spec={spec({ collection_ids: ["kb-gone"] })}
        onRemove={vi.fn()}
        disabled
        {...KNOWN}
      />,
    );

    expect(screen.getByRole("button", { name: "Remove them" })).toBeDisabled();
  });
});
