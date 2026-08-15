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
    cost_is_partial: false,
    budget_percent: null,
    agent_budget_percent: null,
    sandbox: null,
    context: null,
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
  it("draws what the whole thread has cost, beside what the last turn cost", () => {
    // Two different questions. The turn answers "what did that answer cost"; the
    // thread answers "what has this conversation cost me", which is the one
    // somebody asks before they stop using it.
    render(
      <UsageStrip
        usage={usage()}
        total={{
          input_tokens: 40_000,
          output_tokens: 2_000,
          cost_usd: "0.9100",
          cost_is_partial: false,
        }}
      />,
    );

    expect(screen.getByText(/thread 42,000 tokens · \$0\.9100/)).toBeInTheDocument();
  });

  it("marks a thread total that is only a floor", () => {
    // One unpriced request makes the whole total short, and a figure that omits
    // part of the bill without saying so is worse than one that admits it.
    render(
      <UsageStrip
        usage={usage()}
        total={{
          input_tokens: 40_000,
          output_tokens: 2_000,
          cost_usd: "0.9100",
          cost_is_partial: true,
        }}
      />,
    );

    expect(screen.getByText(/thread 42,000 tokens · ≥ \$0\.9100/)).toBeInTheDocument();
  });

  it("draws how full the context window is", () => {
    // The ceiling nobody sees coming: a budget refuses with a message, a
    // workspace refuses a write, and a context window is refused by the provider
    // mid-answer.
    render(
      <UsageStrip
        usage={usage({
          context: { used_tokens: 150_000, window_tokens: 200_000, percent: 75, resolved: true },
        })}
      />,
    );

    expect(screen.getByText("context 75% full")).toBeInTheDocument();
  });

  it("marks the share as a guess when the window is not the model's own", () => {
    // A confident 73% against a number nobody could resolve is worse than an
    // uncertain one, because it is acted on.
    render(
      <UsageStrip
        usage={usage({
          context: { used_tokens: 150_000, window_tokens: 200_000, percent: 75, resolved: false },
        })}
      />,
    );

    expect(screen.getByText("context about 75% full")).toBeInTheDocument();
    expect(screen.getByTitle(/could not be resolved/)).toBeInTheDocument();
  });

  it("says a barely-touched window is under a percent, not zero", () => {
    // "0% full" reads as "nothing is there", and the distinction between an
    // exact and an assumed window stops mattering at that scale - both mean the
    // same thing. The tooltip still carries which it is.
    render(
      <UsageStrip
        usage={usage({
          context: { used_tokens: 800, window_tokens: 200_000, percent: 0, resolved: false },
        })}
      />,
    );

    expect(screen.getByText("context under 1% full")).toBeInTheDocument();
    expect(screen.getByTitle(/could not be resolved/)).toBeInTheDocument();
  });

  it("names the turn, so it is not read as the thread beside it", () => {
    // The two are the same figure on a one-turn conversation, and an unlabelled
    // number next to a labelled one reads as a duplicate rather than as the
    // other half of a comparison.
    render(
      <UsageStrip
        usage={usage()}
        total={{
          input_tokens: 40_000,
          output_tokens: 2_000,
          cost_usd: "0.9100",
          cost_is_partial: false,
        }}
      />,
    );

    expect(screen.getByText(/turn 1,500 tokens/)).toBeInTheDocument();
    expect(screen.getByText(/thread 42,000 tokens/)).toBeInTheDocument();
  });

  it("draws nothing about the context when no model request was made", () => {
    render(<UsageStrip usage={usage()} />);

    expect(screen.queryByText(/context/)).toBeNull();
  });

  it("draws no thread total for a conversation in which nothing was measured", () => {
    // Zeroes would be a claim. Null is what the server answers for a thread older
    // than the columns, or one whose every turn failed before a cost was read.
    render(<UsageStrip usage={usage()} total={null} />);

    expect(screen.queryByText(/thread/)).toBeNull();
  });

  it("marks the last turn's own cost when that is a floor too", () => {
    render(<UsageStrip usage={usage({ cost_is_partial: true })} />);

    expect(screen.getByText(/1,500 tokens · ≥ \$0\.0125/)).toBeInTheDocument();
  });

  it("says nothing before a turn has been measured, and still holds its line", () => {
    // "0 tokens" under a conversation that has not run anything is a claim, and
    // this has none to make yet. The *row* is not optional though: the strip sits
    // inside the composer, so appearing after the first answer grew the box
    // somebody had just typed in and shifted the conversation up a line. The row
    // is the same before and after; only its contents change.
    const empty = render(<UsageStrip usage={null} />);
    const emptyRow = empty.container.firstElementChild;

    expect(emptyRow?.textContent).toBe("");

    const measured = render(<UsageStrip usage={usage()} />);

    expect(measured.container.firstElementChild?.className).toBe(emptyRow?.className);
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

  it("colours the agent's share once it is close to the cap", () => {
    // The number is the warning; grey is not. A budget breach refuses the next turn
    // outright, so the last few percent have to look different from the first forty.
    render(<UsageStrip usage={usage({ agent_budget_percent: 88 })} />);

    expect(screen.getByText(/88% of this agent's month/).className).toContain("text-amber-600");
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
