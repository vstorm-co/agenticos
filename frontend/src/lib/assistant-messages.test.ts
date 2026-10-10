import { describe, expect, it } from "vitest";

import {
  ASK,
  ATTACH,
  CONTEXT,
  HISTORY,
  NAVIGATE,
  NEW,
  readFromFrame,
  readToFrame,
} from "./assistant-messages";

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

describe("an attachment for the frame", () => {
  it("is read only when it carries a file", () => {
    const file = new File(["png"], "shot.png", { type: "image/png" });

    expect(readToFrame(from({ type: ATTACH, file }), ORIGIN)).toEqual({ type: ATTACH, file });
    expect(readToFrame(from({ type: ATTACH, file: "shot.png" }), ORIGIN)).toBeNull();
  });
});

describe("readFromFrame", () => {
  const frame = {} as Window;
  const fromFrame = (data: unknown, source: unknown = frame, origin = ORIGIN) =>
    new MessageEvent("message", { data, origin, source: source as Window });

  it("reads a link the frame wants opened", () => {
    expect(readFromFrame(fromFrame({ type: NAVIGATE, href: "/agents" }), ORIGIN, frame)).toEqual({
      type: NAVIGATE,
      href: "/agents",
    });
  });

  it("ignores anything not from its own frame, of this origin, in a known shape", () => {
    const link = { type: NAVIGATE, href: "/agents" };
    expect(readFromFrame(fromFrame(link, {}), ORIGIN, frame)).toBeNull();
    expect(readFromFrame(fromFrame(link), ORIGIN, null)).toBeNull();
    expect(readFromFrame(fromFrame(link, frame, "https://evil.example"), ORIGIN, frame)).toBeNull();
    expect(readFromFrame(fromFrame("hi"), ORIGIN, frame)).toBeNull();
    expect(readFromFrame(fromFrame({ type: NAVIGATE }), ORIGIN, frame)).toBeNull();
    expect(readFromFrame(fromFrame({ type: ASK, text: "x" }), ORIGIN, frame)).toBeNull();
  });
});
