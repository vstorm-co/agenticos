import { afterEach, describe, expect, it, vi } from "vitest";

import {
  openAccessibilitySettings,
  parseActiveContext,
  takeContextFiles,
  withContext,
} from "./context";
import { ShellError } from "./shell";

const FOUND = {
  app: "Mail",
  window: "Refund for order 1182",
  selection: "Please refund me",
  clipboard: null,
  files: ["a.pdf"],
  accessibility: true,
};

function withShell(invoke: (command: string) => unknown) {
  window.__TAURI__ = { core: { invoke: vi.fn(invoke) }, event: { listen: vi.fn() } };
}

afterEach(() => {
  delete window.__TAURI__;
});

describe("parseActiveContext", () => {
  it("reads the shell's capture", () => {
    expect(parseActiveContext(FOUND)).toEqual(FOUND);
  });

  it("refuses a shape it does not know", () => {
    for (const value of [
      null,
      { ...FOUND, files: "a.pdf" },
      { ...FOUND, files: [1] },
      { ...FOUND, app: 3 },
      { ...FOUND, accessibility: "yes" },
    ]) {
      expect(() => parseActiveContext(value)).toThrow(ShellError);
    }
  });
});

describe("withContext", () => {
  it("quotes each passage under its heading, after the question", () => {
    expect(
      withContext("Draft a reply", [
        { heading: "Selected in Mail:", text: "line one\nline two" },
        { heading: "From the clipboard:", text: "order 1182" },
      ]),
    ).toBe(
      "Draft a reply\n\nSelected in Mail:\n> line one\n> line two\n\nFrom the clipboard:\n> order 1182",
    );
    expect(withContext("Just this", [])).toBe("Just this");
  });
});

describe("the shell's context commands", () => {
  it("takes the captured files as files, and refuses a shape it does not know", async () => {
    withShell(() => [{ name: "a.txt", data: btoa("hi") }]);
    const [file] = await takeContextFiles();
    expect(file?.name).toBe("a.txt");
    expect(await file?.text()).toBe("hi");
    withShell(() => ({}));
    await expect(takeContextFiles()).rejects.toThrow(ShellError);
    withShell(() => [{ name: "a.txt" }]);
    await expect(takeContextFiles()).rejects.toThrow(ShellError);
  });

  it("opens the privacy settings through the shell", async () => {
    const calls: string[] = [];
    withShell((command) => {
      calls.push(command);
      return null;
    });
    await openAccessibilitySettings();
    expect(calls).toEqual(["open_accessibility_settings"]);
  });
});
