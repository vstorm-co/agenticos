import type { BrowseOutcome, BrowserFrame } from "@/types/chat";

/**
 * One step the engine chose, as the panel lists it.
 *
 * `confidence` is the reason a step is worth listing at all: the engine picks
 * from a table rather than composing an action, and it reports how likely it
 * found the pick. A step taken at 0.31 is one somebody should look at, and a list
 * without the number cannot say which one that was.
 */
export interface BrowseStep {
  step: number;
  operation: string;
  target: string | null;
  confidence: number | null;
  url: string | null;
}

/** One `browse_page` call, assembled from its frames. */
export interface Browse {
  callId: string;
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
}

function opened(frame: BrowserFrame): Browse {
  return {
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
        confidence: frame.confidence ?? null,
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
    case "browser_finished":
      return {
        ...browse,
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
 * list. A frame for a browse nothing opened still creates one - a socket that
 * reconnected mid-browse delivers the rest, and showing those is better than
 * discarding them because the opening frame was missed.
 */
export function applyBrowserFrame(current: Browse[], frame: BrowserFrame): Browse[] {
  const existing = current.find((browse) => browse.callId === frame.call_id);
  if (!existing) {
    return [...current, applyTo(opened(frame), frame)];
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
