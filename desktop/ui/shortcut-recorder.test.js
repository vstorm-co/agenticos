import { expect, test } from "bun:test";

import { acceleratorOf, describe, keyName } from "./shortcut-recorder.js";

const press = (code, mods = {}) => ({ metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, code, ...mods });

test("modifiers come first, in a fixed order, then the key", () => {
  expect(acceleratorOf(press("KeyA", { metaKey: true, shiftKey: true }))).toBe("Super+Shift+A");
  expect(acceleratorOf(press("Digit3", { ctrlKey: true, altKey: true }))).toBe("Ctrl+Alt+3");
  expect(acceleratorOf(press("Space", { metaKey: true }))).toBe("Super+Space");
  expect(acceleratorOf(press("F5", { altKey: true }))).toBe("Alt+F5");
});

test("a modifier alone, a bare key or an unnamed key is not a shortcut", () => {
  expect(acceleratorOf(press("MetaLeft", { metaKey: true }))).toBeNull();
  expect(acceleratorOf(press("KeyA"))).toBeNull();
  expect(acceleratorOf(press("Semicolon", { metaKey: true }))).toBeNull();
});

test("key names follow the grammar the plugin parses", () => {
  expect(keyName("ArrowUp")).toBe("Up");
  expect(keyName("F12")).toBe("F12");
  expect(keyName("F13")).toBeNull();
});

test("the field shows the keyboard's glyphs on a Mac and words elsewhere", () => {
  expect(describe("CmdOrCtrl+Shift+A", true)).toBe("⌘⇧A");
  expect(describe("CmdOrCtrl+Shift+A", false)).toBe("Ctrl+Shift+A");
  expect(describe(null, true)).toBe("");
});
