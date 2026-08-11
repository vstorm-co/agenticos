import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PublishState } from "./publish-state";
import type { AgentSpec } from "@/types/agents";

/**
 * The badge that says whether the agent people are talking to is the one on
 * screen - the state #519 found drawn identically to "published and up to
 * date". Two rules live here:
 *
 * - It compares the *stored* draft against the frozen version spec, so a
 *   serialization detail like key order must not read as a difference.
 * - It says nothing for an agent that has never published: there is no
 *   version to differ from, and the status badge already says "draft".
 */

/** What `useAgentVersion` answers when asked for a version at all. */
const answer: { version?: { version: number; spec: AgentSpec } } = {};

vi.mock("@/hooks", () => ({
  useAgentVersion: (_agentId: string | null, versionId: string | null) => ({
    version: versionId ? answer.version : undefined,
    isLoading: false,
  }),
}));

function spec(overrides: Partial<AgentSpec> = {}): AgentSpec {
  return {
    name: "Support",
    instructions: "Be helpful.",
    model_settings: {},
    capabilities: [],
    collection_ids: [],
    skill_ids: [],
    mcp_server_ids: [],
    ...overrides,
  };
}

beforeEach(() => {
  answer.version = { version: 7, spec: spec() };
});

describe("the publish-state badge", () => {
  it("says the draft is up to date when it matches the published version", () => {
    render(<PublishState agentId="a-1" currentVersionId="v7-id" draftSpec={spec()} />);

    expect(screen.getByText("Up to date with v7")).toBeInTheDocument();
  });

  it("says the draft differs, and that v7 keeps answering until a publish", () => {
    render(
      <PublishState
        agentId="a-1"
        currentVersionId="v7-id"
        draftSpec={spec({ instructions: "Be terse." })}
      />,
    );

    const badge = screen.getByText("Draft differs from v7");
    expect(badge).toHaveAttribute(
      "title",
      "The draft is saved. Everything published - channels, widgets, the API - keeps answering with v7 until you publish.",
    );
  });

  it("does not read key order as a difference", () => {
    // The comparison is over sorted-keys YAML, the same serialization the diff
    // reads. `JSON.stringify` equality - what the "Unsaved" badge uses for the
    // local edit - would call these two different.
    const reordered = Object.fromEntries(Object.entries(spec()).reverse()) as unknown as AgentSpec;
    render(<PublishState agentId="a-1" currentVersionId="v7-id" draftSpec={reordered} />);

    expect(screen.getByText("Up to date with v7")).toBeInTheDocument();
  });

  it("says nothing for an agent that has never published", () => {
    const { container } = render(
      <PublishState agentId="a-1" currentVersionId={null} draftSpec={spec()} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("says nothing until the published version has arrived", () => {
    answer.version = undefined;
    const { container } = render(
      <PublishState agentId="a-1" currentVersionId="v7-id" draftSpec={spec()} />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
