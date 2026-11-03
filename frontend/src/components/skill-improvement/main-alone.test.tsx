import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { checkAgent, skillCheck, skillSession } from "@/test-utils/skill-improvement";
import { MainAloneChoice, MainAloneResult } from "./main-alone";

const QUOTE = {
  mode: "next_step" as const,
  number: 1,
  total_usd: "0.30",
  budget_usd: "1.00",
  affordable: true,
  candidate_hash: "h",
};

describe("MainAloneChoice", () => {
  it("prices checking main alone on its own line, and turns it off", async () => {
    const changed = vi.fn();
    const view = render(
      <MainAloneChoice
        quote={{ ...QUOTE, main_alone_usd: "0.12" } as typeof QUOTE}
        checked
        onChange={changed}
      />,
    );
    const box = screen.getByRole("checkbox", {
      name: /Also check main's newest version alone on the fork's agents \(\+\$0\.12\)/,
    });
    expect(box).toBeChecked();
    await userEvent.click(box);
    expect(changed).toHaveBeenCalledWith(false);

    view.rerender(<MainAloneChoice quote={QUOTE} checked={false} onChange={changed} />);
    expect(
      screen.getByRole("checkbox", {
        name: /^Also check main's newest version alone on the fork's agents ?Only this check/,
      }),
    ).not.toBeChecked();
  });
});

describe("MainAloneResult", () => {
  it("shows each agent on main alone beside a catch-up's result", () => {
    render(
      <MainAloneResult
        session={skillSession({
          purpose: "catch_up",
          main_alone: "checked",
          main_alone_check: skillCheck({ agents: [checkAgent("Desk", "no_change")] }),
        })}
      />,
    );
    expect(screen.getByRole("heading", { name: "Main alone" })).toBeVisible();
    expect(screen.getByText("Desk")).toBeVisible();
  });

  it("says why there is no second check, and nothing for other sessions", () => {
    const view = render(
      <MainAloneResult session={skillSession({ purpose: "catch_up", main_alone: "same" })} />,
    );
    expect(
      screen.getByText("The merge is main's newest version, so it was checked once."),
    ).toBeVisible();

    view.rerender(<MainAloneResult session={skillSession({ purpose: "to_main" })} />);
    expect(screen.queryByText("Main alone")).not.toBeInTheDocument();
    view.rerender(<MainAloneResult session={skillSession({ purpose: "catch_up" })} />);
    expect(screen.queryByText("Main alone")).not.toBeInTheDocument();
  });
});
