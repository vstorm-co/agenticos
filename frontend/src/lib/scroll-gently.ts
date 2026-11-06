import { prefersReducedMotion } from "@/lib/motion";

/** An explicit viewport move, bounded in time and relinquished on reader input. */
export function scrollGently(element: HTMLElement, top: number): () => void {
  const start = element.scrollTop;
  const target = Math.max(0, top);
  if (prefersReducedMotion() || Math.abs(target - start) < 1) {
    element.scrollTop = target;
    return () => {};
  }
  let frame = 0;
  let began: number | null = null;
  const cancel = () => {
    cancelAnimationFrame(frame);
    element.removeEventListener("wheel", cancel);
    element.removeEventListener("touchstart", cancel);
    element.removeEventListener("pointerdown", cancel);
    element.removeEventListener("keydown", cancel);
  };
  const tick = (now: number) => {
    began ??= now;
    const progress = Math.min(1, (now - began) / 360);
    element.scrollTop = start + (target - start) * (1 - Math.pow(1 - progress, 3));
    if (progress < 1) frame = requestAnimationFrame(tick);
    else cancel();
  };
  element.addEventListener("wheel", cancel, { passive: true });
  element.addEventListener("touchstart", cancel, { passive: true });
  element.addEventListener("pointerdown", cancel, { passive: true });
  element.addEventListener("keydown", cancel);
  frame = requestAnimationFrame(tick);
  return cancel;
}
