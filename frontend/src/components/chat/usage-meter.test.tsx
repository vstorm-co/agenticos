import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it } from "vitest";

import { UsageMeter } from "./usage-meter";
import type { ConversationWorkspace } from "@/lib/conversation-workspace-api";
import type { ConversationCost, TurnUsage } from "@/types";

function usage(overrides: Partial<TurnUsage> = {}): TurnUsage {
  return {
    input_tokens: 1200,
    output_tokens: 300,
    cost_usd: "0.0125",
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

type Sandbox = NonNullable<TurnUsage["sandbox"]>;

function stored(percent: number | null, used = 1_048_576, limit = 4_194_304): Sandbox {
  return {
    kind: "state",
    percent,
    bytes_used: used,
    bytes_limit: limit,
    memory_bytes: null,
    memory_limit_bytes: null,
  };
}

function container(percent: number | null, used: number | null, limit: number | null): Sandbox {
  return {
    kind: "service",
    percent,
    bytes_used: null,
    bytes_limit: null,
    memory_bytes: used,
    memory_limit_bytes: limit,
  };
}

const trigger = () => screen.getByRole("button", { name: /Usage of this conversation/ });

/** Renders the meter and opens it, which is where the numbers are. */
async function openMeter(props: ComponentProps<typeof UsageMeter>) {
  render(<UsageMeter {...props} />);
  await userEvent.click(trigger());
}

/** The value a reading shows, found by its label. */
function valueOf(label: string) {
  return screen.getByText(label).closest("div")?.querySelector("dd");
}

describe("UsageMeter, closed", () => {
  it("is one icon, and nothing at all before anything was measured", () => {
    // "0 tokens" under a conversation that has not run anything is a claim.
    const { container: empty } = render(<UsageMeter usage={null} />);
    expect(empty).toBeEmptyDOMElement();

    render(<UsageMeter usage={null} total={total()} />);
    expect(trigger()).toHaveTextContent("");
  });

  it("fills its disc with the context window, past half on the long arc", () => {
    // The ceiling a turn hits without warning, so the one the icon itself draws.
    const { unmount } = render(
      <UsageMeter usage={usage({ context: { used_tokens: 50_000 } })} contextWindow={200_000} />,
    );
    expect(screen.getByTestId("context-fill").getAttribute("d")).toBe(
      "M8 8 L8 1.5 A6.5 6.5 0 0 1 14.500 8.000 Z",
    );
    unmount();

    render(
      <UsageMeter usage={usage({ context: { used_tokens: 150_000 } })} contextWindow={200_000} />,
    );
    expect(screen.getByTestId("context-fill").getAttribute("d")).toBe(
      "M8 8 L8 1.5 A6.5 6.5 0 1 1 1.500 8.000 Z",
    );
  });

  it("draws a full disc, not a wrapped one, past the window", () => {
    render(
      <UsageMeter usage={usage({ context: { used_tokens: 150_000 } })} contextWindow={128_000} />,
    );

    expect(screen.getByTestId("context-fill").tagName.toLowerCase()).toBe("circle");
  });

  it("stays grey while every reading is calm", () => {
    render(
      <UsageMeter
        usage={usage({ context: { used_tokens: 10_000 }, agent_budget_percent: 40 })}
        total={total()}
        contextWindow={200_000}
      />,
    );

    expect(trigger().className).toContain("text-muted-foreground");
    expect(trigger()).toHaveAccessibleName("Usage of this conversation");
  });

  it("turns amber when any reading nears its limit, and says so", () => {
    // The readings are a click away; the warning is not allowed to be.
    render(<UsageMeter usage={usage({ agent_budget_percent: 86 })} total={total()} />);

    expect(trigger().className).toContain("text-amber-600");
    expect(trigger()).toHaveAccessibleName("Usage of this conversation - near a limit");
  });

  it("turns red at the edge, from whichever reading got there", () => {
    render(<UsageMeter usage={usage({ sandbox: stored(93) })} />);

    expect(trigger().className).toContain("text-destructive");
  });

  it("warns on the context window earlier than on a budget", () => {
    // A budget refuses with a message somebody can act on; the provider refuses
    // an overfull window mid-answer.
    render(
      <UsageMeter usage={usage({ context: { used_tokens: 152_000 } })} contextWindow={200_000} />,
    );

    expect(trigger().className).toContain("text-amber-600");
  });
});

describe("UsageMeter, open", () => {
  it("draws money, and leaves the tokens to the detail line", async () => {
    // Two counts of tokens can never agree: the input is re-sent and re-paid for
    // every turn, so a conversation whose context peaked at 3,868 has been billed
    // 7,747. One figure per unit, and nothing invites the comparison.
    await openMeter({ usage: usage(), total: total() });

    expect(screen.getByText("$0.91")).toBeInTheDocument();
    expect(screen.getByText(/40,000 in · 2,000 out billed across this conversation/)).toBeVisible();
  });

  it("marks a thread total that is only a floor", async () => {
    await openMeter({ usage: usage(), total: total({ cost_is_partial: true }) });

    expect(valueOf("This conversation")).toHaveTextContent("≥ $0.91");
    expect(screen.getByText(/a floor: some model in it had no price/)).toBeVisible();
  });

  it("prints cents from a cent upwards and keeps four decimals below one", async () => {
    // `$0.9100` is two digits nobody reads; `$0.00` under a conversation that did
    // cost something is a figure that is wrong.
    await openMeter({ usage: null, total: total({ cost_usd: "12.3456" }) });
    expect(screen.getByText("$12.35")).toBeVisible();
  });

  it("keeps four decimals for a sub-cent total", async () => {
    await openMeter({ usage: null, total: total({ cost_usd: "0.0034" }) });
    expect(screen.getByText("$0.0034")).toBeVisible();
  });

  it("prints nothing spent as cents", async () => {
    await openMeter({ usage: null, total: total({ cost_usd: "0" }) });
    expect(screen.getByText("$0.00")).toBeVisible();
  });

  it("says how full the context window is, against what", async () => {
    await openMeter({
      usage: usage({ context: { used_tokens: 150_000 } }),
      contextWindow: 200_000,
    });

    expect(valueOf("Context")).toHaveTextContent("75%");
    expect(valueOf("Context")?.className).toContain("text-amber-600");
    expect(
      screen.getByText("150,000 of 200,000 tokens in the model's context window"),
    ).toBeVisible();
  });

  it("divides by the model selected now, not by the one that produced the reading", async () => {
    // A history of 150,000 tokens is 117% of a 128K window, and the next request
    // is refused outright - so switching model has to move this before sending.
    await openMeter({
      usage: usage({ context: { used_tokens: 150_000 } }),
      contextWindow: 128_000,
    });

    expect(valueOf("Context")).toHaveTextContent("117%");
    expect(valueOf("Context")?.className).toContain("text-destructive");
  });

  it("draws no share at all when no window can be resolved", async () => {
    // A share against an assumed window is a guess presented as a measurement.
    await openMeter({
      usage: usage({ context: { used_tokens: 150_000 } }),
      total: total(),
      contextWindow: null,
    });

    expect(screen.queryByText("Context")).toBeNull();
  });

  it("keeps the digits that carry the reading when the window is barely touched", async () => {
    await openMeter({ usage: usage({ context: { used_tokens: 812 } }), contextWindow: 200_000 });
    expect(valueOf("Context")).toHaveTextContent("0.41%");
  });

  it("keeps one digit in the middle of the range", async () => {
    await openMeter({ usage: usage({ context: { used_tokens: 8_400 } }), contextWindow: 200_000 });
    expect(valueOf("Context")).toHaveTextContent("4.2%");
  });

  it("names both budgets once they are set, each against its own cap", async () => {
    await openMeter({
      usage: usage({ agent_budget_percent: 40, budget_percent: 92 }),
      total: total(),
    });

    expect(valueOf("This agent's budget")).toHaveTextContent("40% of the month");
    expect(valueOf("This agent's budget")?.className).not.toContain("text-amber-600");
    expect(valueOf("Organization budget")).toHaveTextContent("92% of the month");
    expect(valueOf("Organization budget")?.className).toContain("text-destructive");
  });

  it("says nothing about a budget nobody set", async () => {
    await openMeter({ usage: usage(), total: total() });

    expect(screen.queryByText(/budget/)).toBeNull();
  });

  it("draws a bar as well as the number, because 84% and 8% read alike in grey", async () => {
    await openMeter({ usage: usage({ sandbox: stored(84, 3_500_000) }) });

    expect(valueOf("Workspace")).toHaveTextContent("84%");
    expect(screen.getByRole("progressbar", { name: "Workspace used" })).toHaveAttribute(
      "aria-valuenow",
      "84",
    );
  });

  it("says what a stored workspace is holding, in bytes", async () => {
    await openMeter({ usage: usage({ sandbox: stored(25) }) });

    expect(screen.getByText("1.0 MiB of 4.0 MiB stored")).toBeVisible();
    expect(screen.getByRole("progressbar").firstElementChild?.className).toContain(
      "bg-foreground/40",
    );
  });

  it("colours the bar with the reading", async () => {
    await openMeter({ usage: usage({ sandbox: stored(95) }) });

    expect(screen.getByRole("progressbar").firstElementChild?.className).toContain(
      "bg-destructive",
    );
  });

  it("says what a container is using, in its own terms", async () => {
    // A stored workspace and a container are two different limits; calling both
    // "the workspace" names a limit that is not theirs (#1039).
    await openMeter({ usage: usage({ sandbox: container(85, 512, 2048) }) });

    expect(valueOf("Sandbox memory")).toHaveTextContent("85%");
    expect(screen.queryByText("Workspace")).toBeNull();
    expect(
      screen.getByText(
        "512 B of 2 KiB — the memory ceiling of this conversation's own container, " +
          "not a quota shared with anything else",
      ),
    ).toBeVisible();
    expect(screen.getByRole("progressbar").firstElementChild?.className).toContain("bg-amber-500");
  });

  it("reports a workspace nobody could measure as in use rather than as empty", async () => {
    await openMeter({ usage: usage({ sandbox: container(null, null, null) }) });

    expect(valueOf("Sandbox memory")).toHaveTextContent("in use");
    expect(screen.getByText("in use — this host did not report a number")).toBeVisible();
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("prints the amount rather than a bar drawn at zero", async () => {
    // A container with a 2 GiB ceiling holding 760 KiB is 0.036% full, which the
    // server rounds to `0` - a gauge that reads the same on every ordinary turn.
    await openMeter({ usage: usage({ sandbox: container(0, 778240, 2 * 1024 ** 3) }) });

    expect(valueOf("Sandbox memory")).toHaveTextContent("760 KiB");
    expect(screen.getByText(/760 KiB of 2\.0 GiB/)).toBeVisible();
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("keeps a zero share when there is no amount to print instead", async () => {
    await openMeter({ usage: usage({ sandbox: stored(0, 0, 4_194_304) }) });

    expect(valueOf("Workspace")).toHaveTextContent("0 B");
  });

  it("reads kilobytes and megabytes as such", async () => {
    await openMeter({ usage: usage({ sandbox: stored(1, 2048) }) });
    expect(screen.getByText("2 KiB of 4.0 MiB stored")).toBeVisible();
  });

  it("measures a stored workspace from the listing when no turn has reported one", async () => {
    // A reopened conversation has no turn to report anything - which is how the
    // fill came to appear only after somebody sent a message.
    await openMeter({ usage: usage(), workspace: workspace() });

    expect(valueOf("Workspace")).toHaveTextContent("25%");
    expect(screen.getByText("1 KiB of 4 KiB stored")).toBeVisible();
  });

  it("prefers what the turn reported, which is the only source a container has", async () => {
    await openMeter({ usage: usage({ sandbox: container(90, 90, 100) }), workspace: workspace() });

    expect(valueOf("Sandbox memory")).toHaveTextContent("90%");
  });

  it("says nothing about a container nothing has measured", async () => {
    // The listing cannot answer for one, and "in use" would claim a sandbox is
    // running when the last one may have been reaped weeks ago.
    await openMeter({
      usage: usage(),
      total: total(),
      workspace: workspace({ backend: "service" }),
    });

    expect(screen.queryByText("Workspace")).toBeNull();
  });

  it("says nothing about a workspace with no ceiling to fill", async () => {
    await openMeter({
      usage: usage(),
      total: total(),
      workspace: workspace({ bytes_limit: null }),
    });

    expect(screen.queryByText("Workspace")).toBeNull();
  });
});
