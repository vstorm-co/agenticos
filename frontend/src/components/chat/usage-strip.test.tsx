import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { UsageStrip } from "./usage-strip";
import type { TurnUsage } from "@/types";

function usage(overrides: Partial<TurnUsage> = {}): TurnUsage {
  return {
    input_tokens: 1200,
    output_tokens: 300,
    cost_usd: 0.0125,
    budget_percent: null,
    sandbox: null,
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

  it("names the share of the month once there is a cap to compare against", () => {
    render(<UsageStrip usage={usage({ budget_percent: 40 })} />);

    expect(screen.getByText(/40% of this month/)).toBeVisible();
  });

  it("says nothing about a budget the organization did not set", () => {
    render(<UsageStrip usage={usage()} />);

    expect(screen.queryByText(/this month/)).toBeNull();
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
});
