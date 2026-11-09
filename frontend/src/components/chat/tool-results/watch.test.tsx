import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ToolCall } from "@/types";
import { WatchResult, writtenWatches } from "./watch";

const id = "00000000-0000-4000-8000-000000000001";
const connection = "00000000-0000-4000-8000-000000000002";
const saved = { id, connection_id: connection };
function call(overrides: Partial<ToolCall> = {}): ToolCall {
  return {
    id: "call",
    name: "agenticos_create_watch",
    args: {},
    status: "completed",
    result: saved,
    ...overrides,
  };
}
describe("watch references", () => {
  it("deduplicates successful platform writes", () => {
    expect(
      writtenWatches([
        call(),
        call({ name: "agenticos_update_watch", result: JSON.stringify(saved) }),
      ]),
    ).toEqual([id]);
  });
  it.each([
    { name: "other_create_watch" },
    { status: "error" as const },
    { result: "Forbidden" },
    { result: null },
    { result: "[]" },
    { result: { id: "invalid", connection_id: connection } },
    { result: { id, connection_id: "invalid" } },
    { result: { id } },
  ])("ignores a refusal, malformed data or untrusted tool: %j", (change) => {
    expect(writtenWatches([call(change)])).toEqual([]);
  });
});

vi.mock("@/components/watches/watches-card", () => ({
  WatchesCard: ({ watchId }: { watchId: string }) => <p>{watchId}</p>,
}));
it("renders a watch through its authorized management card", () => {
  render(<WatchResult watchId={id} />);
  expect(screen.getByText(id)).toBeVisible();
});

it("keeps trusted platform cards and refuses a generic external watch", () => {
  expect(writtenWatches([call({ presentation_kind: "platform" })])).toEqual([id]);
  expect(writtenWatches([call({ presentation_kind: "generic" })])).toEqual([]);
});
