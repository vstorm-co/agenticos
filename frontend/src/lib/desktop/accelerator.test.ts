import { describe, expect, it } from "vitest";

import { acceleratorOf, describeAccelerator, keyName, type KeyPress } from "./accelerator";

const press = (code: string, mods: Partial<KeyPress> = {}): KeyPress => ({
  metaKey: false,
  ctrlKey: false,
  altKey: false,
  shiftKey: false,
  code,
  ...mods,
});

describe("acceleratorOf", () => {
  it("puts the modifiers first, in a fixed order, then the key", () => {
    expect(acceleratorOf(press("KeyA", { metaKey: true, shiftKey: true }))).toBe("Super+Shift+A");
    expect(acceleratorOf(press("Digit3", { ctrlKey: true, altKey: true }))).toBe("Ctrl+Alt+3");
    expect(acceleratorOf(press("Space", { altKey: true }))).toBe("Alt+Space");
    expect(acceleratorOf(press("F5", { altKey: true }))).toBe("Alt+F5");
  });

  it("refuses a modifier alone, a bare key and a key with no name", () => {
    expect(acceleratorOf(press("MetaLeft", { metaKey: true }))).toBeNull();
    expect(acceleratorOf(press("KeyA"))).toBeNull();
    expect(acceleratorOf(press("Semicolon", { metaKey: true }))).toBeNull();
  });
});

describe("keyName", () => {
  it("follows the grammar the shortcut plugin parses", () => {
    expect(keyName("ArrowUp")).toBe("Up");
    expect(keyName("F12")).toBe("F12");
    expect(keyName("F13")).toBeNull();
  });
});

describe("describeAccelerator", () => {
  it("shows the keyboard's glyphs on a Mac and words elsewhere", () => {
    expect(describeAccelerator("CmdOrCtrl+Shift+A", true)).toBe("⌘⇧A");
    expect(describeAccelerator("CmdOrCtrl+Shift+A", false)).toBe("Ctrl+Shift+A");
    expect(describeAccelerator("Alt+Space", true)).toBe("⌥Space");
    expect(describeAccelerator(null, true)).toBe("");
  });
});
