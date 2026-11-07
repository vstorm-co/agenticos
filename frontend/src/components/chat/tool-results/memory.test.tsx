import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ToolCall } from "@/types";
import { memoryChangesOf } from "@/lib/turn-extras";
import { MemoryToolResult } from "./memory";

const claim = "00000000-0000-4000-8000-000000000001";
function call(result: string, name = "remember"): ToolCall {
  return {
    id: "c",
    name,
    status: "completed",
    args: { statement: "Prefers short Polish answers", profile: true },
    result,
  };
}

describe("memory in a conversation", () => {
  it("shows a confirmed claim and a link to manage memory without raw arguments", () => {
    const saved = call(`Recorded (claim ${claim}).`);
    render(<MemoryToolResult toolCall={saved} resultText={String(saved.result)} />);
    expect(screen.getByText("Prefers short Polish answers")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Your memory" })).toHaveAttribute(
      "href",
      "/settings/memory",
    );
    expect(screen.queryByText("Arguments")).toBeNull();
    expect(memoryChangesOf([saved])).toEqual([
      { callId: "c", forgot: false, label: "Prefers short Polish answers" },
    ]);
  });
  it.each([
    "Nothing was saved: no person.",
    `Kept aside as disputed (claim ${claim}).`,
    `Already recorded (claim ${claim}); nothing changed.`,
  ])("does not claim a write succeeded: %s", (result) => {
    const refused = call(result);
    render(<MemoryToolResult toolCall={refused} resultText={result} />);
    expect(screen.getByText(result)).toBeInTheDocument();
    expect(screen.queryByText("Prefers short Polish answers")).toBeNull();
    expect(memoryChangesOf([refused])).toEqual([]);
  });
  it("does not show a success chip for a failed or refused note write", () => {
    const refused = {
      ...call("A note already exists.", "write_memory"),
      args: { name: "notes.md" },
    };
    expect(memoryChangesOf([refused, { ...refused, status: "error" }])).toEqual([]);
  });
  it("shows corrections under the answer", () => {
    expect(
      memoryChangesOf([call(`Corrected (claim ${claim}); history kept.`, "correct_memory")]),
    ).toHaveLength(1);
  });
});

it.each([
  ["fact", "Facts"],
  ["preference", "Preferences"],
  ["decision", "Decisions"],
])("labels a recorded %s", (kind, label) => {
  const saved = {
    ...call(`Recorded (claim ${claim}).`),
    args: { statement: "A durable record", kind },
  };
  render(<MemoryToolResult toolCall={saved} resultText={String(saved.result)} />);
  expect(screen.getByText(label)).toBeVisible();
});

it("shows a correction with history instead of guessing the original memory type", () => {
  const corrected = call(`Corrected (claim ${claim}); history kept.`, "correct_memory");
  render(<MemoryToolResult toolCall={corrected} resultText={String(corrected.result)} />);
  expect(screen.getByText("Corrected; earlier version kept in history")).toBeVisible();
  expect(screen.queryByText("Facts")).toBeNull();
});
