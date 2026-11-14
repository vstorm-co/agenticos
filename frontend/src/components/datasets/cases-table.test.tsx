import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import type { DatasetCase } from "@/types/datasets";
import { CasesTable } from "./cases-table";
const item: DatasetCase = {
  id: "r1",
  case_id: "c1",
  input: "Private question",
  reference_answer: "Private answer",
  counter_example: null,
  history: [],
  expected_tool_calls: [],
  order_mode: "any",
  checks: [],
  tags: ["private-tag"],
  note: null,
  source: "conversation",
  source_run_id: null,
  source_conversation_id: null,
  source_message_id: null,
  source_document_id: null,
  created_by_user_id: null,
  created_at: "2026-11-03T00:00:00Z",
};
it("opens cases by question and restricts delete to editors", async () => {
  const open = vi.fn();
  const remove = vi.fn();
  const { rerender } = render(<CasesTable cases={[item]} onOpen={open} />);
  await userEvent.click(screen.getByRole("button", { name: /Private question/ }));
  expect(open).toHaveBeenCalledWith(item);
  expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  rerender(<CasesTable cases={[item]} onOpen={open} onRemove={remove} />);
  await userEvent.click(screen.getByRole("button", { name: "Case actions" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
  expect(remove).toHaveBeenCalledWith(item);
  expect(open).toHaveBeenCalledTimes(1);
});
it("opens a case once from its side-panel control or Edit menu without triggering the row", async () => {
  const open = vi.fn();
  render(<CasesTable cases={[item]} onOpen={open} onRemove={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Open case" }));
  expect(open).toHaveBeenCalledExactlyOnceWith(item);
  await userEvent.click(screen.getByRole("button", { name: "Case actions" }));
  expect(open).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByRole("menuitem", { name: "Edit" }));
  expect(open).toHaveBeenCalledTimes(2);
  expect(open).toHaveBeenLastCalledWith(item);
});
it("never renders masked questions, answers or tags", () => {
  render(<CasesTable cases={[{ ...item, masked: true }]} onOpen={vi.fn()} />);
  expect(screen.queryByText(/Private question/)).toBeNull();
  expect(screen.queryByText("Private answer")).toBeNull();
  expect(screen.queryByText("private-tag")).toBeNull();
  expect(
    screen.getByRole("button", { name: /From a conversation you cannot open/ }),
  ).toBeInTheDocument();
});

it("shows readable tags and the case source in separate columns", () => {
  render(
    <CasesTable
      cases={[{ ...item, source: "manual", tags: ["qa", "hard", "returns-vs-archive"] }]}
      onOpen={vi.fn()}
    />,
  );
  expect(screen.getByText("returns-vs-archive")).toBeInTheDocument();
  expect(screen.getAllByText("Written").length).toBeGreaterThan(0);
  expect(screen.queryByText("0 checks")).toBeNull();
});
it("keeps anonymisation and available expectations clear across case types", () => {
  render(
    <CasesTable
      cases={[
        { ...item, id: "anon", anonymised_at: "2026-11-03T00:00:00Z", tags: [] },
        {
          ...item,
          id: "counter",
          reference_answer: null,
          counter_example: "A bad answer",
          checks: [{ type: "contains", value: "policy" }],
        },
        {
          ...item,
          id: "checks",
          source: "manual",
          reference_answer: null,
          checks: [{ type: "contains", value: "policy" }],
        },
      ]}
      onOpen={vi.fn()}
    />,
  );
  expect(screen.getByText("A bad answer")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Private question$/ })).toBeNull();
  expect(screen.getAllByText(/1 check/).length).toBeGreaterThan(0);
});

it("opens a case from its cells and keeps the active row keyboard-accessible", async () => {
  const onOpen = vi.fn();
  render(<CasesTable cases={[item]} onOpen={onOpen} activeCaseId={item.case_id} offset={50} />);
  expect(screen.getByText("51")).toBeInTheDocument();
  await userEvent.click(screen.getByText("Private answer"));
  expect(onOpen).toHaveBeenCalledTimes(1);
  const row = screen.getByRole("row", { selected: true });
  row.focus();
  await userEvent.keyboard("{Enter}");
  expect(onOpen).toHaveBeenCalledTimes(2);
});

it("keeps the actual columns and responsive visibility while cases load", () => {
  const { rerender } = render(<CasesTable cases={[]} loading onOpen={vi.fn()} />);
  const headerClasses = screen.getAllByRole("columnheader").map((header) => header.className);
  expect(screen.getByRole("table")).toHaveAttribute("aria-busy", "true");
  expect(screen.getAllByRole("row")).toHaveLength(7);
  rerender(<CasesTable cases={[item]} onOpen={vi.fn()} />);
  expect(screen.getAllByRole("columnheader").map((header) => header.className)).toEqual(
    headerClasses,
  );
  expect(screen.getByRole("table")).not.toHaveAttribute("aria-busy");
});
