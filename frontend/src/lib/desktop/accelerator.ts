/**
 * Global shortcuts as the desktop app's shortcut plugin spells them
 * (`CmdOrCtrl+Shift+A`), recorded from a key press and shown as the keyboard
 * shows them. Ported from the shell's own settings page when the settings moved
 * into the console.
 */

const NAMED: Record<string, string> = {
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

/** A physical key's name in the plugin's grammar, or `null` for one it has no name for. */
export function keyName(code: string): string | null {
  if (/^Key[A-Z]$/.test(code)) return code.slice(3);
  if (/^Digit[0-9]$/.test(code)) return code.slice(5);
  if (/^F([1-9]|1[0-2])$/.test(code)) return code;
  return NAMED[code] ?? null;
}

export interface KeyPress {
  metaKey: boolean;
  ctrlKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
  code: string;
}

/**
 * A key press as an accelerator, or `null` when it is not a shortcut: a modifier
 * on its own, a key with no modifier (a global shortcut on a bare letter would
 * swallow typing in every application), or a key the grammar has no name for.
 */
export function acceleratorOf({
  metaKey,
  ctrlKey,
  altKey,
  shiftKey,
  code,
}: KeyPress): string | null {
  const key = keyName(code);
  if (!key) return null;
  const modifiers = [
    metaKey && "Super",
    ctrlKey && "Ctrl",
    altKey && "Alt",
    shiftKey && "Shift",
  ].filter((modifier): modifier is string => typeof modifier === "string");
  if (modifiers.length === 0) return null;
  return [...modifiers, key].join("+");
}

const MAC_GLYPHS: Record<string, string> = {
  Super: "⌘",
  CmdOrCtrl: "⌘",
  Ctrl: "⌃",
  Alt: "⌥",
  Shift: "⇧",
};
const PC_WORDS: Record<string, string> = {
  Super: "Win",
  CmdOrCtrl: "Ctrl",
  Ctrl: "Ctrl",
  Alt: "Alt",
  Shift: "Shift",
};

/** The accelerator as the keyboard shows it: glyphs on a Mac, words elsewhere. */
export function describeAccelerator(accelerator: string | null, mac: boolean): string {
  if (!accelerator) return "";
  const names = mac ? MAC_GLYPHS : PC_WORDS;
  return accelerator
    .split("+")
    .map((part) => names[part] ?? part)
    .join(mac ? "" : "+");
}
