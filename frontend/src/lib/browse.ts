import type { BrowseOutcome, BrowserFrame } from "@/types/chat";

/**
 * One step the browser took, as the panel lists it.
 *
 * `reason` is what makes a step worth reading rather than a log line: the model
 * says what each action is for, so a person watching can tell a browse heading
 * the wrong way from one taking the long way round.
 */
export interface BrowseStep {
  step: number;
  operation: string;
  target: string | null;
  reason: string | null;
  url: string | null;
}

/**
 * The tools that drive a desktop rather than a browser. Each run that uses one
 * draws the desktop in a window named after its first call - a screenshot, or
 * an action approved in a run of its own - so any of them can carry a window.
 */
export const DESKTOP_TOOLS: ReadonlySet<string> = new Set(["computer_screenshot", "computer_act"]);

/** One `browse_web` call, assembled from its frames. */
export interface Browse {
  callId: string;
  /** The run it belongs to, which addresses its live view; null before it is known. */
  runId?: string | null;
  /**
   * What the browser asked a person to do, while it waits for one (#2128) -
   * cleared once somebody takes it over.
   */
  needs?: string | null;
  /** Who holds the browser right now, while a person does - their name, for showing. */
  heldBy?: string | null;
  /** The same person by id: names are not unique, so this is what says it is you. */
  heldById?: string | null;
  goal: string;
  maxSteps: number | null;
  url: string | null;
  title: string | null;
  steps: BrowseStep[];
  /**
   * The most recent viewport, and nothing older.
   *
   * One image, not a film strip. A browse sends one JPEG per step and a long one
   * would hold thirty of them in memory for a panel that shows the newest -
   * which is the whole of what a live preview is.
   */
  image: string | null;
  /**
   * Which step `image` belongs to.
   *
   * Frames share a socket with the turn's text and a picture can arrive after the
   * step that followed it. Without this the panel would draw the previous page
   * under the current caption - worse than drawing nothing, because it looks
   * right.
   */
  imageStep: number;
  outcome: BrowseOutcome | null;
  detail: string | null;
  /** The site a person kept their sign-in to when they handed the browser back (#2129). */
  kept?: string | null;
  /**
   * Where the agent is about to press, as fractions of the viewport - the
   * cursor a person watches move across the page - and the step it belongs to,
   * so each press draws its own click. Absent until the agent points at
   * something, and cleared while a person holds the browser or once it is over.
   */
  pointer?: { x: number; y: number; step: number } | null;
}

function opened(frame: BrowserFrame): Browse {
  return {
    runId: frame.run_id ?? null,
    needs: null,
    heldBy: null,
    heldById: null,
    callId: frame.call_id,
    goal: frame.goal ?? "",
    maxSteps: frame.max_steps ?? null,
    url: frame.url ?? null,
    title: frame.title ?? null,
    steps: [],
    image: null,
    imageStep: -1,
    outcome: null,
    detail: null,
  };
}

function applyTo(browse: Browse, frame: BrowserFrame): Browse {
  switch (frame.kind) {
    case "browser_opened":
      return { ...browse, ...opened(frame), steps: browse.steps };
    case "browser_frame":
      // Older than what is on screen: a picture that overtook its own step.
      if (frame.step < browse.imageStep) return browse;
      return {
        ...browse,
        image: frame.image ?? browse.image,
        imageStep: frame.step,
        url: frame.url ?? browse.url,
        title: frame.title ?? browse.title,
      };
    case "browser_step": {
      const step: BrowseStep = {
        step: frame.step,
        operation: frame.operation ?? "",
        target: frame.target ?? null,
        reason: frame.reason ?? null,
        url: frame.url ?? null,
      };
      // Replaced rather than appended when the step number repeats: a resumed or
      // re-sent frame must not put the same step in the list twice.
      const steps = browse.steps.filter((existing) => existing.step !== frame.step);
      return {
        ...browse,
        steps: [...steps, step].sort((a, b) => a.step - b.step),
        url: frame.url ?? browse.url,
        title: frame.title ?? browse.title,
      };
    }
    case "browser_needs_person":
      return { ...browse, needs: frame.detail ?? null };
    case "browser_pointer":
      return { ...browse, pointer: { x: frame.x ?? 0, y: frame.y ?? 0, step: frame.step } };
    case "browser_held":
      return {
        ...browse,
        needs: null,
        heldBy: frame.by ?? null,
        heldById: frame.by_user_id ?? null,
        pointer: null,
      };
    case "browser_released":
      // A give-back that kept the sign-in says which site (#2129).
      return {
        ...browse,
        heldBy: null,
        heldById: null,
        kept: frame.detail ?? browse.kept ?? null,
      };
    case "browser_finished":
      return {
        ...browse,
        needs: null,
        heldBy: null,
        heldById: null,
        pointer: null,
        outcome: frame.outcome ?? null,
        detail: frame.detail ?? null,
        url: frame.url ?? browse.url,
        title: frame.title ?? browse.title,
      };
  }
}

/**
 * Fold one frame into the browses on screen.
 *
 * Keyed on `call_id`, not on the run: one turn can browse twice, and a panel
 * keyed on the turn would draw the second browse's steps into the first one's
 * list.
 *
 * **A browse is created by `browser_opened` and by nothing else.** The first
 * version of this took any frame for an unknown id, on the reasoning that a
 * socket which reconnected mid-browse should still show what it could. That was
 * the wrong trade once the turn boundaries started clearing `browses`: a
 * background delegation from the previous turn emits a step after `doSend` or a
 * conversation switch has cleared them, and a reducer that reconstructs on any
 * frame puts that browse - and its screenshot of somebody else's page - back
 * under the new transcript. A late frame for a browse this turn never opened is
 * dropped.
 */
export function applyBrowserFrame(current: Browse[], frame: BrowserFrame): Browse[] {
  const existing = current.find((browse) => browse.callId === frame.call_id);
  if (!existing) {
    return frame.kind === "browser_opened" ? [...current, applyTo(opened(frame), frame)] : current;
  }
  return current.map((browse) =>
    browse.callId === frame.call_id ? applyTo(browse, frame) : browse,
  );
}

/** Whether a browse is still going, which is what the panel draws a pulse for. */
export function isRunning(browse: Browse): boolean {
  return browse.outcome === null;
}

/** One browse by its `call_id`, or `null` where the turn no longer holds it. */
export function browseById(browses: Browse[], callId: string | null): Browse | null {
  if (callId === null) return null;
  return browses.find((browse) => browse.callId === callId) ?? null;
}
