import { spotlightPath } from "@/components/onboarding/spotlight";

/** How far the light stands off the control it frames — driver.js's old `stagePadding`. */
const PADDING = 8;

/** The corner of the cut-out and of the ring around it. */
const RADIUS = 10;

/** A box in viewport coordinates. */
interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** What draws the tour's light: moves it onto a control, or takes it away. */
export interface TourSpotlight {
  /**
   * Light `element`, or dim the whole page with nothing lit when it is `null`.
   * Resolves once the light has arrived — at once for a snap, at the end of the
   * travel otherwise, or early when a later call supersedes this one.
   */
  focus(element: Element | null): Promise<void>;
  destroy(): void;
}

/**
 * How long the light takes to travel `distance` pixels.
 *
 * Scaled rather than fixed: a fixed duration either drags a hop from a tab to the
 * panel under it or flings the light across the screen from the sidebar to a
 * header button. The floor keeps a short hop visible; the ceiling keeps a long
 * one from feeling like a wait.
 */
export function travelMs(distance: number): number {
  return Math.min(700, Math.max(280, 240 + distance * 0.35));
}

/** Ease in and out, so the eye can pick the light up as it leaves and as it lands. */
function ease(progress: number): number {
  return progress < 0.5 ? 4 * progress ** 3 : 1 - (-2 * progress + 2) ** 3 / 2;
}

function lerp(from: Box, to: Box, amount: number): Box {
  return {
    x: from.x + (to.x - from.x) * amount,
    y: from.y + (to.y - from.y) * amount,
    width: from.width + (to.width - from.width) * amount,
    height: from.height + (to.height - from.height) * amount,
  };
}

/** The lit box around `element`, measured now. */
function padded(element: Element): Box {
  const rect = element.getBoundingClientRect();
  return {
    x: rect.left - PADDING,
    y: rect.top - PADDING,
    width: rect.width + PADDING * 2,
    height: rect.height + PADDING * 2,
  };
}

/**
 * The tour's dim, cut-out and ring, drawn by us rather than by driver.js.
 *
 * driver.js only dims: in dark mode its near-black overlay over a near-black page
 * left the lit control at 1.1:1 against the rest of the screen, so the reader
 * could not find what the caption was talking about. And it glides badly: its
 * easing restarts from the light's current position every frame, so a 400ms move
 * spends most of the distance in about a hundred milliseconds — a sweep from the
 * sidebar to a header button read as the light teleporting. So driver.js keeps
 * the caption, the click shield and the keyboard, with its own overlay made
 * transparent, and this layer draws what the reader sees: the dim with a hole in
 * it, and a coloured ring with a beacon on the hole's edge (`globals.css`).
 *
 * The hole and the ring are measured from the control every frame, so they follow
 * it through a scroll, a layout shift or the click pulse; a travel between two
 * controls is eased towards the control's *live* box, so it lands where the
 * control is when it arrives, not where it was when it left. A control removed
 * from the document (its page navigated away) holds the light where it last was
 * rather than letting a zero rect drag it to the corner. `focus(null)` dims the
 * whole page and fades the ring out — the welcome and the farewell describe no
 * control, and a light shrunk to a dot in the middle of the screen read as a
 * glitch. A reader who asks for reduced motion gets snaps instead of travel.
 *
 * The layer is also the page's click shield under driver's overlay: driver's
 * overlay has a hole over the control, and `globals.css` turns off driver's
 * rule that made every element unclickable (it froze browser extensions' own
 * prompts too), so what falls through the hole lands here rather than on the page.
 */
export function createTourSpotlight(reducedMotion: boolean): TourSpotlight {
  const SVG = "http://www.w3.org/2000/svg";
  const root = document.createElement("div");
  root.className = "tour-spotlight";
  root.setAttribute("aria-hidden", "true");
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("class", "tour-spotlight-dim");
  const path = document.createElementNS(SVG, "path");
  svg.appendChild(path);
  const ring = document.createElement("div");
  ring.className = "tour-spotlight-ring";
  ring.style.borderRadius = `${RADIUS}px`;
  const beacon = document.createElement("span");
  beacon.className = "tour-spotlight-beacon";
  ring.appendChild(beacon);
  root.append(svg, ring);
  document.body.appendChild(root);

  let target: Element | null = null;
  let shown: Box | null = null;
  let travel: { from: Box; start: number; duration: number } | null = null;
  let arrived: (() => void) | null = null;
  let frame = 0;
  let drawn = "";

  const land = () => {
    travel = null;
    arrived?.();
    arrived = null;
  };

  const draw = (box: Box | null) => {
    const width = window.innerWidth;
    const height = window.innerHeight;
    const key = box
      ? `${width},${height},${box.x},${box.y},${box.width},${box.height}`
      : `${width},${height}`;
    if (key === drawn) return;
    drawn = key;
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    path.setAttribute(
      "d",
      box
        ? spotlightPath(width, height, box.x, box.y, box.width, box.height, RADIUS)
        : `M${width},0 L0,0 L0,${height} L${width},${height} Z`,
    );
    ring.classList.toggle("is-visible", box !== null);
    if (box) {
      ring.style.left = `${box.x}px`;
      ring.style.top = `${box.y}px`;
      ring.style.width = `${box.width}px`;
      ring.style.height = `${box.height}px`;
    }
  };

  const tick = (now: number) => {
    let box: Box | null = null;
    if (target) {
      // Detached: its page went away under it. Hold the light where it was.
      box = target.isConnected ? padded(target) : shown;
      if (box && travel) {
        const progress = Math.min(1, (now - travel.start) / travel.duration);
        box = lerp(travel.from, box, ease(progress));
        if (progress === 1) land();
      }
    }
    shown = box;
    draw(box);
    frame = requestAnimationFrame(tick);
  };
  frame = requestAnimationFrame(tick);

  return {
    focus(element) {
      if (element === target) return Promise.resolve();
      land();
      const from = shown;
      target = element;
      if (!element || !from || reducedMotion) return Promise.resolve();
      const to = padded(element);
      const distance = Math.hypot(to.x - from.x, to.y - from.y);
      travel = { from, start: performance.now(), duration: travelMs(distance) };
      return new Promise((resolve) => {
        arrived = resolve;
      });
    },
    destroy() {
      cancelAnimationFrame(frame);
      land();
      root.remove();
    },
  };
}
