import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MAX_DIFF_LINES } from "@/lib/diff";

import { LineDiff } from "./line-diff";

const labels = {
  identicalLabel: "Nothing changed",
  unchangedLabel: (count: number) => `${count} unchanged`,
  tooLongLabel: "Too long",
};

describe("LineDiff", () => {
  it("says so when the texts are identical", () => {
    render(<LineDiff before={"a\nb"} after={"a\nb"} {...labels} />);

    expect(screen.getByText("Nothing changed")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("marks added and removed lines and folds a long unchanged stretch", () => {
    const keep = Array.from({ length: 12 }, (_, i) => `keep ${i}`);
    render(
      <LineDiff
        before={["old", ...keep].join("\n")}
        after={["new", ...keep].join("\n")}
        {...labels}
      />,
    );

    expect(screen.getByText("+1")).toBeTruthy();
    expect(screen.getByText("−1")).toBeTruthy();
    expect(screen.getByText("old").closest("tr")?.textContent).toContain("−");
    expect(screen.getByText("new").closest("tr")?.textContent).toContain("+");
    expect(screen.getByText("9 unchanged")).toBeTruthy();
  });

  it("refuses a text over the line limit", () => {
    const long = Array.from({ length: MAX_DIFF_LINES + 1 }, () => "x").join("\n");
    render(<LineDiff before={long} after="short" {...labels} />);

    expect(screen.getByText("Too long")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
