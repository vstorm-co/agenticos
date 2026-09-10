/**
 * A key press as the accelerator the shell's shortcut plugin parses.
 *
 * `null` when the press is not a shortcut: a modifier on its own, a key with no
 * modifier (a global shortcut on a bare letter would swallow typing everywhere),
 * or a key the grammar has no name for.
 */

const NAMED = {
  Space: "Space",
  Enter: "Enter",
  Tab: "Tab",
  Backspace: "Backspace",
  Delete: "Delete",
  Home: "Home",
  End: "End",
  PageUp: "PageUp",
  PageDown: "PageDown",
  ArrowUp: "Up",
  ArrowDown: "Down",
  ArrowLeft: "Left",
  ArrowRight: "Right",
};

export function keyName(code) {
  if (/^Key[A-Z]$/.test(code)) return code.slice(3);
  if (/^Digit[0-9]$/.test(code)) return code.slice(5);
  if (/^F([1-9]|1[0-2])$/.test(code)) return code;
  return NAMED[code] ?? null;
}

export function acceleratorOf({ metaKey, ctrlKey, altKey, shiftKey, code }) {
  const key = keyName(code);
  if (!key) return null;
  const modifiers = [metaKey && "Super", ctrlKey && "Ctrl", altKey && "Alt", shiftKey && "Shift"].filter(Boolean);
  if (modifiers.length === 0) return null;
  return [...modifiers, key].join("+");
}

/** The accelerator as the keyboard shows it, for the field somebody reads it in. */
export function describe(accelerator, mac) {
  if (!accelerator) return "";
  const glyphs = mac
    ? { Super: "⌘", CmdOrCtrl: "⌘", Ctrl: "⌃", Alt: "⌥", Shift: "⇧" }
    : { Super: "Win", CmdOrCtrl: "Ctrl", Ctrl: "Ctrl", Alt: "Alt", Shift: "Shift" };
  return accelerator
    .split("+")
    .map((part) => glyphs[part] ?? part)
    .join(mac ? "" : "+");
}
