import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PublishState } from "./publish-state";
import type { AgentEnvironment, AgentSpec } from "@/types/agents";

/**
 * The badges that say whether the draft on screen is a published version, and
 * which version production runs. Three rules live here:
 *
 * - It compares the *stored* draft against the version it is based on - the
 *   latest published one - so a serialization detail like key order must not
 *   read as a difference.
 * - Production held on an older version by its guards is a badge of its own.
 * - It says nothing for an agent that has never published: there is no
 *   version to differ from, and the status badge already says "draft".
 */

/** The version `useDraftBase` answers with: the latest published one. */
const answer: { base?: { id: string; version: number; spec: AgentSpec } } = {};

vi.mock("@/hooks", () => ({
  useDraftBase: () => ({ base: answer.base }),
}));

function production(overrides: Partial<AgentEnvironment> = {}): AgentEnvironment {
  return {
    id: "env-1",
    agent_id: "a-1",
    name: "production",
    version_id: "v7-id",
    version: 7,
    is_default: true,
    tracks_latest: true,
    behind_by: 0,
    logfire_token_secret_id: null,
    service_name: null,
    connections: [],
    guard_suite_ids: [],
    created_at: "2026-10-22T00:00:00Z",
    ...overrides,
  };
}

function spec(overrides: Partial<AgentSpec> = {}): AgentSpec {
  return {
    name: "Support",
    instructions: "Be helpful.",
    model_settings: {},
    capabilities: [],
    collection_ids: [],
    skill_ids: [],
    context_ids: [],
    mcp_servers: [],
    ...overrides,
  };
}

beforeEach(() => {
  answer.base = { id: "v7-id", version: 7, spec: spec() };
});

describe("the publish-state badge", () => {
  it("says the draft is up to date when it matches the published version", () => {
    render(<PublishState agentId="a-1" production={production()} draftSpec={spec()} />);

    expect(screen.getByText("Up to date with v7")).toBeInTheDocument();
  });

  it("says the draft differs from the version it is based on", () => {
    render(
      <PublishState
        agentId="a-1"
        production={production()}
        draftSpec={spec({ instructions: "Be terse." })}
      />,
    );

    const badge = screen.getByText("Draft differs from v7");
    expect(badge).toHaveAttribute(
      "title",
      "The draft is saved and differs from v7, the latest published version. Publishing makes it a new version.",
    );
  });

  it("offers to test the draft only while it differs, and only when asked to", async () => {
    const onTest = vi.fn();
    const { rerender } = render(
      <PublishState
        agentId="a-1"
        production={production()}
        draftSpec={spec({ instructions: "Be terse." })}
        onTest={onTest}
      />,
    );
    screen.getByRole("button", { name: "Test draft" }).click();
    expect(onTest).toHaveBeenCalled();

    rerender(
      <PublishState
        agentId="a-1"
        production={production()}
        draftSpec={spec({ instructions: "Be terse." })}
      />,
    );
    expect(screen.queryByRole("button", { name: "Test draft" })).toBeNull();
    rerender(
      <PublishState agentId="a-1" production={production()} draftSpec={spec()} onTest={onTest} />,
    );
    expect(screen.queryByRole("button", { name: "Test draft" })).toBeNull();
  });

  it("shows an editor who may not read runs that a test of the draft needs it", () => {
    render(
      <PublishState
        agentId="a-1"
        production={production()}
        draftSpec={spec({ instructions: "Be terse." })}
        testNeedsRunsView
      />,
    );

    const button = screen.getByRole("button", { name: /Test draft/ });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAttribute("title", "Needs permission to read runs");
  });

  it("does not read key order as a difference", () => {
    // The comparison is over sorted-keys YAML, the same serialization the diff
    // reads. `JSON.stringify` equality - what the "Unsaved" badge uses for the
    // local edit - would call these two different.
    const reordered = Object.fromEntries(Object.entries(spec()).reverse()) as unknown as AgentSpec;
    render(<PublishState agentId="a-1" production={production()} draftSpec={reordered} />);

    expect(screen.getByText("Up to date with v7")).toBeInTheDocument();
  });

  it("says which version production runs when its guards hold it back", () => {
    const { rerender } = render(
      <PublishState
        agentId="a-1"
        production={production({ version_id: "v6-id", version: 6, tracks_latest: false })}
        draftSpec={spec()}
      />,
    );
    expect(screen.getByText("Up to date with v7")).toBeInTheDocument();
    expect(screen.getByText("production on v6")).toHaveAttribute(
      "title",
      "Channels, widgets and the API answer with v6: production runs it until a newer version is promoted.",
    );

    rerender(
      <PublishState
        agentId="a-1"
        production={production({
          version_id: "v6-id",
          version: 6,
          guard_suite_ids: ["suite-1"],
          behind_by: 1,
        })}
        draftSpec={spec()}
      />,
    );
    expect(screen.getByText("production on v6 (waiting for evals)")).toBeInTheDocument();
  });

  it("says nothing of production while it runs the latest version", () => {
    render(<PublishState agentId="a-1" production={production()} draftSpec={spec()} />);
    expect(screen.queryByText(/production on/)).toBeNull();
  });

  it("says nothing for an agent that has never published", () => {
    answer.base = undefined;
    const { container } = render(
      <PublishState agentId="a-1" production={production()} draftSpec={spec()} />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
