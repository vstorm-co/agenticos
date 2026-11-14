import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { StartExample } from "./start-example";

it("labels a recorded demonstration and does not offer a charged run", () => {
  render(<StartExample goal="document" />);
  expect(screen.getByRole("note")).toHaveTextContent("No AI was called");
  expect(screen.getByRole("textbox")).toHaveAttribute("readonly");
  expect(screen.queryByRole("button", { name: "Run this task" })).not.toBeInTheDocument();
});
it("runs only after an explicit click and sends the edited material", async () => {
  const run = vi.fn();
  render(<StartExample goal="meeting" onRun={run} />);
  expect(run).not.toHaveBeenCalled();
  const text = screen.getByRole("textbox");
  await userEvent.clear(text);
  await userEvent.type(text, "My edited fictional task");
  await userEvent.click(screen.getByRole("button", { name: "Run this task" }));
  expect(run).toHaveBeenCalledExactlyOnceWith("My edited fictional task");
});
it("does not submit an empty task", async () => {
  render(<StartExample goal="compare" onRun={vi.fn()} />);
  await userEvent.clear(screen.getByRole("textbox"));
  expect(screen.getByRole("button", { name: "Run this task" })).toBeDisabled();
});
