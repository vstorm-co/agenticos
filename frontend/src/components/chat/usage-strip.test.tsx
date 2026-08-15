import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { UsageStrip } from "./usage-strip";
import type { ConversationWorkspace } from "@/lib/conversation-workspace-api";
import type { ConversationCost, TurnUsage } from "@/types";

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

function total(overrides: Partial<ConversationCost> = {}): ConversationCost {
  return {
    input_tokens: 40_000,
    output_tokens: 2_000,
    cost_usd: "0.9100",
    cost_is_partial: false,
    ...overrides,
  };
}

describe("UsageStrip", () => {
  it("draws what the whole thread has cost, and only that", () => {
    // What one *answer* cost is drawn under that answer, where it can be compared
    // with the answer beside it. Repeating it here put the same figure on screen
    // twice with nothing saying which was which - and on a one-turn conversation
    // the two are identical, which is exactly where somebody first meets this.
    render(<UsageStrip usage={usage()} total={total()} />);

    expect(screen.getByText(/42,000 tokens · \$0\.9100/)).toBeInTheDocument();
    expect(screen.queryByText(/1,500 tokens/)).toBeNull();
  });

  it("marks a thread total that is only a floor", () => {
    // One unpriced request makes the whole total short, and a figure that omits
    // part of the bill without saying so is worse than one that admits it.
    render(<UsageStrip usage={usage()} total={total({ cost_is_partial: true })} />);

    expect(screen.getByText(/42,000 tokens · ≥ \$0\.9100/)).toBeInTheDocument();
  });

  it("draws how full the context window is", () => {
    // The ceiling nobody sees coming: a budget refuses with a message, a
    // workspace refuses a write, and a context window is refused by the provider
    // mid-answer. It measures what the request *sent*, so it falls when
    // compaction works.
    render(
      <UsageStrip usage={usage({ context: { used_tokens: 150_000 } })} contextWindow={200_000} />,
    );

    expect(screen.getByText("Context 75%")).toBeInTheDocument();
    expect(
      screen.getByTitle("150,000 of 200,000 tokens in the model's context window"),
    ).toBeVisible();
  });

  it("divides by the model selected now, not by the one that produced the reading", () => {
    // The whole reason the window is not stored with the count. A history of
    // 150,000 tokens is 15% of a 1M-context model and 117% of a 128K one, and
    // the second is a request the provider refuses outright - so switching model
    // has to move this figure before the next message, not after it.
    const wide = render(
      <UsageStrip usage={usage({ context: { used_tokens: 150_000 } })} contextWindow={1_000_000} />,
    );
    expect(wide.getByText("Context 15%")).toBeInTheDocument();

    const narrow = render(
      <UsageStrip usage={usage({ context: { used_tokens: 150_000 } })} contextWindow={128_000} />,
    );
    expect(narrow.getByText("Context 117%")).toBeInTheDocument();
  });

  it("draws no share at all when no window can be resolved", () => {
    // A share against an assumed window is a guess presented as a measurement,
    // and the guess errs in the direction that lets a run reach the ceiling.
    render(
      <UsageStrip usage={usage({ context: { used_tokens: 150_000 } })} contextWindow={null} />,
    );

    expect(screen.queryByText(/Context/)).toBeNull();
  });

  it("keeps the digits that carry the reading when the window is barely touched", () => {
    // A first turn is a few hundred tokens against hundreds of thousands.
    // Rounded to a whole percent it reads `0`, which says "nothing was measured"
    // rather than "barely touched" - and the reader cannot tell the two apart.
    render(<UsageStrip usage={usage({ context: { used_tokens: 812 } })} contextWindow={200_000} />);

    expect(screen.getByText("Context 0.41%")).toBeInTheDocument();
  });

  it("drops the digits once they are noise beside the ceiling", () => {
    // A tenth of a percent means nothing at 75%, and the extra characters are
    // read every turn.
    render(
      <UsageStrip usage={usage({ context: { used_tokens: 150_400 } })} contextWindow={200_000} />,
    );

    expect(screen.getByText("Context 75%")).toBeInTheDocument();
  });

  it("keeps one digit in the middle of the range", () => {
    render(
      <UsageStrip usage={usage({ context: { used_tokens: 8_400 } })} contextWindow={200_000} />,
    );

    expect(screen.getByText("Context 4.2%")).toBeInTheDocument();
  });

  it("draws nothing about the context when no model request was made", () => {
    render(<UsageStrip usage={usage()} />);

    expect(screen.queryByText(/Context/)).toBeNull();
  });

  it("draws no thread total for a conversation in which nothing was measured", () => {
    // Zeroes would be a claim. Null is what the server answers for a thread older
    // than the columns, or one whose every turn failed before a cost was read.
    render(<UsageStrip usage={usage()} total={null} />);

    expect(screen.queryByText(/thread/)).toBeNull();
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

  it("says nothing about money for a conversation nobody measured", () => {
    // Zeroes would be a claim. Null is what the server answers for a thread older
    // than the columns, or one whose every turn failed before a cost was read.
    render(<UsageStrip usage={usage()} total={null} />);

    expect(screen.queryByText(/tokens/)).toBeNull();
  });

  it("names the agent's own share, because that is the cap an author can raise", () => {
    render(<UsageStrip usage={usage({ agent_budget_percent: 40 })} total={total()} />);

    expect(screen.getByText(/40% of this agent's month/)).toBeVisible();
  });

  it("colours the agent's share once it is close to the cap", () => {
    // The number is the warning; grey is not. A budget breach refuses the next turn
    // outright, so the last few percent have to look different from the first forty.
    render(<UsageStrip usage={usage({ agent_budget_percent: 88 })} total={total()} />);

    expect(screen.getByText(/88% of this agent's month/).className).toContain("text-amber-600");
  });

  it("keeps the organization's cap out of the way until it is close", () => {
    // It stops every agent at once and is somebody else's to change, so it is not
    // worth the space in a line this small until it matters.
    render(<UsageStrip usage={usage({ budget_percent: 40 })} total={total()} />);
    expect(screen.queryByText(/organization/)).toBeNull();

    render(<UsageStrip usage={usage({ budget_percent: 92 })} total={total()} />);
    expect(screen.getByText(/92% of the organization's/)).toBeVisible();
  });

  it("says nothing about a budget nobody set", () => {
    render(<UsageStrip usage={usage()} total={total()} />);

    expect(screen.queryByText(/month/)).toBeNull();
  });

  it("shows the thread's total on a conversation with no live turn", () => {
    // A reopened thread has no report to read a budget share off, and the total
    // is exactly what somebody opening it wants.
    render(<UsageStrip usage={null} total={total()} />);

    expect(screen.getByText(/42,000 tokens/)).toBeVisible();
  });

  it("splits input from output where somebody can look for it", () => {
    // They price differently by an order of magnitude, so one total hides whether
    // a conversation was expensive because of long contexts or long answers.
    render(
      <UsageStrip usage={usage()} total={total({ input_tokens: 1200, output_tokens: 300 })} />,
    );

    expect(screen.getByTitle(/1,200 in · 300 out across this conversation/)).toBeVisible();
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
