import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GoesLive } from "./goes-live";

describe("GoesLive", () => {
  it("names each agent, where it goes live, and the suites guarding it", () => {
    render(
      <GoesLive
        reaches={[
          {
            id: "a-1",
            name: "Refund desk",
            environments: [
              { name: "production", guarded_by: ["Refund smoke"], guards: 1 },
              { name: "staging", guarded_by: [], guards: 0 },
            ],
          },
          {
            id: "a-2",
            name: "Clerk",
            environments: [{ name: "production", guarded_by: [], guards: 2 }],
          },
        ]}
        hidden={1}
      />,
    );

    expect(
      screen.getByText(
        "Goes live now for Refund desk (production guarded by Refund smoke and staging), Clerk (production guarded by 2 eval suites), and 1 agent you cannot see.",
      ),
    ).toBeVisible();
  });

  it("says when no published agent reads it", () => {
    render(<GoesLive reaches={[]} hidden={0} />);

    expect(
      screen.getByText("No published agent reads it yet, so applying it changes no answers today."),
    ).toBeVisible();
  });
});
