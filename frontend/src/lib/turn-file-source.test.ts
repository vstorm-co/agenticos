import { expect, it } from "vitest";
import { turnFileSourceFromEvent } from "./turn-file-source";
it("accepts only recorded source shapes", () => {
  expect(turnFileSourceFromEvent({ file_source: { kind: "local", id: "old-source" } })).toEqual({
    kind: "local",
    id: "old-source",
  });
  expect(turnFileSourceFromEvent({ file_source: { kind: "conversation", id: "chat" } })).toEqual({
    kind: "conversation",
    id: "chat",
  });
  for (const value of [
    null,
    "bad",
    {},
    { file_source: null },
    { file_source: {} },
    { file_source: { kind: "other" } },
    { file_source: { kind: "local", id: "" } },
    { file_source: { kind: "local", id: 7 } },
    { file_source: { kind: "conversation", id: 7 } },
    { file_source: { kind: "conversation", id: "" } },
  ])
    expect(turnFileSourceFromEvent(value)).toBeUndefined();
});
