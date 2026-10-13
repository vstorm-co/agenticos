import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DatasetCase } from "@/types/datasets";
import { CaseRow } from "./case-row";

const CASE: DatasetCase = {
  id: "r1",
  case_id: "c1",
  input: "How long is the return window?",
  history: [{ role: "user", content: "hi" }],
  reference_answer: "30 days",
  counter_example: "90 days",
  expected_tool_calls: [{ tool: "search", args: {} }],
  order_mode: "any",
  checks: [],
  tags: ["returns"],
  note: null,
  source: "conversation",
  source_run_id: "run",
  source_conversation_id: null,
  source_message_id: null,
  source_document_id: null,
  created_by_user_id: null,
  created_at: "2026-10-13T00:00:00Z",
};

describe("CaseRow", () => {
  it("says where a case came from and what it carries", async () => {
    const onOpen = vi.fn();
    render(<CaseRow item={CASE} onOpen={onOpen} />);
    for (const text of [
      "From a conversation",
      "1 earlier turn",
      "Reference answer",
      "Counter-example",
      "1 expected call",
      "returns",
    ]) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    await userEvent.click(screen.getByText(CASE.input));
    expect(onOpen).toHaveBeenCalled();
  });

  it("offers removal only when it is given one, and a bare case shows no badges it lacks", async () => {
    const onRemove = vi.fn();
    render(
      <CaseRow
        item={{
          ...CASE,
          history: [],
          reference_answer: null,
          counter_example: null,
          expected_tool_calls: [],
          tags: [],
          source: "manual",
        }}
        onOpen={vi.fn()}
        onRemove={onRemove}
      />,
    );
    expect(screen.queryByText("Reference answer")).toBeNull();
    expect(screen.queryByText(/earlier turn/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onRemove).toHaveBeenCalled();
  });
});
