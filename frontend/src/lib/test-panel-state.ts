/**
 * What the Builder's test panel remembers per agent (#2074): whether it is open,
 * its width, what answers, what it is compared with and the pinned prompts.
 *
 * A per-viewer convenience, so browser storage - and read defensively: a private
 * window or blocked site data throws, and the panel then starts from defaults.
 */

/** Set on `<html>` while the test panel is open; the Architect's corner widget steps aside. */
export const TEST_PANEL_OPEN = "data-test-panel";

export interface TestPanelState {
  open: boolean;
  width: number;
  /** `draft`, or the id of the environment whose version answers. */
  mode: string;
  /** What answers beside it, in the same terms, or `null` when not comparing. */
  compare: string | null;
  pinned: string[];
}

const DEFAULTS: TestPanelState = {
  open: false,
  width: 440,
  mode: "draft",
  compare: null,
  pinned: [],
};

const key = (agentId: string) => `agenticos:test-panel:${agentId}`;

export function readTestPanel(agentId: string): TestPanelState {
  try {
    const raw = window.localStorage.getItem(key(agentId));
    if (!raw) return DEFAULTS;
    const stored = JSON.parse(raw) as Partial<TestPanelState>;
    return {
      open: stored.open === true,
      width: typeof stored.width === "number" ? stored.width : DEFAULTS.width,
      mode: typeof stored.mode === "string" ? stored.mode : DEFAULTS.mode,
      compare: typeof stored.compare === "string" ? stored.compare : null,
      pinned: Array.isArray(stored.pinned)
        ? stored.pinned.filter((entry): entry is string => typeof entry === "string")
        : [],
    };
  } catch {
    return DEFAULTS;
  }
}

/**
 * Whether the address asks for the test panel - `?test=open`, the link the AI
 * Architect gives to try an agent it drafted (#2074). Read once, on arrival.
 */
export function askedToTest(): boolean {
  try {
    return new URLSearchParams(window.location.search).get("test") === "open";
  } catch {
    return false;
  }
}

export function writeTestPanel(agentId: string, state: TestPanelState): void {
  try {
    window.localStorage.setItem(key(agentId), JSON.stringify(state));
  } catch {
    // Nothing to keep it in; the panel works for this visit all the same.
  }
}
