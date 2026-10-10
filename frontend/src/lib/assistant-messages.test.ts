import { describe, expect, it } from "vitest";

import { ASK, CONTEXT, HISTORY, NEW, readToFrame } from "./assistant-messages";

const ORIGIN = "https://console.example";
const from = (data: unknown, origin = ORIGIN) => new MessageEvent("message", { data, origin });

describe("readToFrame", () => {
  it("reads each kind of message from this origin", () => {
    expect(readToFrame(from({ type: ASK, text: "hi" }), ORIGIN)).toEqual({ type: ASK, text: "hi" });
    expect(readToFrame(from({ type: CONTEXT, path: "/kb", title: "Knowledge" }), ORIGIN)).toEqual({
      type: CONTEXT,
      path: "/kb",
      title: "Knowledge",
    });
    expect(readToFrame(from({ type: NEW }), ORIGIN)).toEqual({ type: NEW });
    expect(readToFrame(from({ type: HISTORY }), ORIGIN)).toEqual({ type: HISTORY });
  });

  it("ignores another origin, a malformed message and an unknown kind", () => {
    expect(readToFrame(from({ type: ASK, text: "hi" }, "https://evil.example"), ORIGIN)).toBeNull();
    expect(readToFrame(from("hello"), ORIGIN)).toBeNull();
    expect(readToFrame(from(null), ORIGIN)).toBeNull();
    expect(readToFrame(from({ type: ASK }), ORIGIN)).toBeNull();
    expect(readToFrame(from({ type: CONTEXT, path: "/kb" }), ORIGIN)).toBeNull();
    expect(readToFrame(from({ type: "agenticos:assistant:delete-everything" }), ORIGIN)).toBeNull();
  });
});
