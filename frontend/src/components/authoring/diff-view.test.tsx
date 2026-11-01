import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { diffLine } from "@/test-utils/diff";
import { DiffView } from "./diff-view";

const wide = vi.hoisted(() => ({ value: false }));
vi.mock("@/hooks/use-wide-screen", () => ({ useWideScreen: () => wide.value }));

const lines = (count: number, prefix: string) =>
  Array.from({ length: count }, (_, index) => `${prefix} ${index + 1}`).join("\n");

beforeEach(() => {
  wide.value = false;
});

it("marks the words a long line changed, not the whole line, for every reader", () => {
  render(
    <DiffView
      before="Answer every question outright and plainly, citing the policy."
      after="Answer every question outright, briefly and plainly, citing the policy."
    />,
  );
  const added = screen.getByText("Added:").closest("tr")!;
  expect(within(added).getByText(/briefly/).tagName).toBe("INS");
  expect(screen.getByText("Removed:").closest("tr")).toHaveTextContent(
    "Answer every question outright and plainly, citing the policy.",
  );
  expect(screen.queryByRole("group", { name: "How to show the change" })).toBeNull();
});

it("folds unchanged lines around a change and opens them on request", async () => {
  render(<DiffView before={`${lines(10, "keep")}\nold`} after={`${lines(10, "keep")}\nnew`} />);
  expect(screen.queryByText(diffLine("keep 1"))).toBeNull();
  expect(screen.getByText(diffLine("keep 8"))).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Show 7 unchanged lines" }));
  expect(screen.getByText(diffLine("keep 1"))).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /unchanged line/ })).toBeNull();
});

it("shows the surroundings of a passage as rows of their own, and an unchanged text whole", () => {
  const { rerender } = render(
    <DiffView context="## Refunds" before="Old." after="New." trailing={"Then stop.\n"} />,
  );
  expect(screen.getByText(diffLine("## Refunds")).closest("tr")).not.toBe(
    screen.getByText(diffLine("Old.")).closest("tr"),
  );
  expect(screen.getByText(diffLine("Then stop."))).toBeInTheDocument();
  rerender(<DiffView before={lines(9, "same")} after={lines(9, "same")} />);
  expect(screen.getByText(diffLine("same 1"))).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /unchanged/ })).toBeNull();
  rerender(<DiffView before="" after="" emptyLabel="No text" />);
  expect(screen.getByText("No text")).toBeInTheDocument();
});

it("puts the two versions side by side on a wide screen, and back", async () => {
  wide.value = true;
  render(
    <DiffView
      before={`${lines(8, "keep")}\none\ntwo`}
      after={`${lines(8, "keep")}\nONE\nadded line\nmore`}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Side by side" }));
  expect(screen.getByRole("button", { name: "Side by side" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  const row = screen.getByText(diffLine("one")).closest("tr")!;
  expect(within(row).getByText(diffLine("ONE"))).toBeInTheDocument();
  expect(screen.getByText(diffLine("more")).closest("tr")).toHaveTextContent("Added:more");
  const kept = screen.getAllByText(diffLine("keep 8"));
  expect(kept).toHaveLength(2);
  expect(kept[0]!.closest("tr")!.querySelectorAll("td")).toHaveLength(4);
  await userEvent.click(screen.getByRole("button", { name: "Show 5 unchanged lines" }));
  expect(screen.getAllByText(diffLine("keep 1"))).toHaveLength(2);
  await userEvent.click(screen.getByRole("button", { name: "Unified" }));
  expect(screen.getByText(diffLine("one")).closest("tr")).not.toBe(
    screen.getByText(diffLine("ONE")).closest("tr"),
  );
});

it("marks a removed line with nothing to pair whole", () => {
  render(<DiffView before={"first\nsecond"} after="first edited" />);
  expect(screen.getByText(diffLine("second")).querySelector("del")).toBeNull();
  expect(screen.getByText(diffLine("first edited")).querySelector("ins")).not.toBeNull();
});
