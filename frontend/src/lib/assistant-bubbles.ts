/**
 * What the AI Architect's speech bubble says, and when it stays quiet (#2063).
 *
 * One bubble at a time, chosen from what the reader is looking at and what is
 * waiting for them - approvals, an organization with nothing in it yet - with an
 * occasional "Did you know…?" on a page that has nothing of its own to say.
 * Clicking the bubble asks the assistant its prompt; × silences that page for
 * good; a switch turns the bubbles off altogether. None of it calls a model:
 * the words are the console's own until somebody clicks.
 */

import { localePrefixOf } from "@/lib/locale-routing";

/** A bubble, as a key under `assistantWidget.bubbles` holding `say` and `ask`. */
export type BubbleKey =
  | "stuck"
  | "approvals"
  | "failedRun"
  | "firstSteps"
  | "agents"
  | "agent"
  | "knowledge"
  | "runs"
  | "skills"
  | "settings"
  | "tipMcp"
  | "tipVariables"
  | "tipGroups"
  | "tipQuestions";

const TIPS: readonly BubbleKey[] = ["tipMcp", "tipVariables", "tipGroups", "tipQuestions"];

/** Page prefixes and what the bubble offers there, most specific first. */
const PAGES: readonly (readonly [RegExp, BubbleKey])[] = [
  [/^\/agents\/[^/]+/, "agent"],
  [/^\/agents\/?$/, "agents"],
  [/^\/(kb|rag)(\/|$)/, "knowledge"],
  [/^\/runs(\/|$)/, "runs"],
  [/^\/skills(\/|$)/, "skills"],
  [/^\/settings(\/|$)/, "settings"],
];

export interface BubbleSignals {
  /** A form has been open, unfinished, for a while. */
  stuck: boolean;
  /** Approvals waiting on this reader. */
  pendingApprovals: number;
  /** A run of the reader's own failed recently, and they have not asked about it. */
  failedRun: boolean;
  /** The organization has no agents yet - the first steps are the whole story. */
  noAgents: boolean;
}

/** The page a path is, without its locale prefix. */
export function pageOf(path: string): string {
  const locale = localePrefixOf(path);
  return locale ? path.slice(locale.length + 1) || "/" : path;
}

/**
 * The bubble for this page, or `null` for none.
 *
 * `visit` is a counter the caller keeps across page views; a tip shows on one
 * page view in four, so a reader is told something new now and then rather
 * than on every click.
 */
export function bubbleFor(path: string, signals: BubbleSignals, visit: number): BubbleKey | null {
  if (signals.stuck) return "stuck";
  if (signals.pendingApprovals > 0) return "approvals";
  if (signals.failedRun) return "failedRun";
  if (signals.noAgents) return "firstSteps";
  const page = pageOf(path);
  const own = PAGES.find(([pattern]) => pattern.test(page));
  if (own) return own[1];
  return visit % 4 === 0 ? TIPS[(visit / 4) % TIPS.length]! : null;
}

const STORAGE_KEY = "assistant-bubbles";

interface Preferences {
  /** Pages the reader closed the bubble on, by `pageOf` path. */
  silenced: string[];
  /** Bubbles switched off altogether. */
  off: boolean;
  /** The failed run the reader last asked about or dismissed, so it is raised once. */
  seenRun: string | null;
}

/** What this browser remembers; anything unreadable is the default. */
export function readPreferences(): Preferences {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    if (typeof parsed === "object" && parsed !== null) {
      const value = parsed as { silenced?: unknown; off?: unknown; seenRun?: unknown };
      return {
        silenced: Array.isArray(value.silenced)
          ? value.silenced.filter((page): page is string => typeof page === "string")
          : [],
        off: value.off === true,
        seenRun: typeof value.seenRun === "string" ? value.seenRun : null,
      };
    }
  } catch {
    // A private window or blocked storage: nothing remembered, nothing broken.
  }
  return { silenced: [], off: false, seenRun: null };
}

function write(preferences: Preferences): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
  } catch {
    // As above: the bubble simply comes back next time.
  }
}

/** Never show the bubble on this page again. */
export function silencePage(path: string): void {
  const preferences = readPreferences();
  const page = pageOf(path);
  if (!preferences.silenced.includes(page)) {
    write({ ...preferences, silenced: [...preferences.silenced, page] });
  }
}

/** Turn every bubble off, or back on. */
export function setBubblesOff(off: boolean): void {
  write({ ...readPreferences(), off });
}

/** Let every silenced page speak again. */
export function resetSilenced(): void {
  write({ ...readPreferences(), silenced: [] });
}

/** The reader has heard about this failed run; do not raise it again. */
export function markRunSeen(runId: string): void {
  write({ ...readPreferences(), seenRun: runId });
}

/** What waits for the reader rather than suggests something - shown on a phone too. */
export function isProactive(bubble: BubbleKey): boolean {
  return (
    bubble === "stuck" ||
    bubble === "approvals" ||
    bubble === "failedRun" ||
    bubble === "firstSteps"
  );
}
