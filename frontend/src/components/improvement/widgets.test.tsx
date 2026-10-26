import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ThumbsDown } from "lucide-react";

import { BeforeAfter, Details, Handled, Proportion, StateBadge, Stepper, Tiles } from "./widgets";

it("lays tiles out by how many there are, under the name that says them as a sentence", () => {
  const view = render(
    <Tiles
      label="Three things"
      tiles={[
        { label: "Rated down", value: 4, tone: "rose", icon: ThumbsDown },
        { label: "Failed", value: 1 },
        { label: "Test answers", value: 0, unit: "answers", caption: "Of the chosen examples" },
      ]}
    />,
  );
  const group = screen.getByRole("group", { name: "Three things" });
  expect(group).toHaveClass("sm:grid-cols-3");
  const rated = within(group).getByText("Rated down").closest("div.flex-col")!;
  expect(rated).toHaveTextContent("4");
  expect(rated.querySelector("svg")).toBeInTheDocument();
  expect(
    within(group).getByText("Failed").closest("div.flex-col")!.querySelector("svg"),
  ).toBeNull();
  expect(within(group).getByText("answers")).toBeInTheDocument();
  expect(within(group).getByText("Of the chosen examples")).toBeInTheDocument();
  view.rerender(
    <Tiles
      tiles={["a", "b", "c", "d"].map((label) => ({ label, value: 1 }))}
      label="Four things"
    />,
  );
  expect(screen.getByRole("group", { name: "Four things" })).toHaveClass("lg:grid-cols-4");
  view.rerender(<Tiles tiles={[{ label: "a", value: 1 }]} label="One" />);
  expect(screen.getByRole("group", { name: "One" }).className).not.toMatch(/cols-[34]/);
});

it.each([
  ["good", "bg-success/10", "text-success"],
  ["bad", "bg-destructive/10", "text-destructive"],
  ["warn", "bg-warning/10", "text-warning"],
  ["neutral", "bg-muted", "text-muted-foreground"],
] as const)("says a %s state with an icon as well as a colour", (tone, chip, ink) => {
  render(<StateBadge tone={tone}>Said</StateBadge>);
  const badge = screen.getByText("Said");
  expect(badge).toHaveClass(chip);
  expect(badge.querySelector("svg")).toHaveClass(ink);
});

it("draws only the parts that hold something and prints every count in the key", () => {
  const { container } = render(
    <Proportion
      label="Two from rated answers, none written"
      parts={[
        { label: "Rated", value: 2, fill: "var(--series-4)" },
        { label: "Written", value: 0, fill: "bg-success" },
        { label: "Liked", value: 1, fill: "bg-success" },
      ]}
    />,
  );
  const bar = screen.getByRole("img", { name: "Two from rated answers, none written" });
  expect(bar.children).toHaveLength(2);
  expect(bar.children[0]).toHaveStyle({ background: "var(--series-4)" });
  expect(bar.children[1]).toHaveClass("bg-success");
  expect(screen.getByText("Written").closest("li")).toHaveClass("opacity-50");
  expect(screen.getByText("Rated").closest("li")).toHaveTextContent("2");
  expect(container.querySelectorAll("li svg")).toHaveLength(0);
});

it("splits answers into handled well, not handled and not graded, each with its icon", () => {
  render(
    <Handled
      label="Before the changes: 4 of 10 handled well."
      passed={4}
      failed={5}
      undecided={1}
    />,
  );
  expect(
    screen.getByRole("img", { name: "Before the changes: 4 of 10 handled well." }),
  ).toBeInTheDocument();
  for (const [label, count] of [
    ["Handled well", "4"],
    ["Not handled well", "5"],
    ["Not graded", "1"],
  ] as const)
    expect(screen.getByText(label).closest("li")).toHaveTextContent(count);
  expect(screen.getByText("Handled well").closest("li")!.querySelector("svg")).toHaveClass(
    "text-success",
  );
});

it("shows before and after against one total, with the difference and its direction", () => {
  const view = render(
    <BeforeAfter title="All test questions" label="3 → 4 of 4" before={3} after={4} total={4} />,
  );
  const figure = screen.getByRole("figure");
  expect(within(figure).getByText("+1")).toHaveClass("text-success");
  expect(screen.getByRole("img", { name: "3 → 4 of 4" })).toHaveTextContent(
    "Before3 of 4After4 of 4",
  );
  view.rerender(<BeforeAfter title="All" label="4 → 2 of 4" before={4} after={2} total={4} />);
  expect(screen.getByText("-2")).toHaveClass("text-destructive");
  expect(screen.getByText("2 of 4").previousElementSibling!.firstElementChild).toHaveClass(
    "bg-destructive",
  );
  view.rerender(<BeforeAfter title="All" label="0 → 0 of 0" before={0} after={0} total={0} />);
  expect(screen.getByText("0")).toHaveClass("text-muted-foreground");
});

it("marks each stage with an icon and a word, and the running one as current", () => {
  render(
    <Stepper
      label="Testing the changes"
      stages={[
        { id: "a", label: "Asking", state: "done", stateLabel: "Done" },
        { id: "b", label: "Grading", state: "running", stateLabel: "Running" },
        { id: "c", label: "Re-asking", state: "pending", stateLabel: "Not started" },
      ]}
    />,
  );
  const [asking, grading, repeating] = within(
    screen.getByRole("list", { name: "Testing the changes" }),
  ).getAllByRole("listitem");
  expect(asking).toHaveTextContent("AskingDone");
  expect(asking!.querySelector("svg")).toHaveClass("text-success");
  expect(grading).toHaveAttribute("aria-current", "step");
  expect(grading!.querySelector("svg")).toHaveClass("animate-spin");
  expect(repeating).not.toHaveAttribute("aria-current");
  expect(repeating!.querySelector("svg")).toHaveClass("text-muted-foreground");
});

it("keeps details folded until opened, and says when they are", async () => {
  const onToggle = vi.fn();
  const view = render(
    <Details summary="Show details" onToggle={onToggle} tour="details">
      <p>Inside</p>
    </Details>,
  );
  const details = screen.getByText("Show details").closest("details")!;
  const summary = details.querySelector("summary")!;
  expect(summary).toHaveClass("flex", "list-none");
  expect(summary.firstElementChild).toHaveClass("lucide-chevron-right");
  expect(details).not.toHaveAttribute("open");
  expect(details).toHaveAttribute("data-tour", "details");
  await userEvent.click(screen.getByText("Show details"));
  expect(details).toHaveAttribute("open");
  details.dispatchEvent(new Event("toggle"));
  expect(onToggle).toHaveBeenCalledWith(true);
  view.rerender(
    <Details summary="Plain">
      <p>Inside</p>
    </Details>,
  );
  expect(screen.getByText("Plain").closest("details")).not.toHaveAttribute("data-tour");
});
