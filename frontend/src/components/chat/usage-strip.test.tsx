import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { UsageStrip } from "./usage-strip";
import type { ConversationWorkspace } from "@/lib/conversation-workspace-api";
import type { TurnUsage } from "@/types";

function usage(overrides: Partial<TurnUsage> = {}): TurnUsage {
  return {
    input_tokens: 1200,
    output_tokens: 300,
    cost_usd: 0.0125,
    budget_percent: null,
    agent_budget_percent: null,
    sandbox: null,
    ...overrides,
  };
}

function workspace(overrides: Partial<ConversationWorkspace> = {}): ConversationWorkspace {
  return {
    scope: "conversation",
    backend: "state",
    owner_label: "This conversation",
    items: [],
    total: 0,
    bytes_total: 1024,
    bytes_limit: 4096,
    unreadable_reason: null,
    ...overrides,
  };
}

describe("UsageStrip", () => {
  it("says nothing before a turn has been measured", () => {
    // "0 tokens" under a conversation that has not run anything is a claim, and
    // this has none to make yet.
    const { container } = render(<UsageStrip usage={null} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("reports the tokens and the cost of the last turn", () => {
    render(<UsageStrip usage={usage()} />);

    expect(screen.getByText(/1,500 tokens/)).toBeVisible();
    expect(screen.getByText(/\$0\.0125/)).toBeVisible();
  });

  it("names the agent's own share, because that is the cap an author can raise", () => {
    render(<UsageStrip usage={usage({ agent_budget_percent: 40 })} />);

    expect(screen.getByText(/40% of this agent's month/)).toBeVisible();
  });

  it("keeps the organization's cap out of the way until it is close", () => {
    // It stops every agent at once and is somebody else's to change, so it is not
    // worth the space in a line this small until it matters.
    render(<UsageStrip usage={usage({ budget_percent: 40 })} />);
    expect(screen.queryByText(/organization/)).toBeNull();

    render(<UsageStrip usage={usage({ budget_percent: 92 })} />);
    expect(screen.getByText(/92% of the organization's/)).toBeVisible();
  });

  it("says nothing about a budget nobody set", () => {
    render(<UsageStrip usage={usage()} />);

    expect(screen.queryByText(/month/)).toBeNull();
  });

  it("splits input from output where somebody can look for it", () => {
    // They price differently by an order of magnitude, so one total hides whether
    // a turn was expensive because of a long context or a long answer.
    render(<UsageStrip usage={usage({ input_tokens: 1200, output_tokens: 300 })} />);

    expect(screen.getByTitle("1,200 in · 300 out")).toBeVisible();
  });

  it("draws a bar as well as the number, because 84% and 8% read alike in grey", () => {
    render(
      <UsageStrip
        usage={usage({
          sandbox: {
            kind: "state",
            percent: 84,
            bytes_used: 3_500_000,
            bytes_limit: 4_194_304,
            memory_bytes: null,
            memory_limit_bytes: null,
          },
        })}
      />,
    );

    expect(screen.getByText(/workspace 84% full/)).toBeVisible();
    expect(screen.getByRole("progressbar", { name: "Workspace used" })).toHaveAttribute(
      "aria-valuenow",
      "84",
    );
  });

  it("says what a stored workspace is holding, in bytes", () => {
    render(
      <UsageStrip
        usage={usage({
          sandbox: {
            kind: "state",
            percent: 25,
            bytes_used: 1_048_576,
            bytes_limit: 4_194_304,
            memory_bytes: null,
            memory_limit_bytes: null,
          },
        })}
      />,
    );

    expect(screen.getByTitle("1.0 MiB of 4.0 MiB stored")).toBeVisible();
  });

  it("says what a container is using, in its own terms", () => {
    // A stored workspace and a container are two different limits; calling both
    // "the workspace" would tell somebody they are near a limit that is not theirs.
    render(
      <UsageStrip
        usage={usage({
          sandbox: {
            kind: "service",
            percent: 25,
            bytes_used: null,
            bytes_limit: null,
            memory_bytes: 512,
            memory_limit_bytes: 2048,
          },
        })}
      />,
    );

    expect(screen.getByTitle("512 B of 2 KiB in the container")).toBeVisible();
  });

  it("reports a workspace nobody could measure as in use rather than as empty", () => {
    render(
      <UsageStrip
        usage={usage({
          sandbox: {
            kind: "service",
            percent: null,
            bytes_used: null,
            bytes_limit: null,
            memory_bytes: null,
            memory_limit_bytes: null,
          },
        })}
      />,
    );

    expect(screen.getByText("workspace in use")).toBeVisible();
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("says nothing about a workspace for an agent that keeps no files", () => {
    render(<UsageStrip usage={usage()} />);

    expect(screen.queryByText(/workspace/)).toBeNull();
  });

  it("reads kilobytes as kilobytes", () => {
    render(
      <UsageStrip
        usage={usage({
          sandbox: {
            kind: "state",
            percent: 1,
            bytes_used: 2048,
            bytes_limit: 4_194_304,
            memory_bytes: null,
            memory_limit_bytes: null,
          },
        })}
      />,
    );

    expect(screen.getByTitle("2 KiB of 4.0 MiB stored")).toBeVisible();
  });

  /**
   * The fill on a conversation nobody has sent to yet.
   *
   * Two sources for one line, because they measure at different times: a live turn
   * reports the workspace it used, and a *reopened* conversation has no turn to report
   * anything - which is how "workspace 0% full" came to appear only after somebody sent
   * a message, the one moment it is least useful.
   */
  it("measures a stored workspace from the listing when no turn has reported one", () => {
    render(<UsageStrip usage={usage()} workspace={workspace()} />);

    expect(screen.getByText("workspace 25% full")).toBeVisible();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "25");
  });

  it("prefers what the turn reported, which is the only source a container has", () => {
    render(
      <UsageStrip
        usage={usage({
          sandbox: {
            kind: "service",
            // The percentage is the server's arithmetic, not the client's: a container
            // is memory against a ceiling its host set, and a stored workspace is bytes
            // against ours.
            percent: 90,
            bytes_used: null,
            bytes_limit: null,
            memory_bytes: 90,
            memory_limit_bytes: 100,
          },
        })}
        workspace={workspace()}
      />,
    );

    expect(screen.getByText("workspace 90% full")).toBeVisible();
  });

  it("says nothing about a container nothing has measured", () => {
    // The listing cannot answer for one, and "in use" would claim a sandbox is running
    // when the last one may have been reaped weeks ago.
    render(<UsageStrip usage={usage()} workspace={workspace({ backend: "service" })} />);

    expect(screen.queryByText(/workspace/)).toBeNull();
  });

  it("says nothing about a workspace with no ceiling to fill", () => {
    render(<UsageStrip usage={usage()} workspace={workspace({ bytes_limit: null })} />);

    expect(screen.queryByText(/workspace/)).toBeNull();
  });
});
