/** Ease discrete mouse-wheel steps; fine pixel input keeps native trackpad momentum. */
export function smoothDesktopWheel(scroller: HTMLElement): () => void {
  let frame = 0;
  let target = scroller.scrollTop;
  let lastFrame = 0;
  const stop = () => {
    cancelAnimationFrame(frame);
    frame = 0;
    target = scroller.scrollTop;
  };
  const animate = (now: number) => {
    const progress = 1 - Math.exp(-Math.max(0, Math.min(now - lastFrame, 64)) / 60);
    lastFrame = now;
    target = Math.max(0, Math.min(target, scroller.scrollHeight - scroller.clientHeight));
    const distance = target - scroller.scrollTop;
    if (Math.abs(distance) < 0.5) {
      scroller.scrollTo({ top: target, behavior: "instant" });
      frame = 0;
      return;
    }
    scroller.scrollTo({ top: scroller.scrollTop + distance * progress, behavior: "instant" });
    frame = requestAnimationFrame(animate);
  };
  const wheel = (event: WheelEvent) => {
    if (
      event.ctrlKey ||
      event.metaKey ||
      event.shiftKey ||
      event.deltaX !== 0 ||
      event.deltaY === 0
    )
      return;
    // Legacy mouse wheels emit 120-pixel notches. Smaller/fractional pixel deltas
    // belong to the native scrolling path; don't synthesize trackpad momentum.
    if (event.deltaMode === 0 && Math.abs(event.deltaY) % 120 !== 0) {
      stop();
      return;
    }
    let node = event.target instanceof Element ? event.target : null;
    while (node && node !== scroller) {
      if (
        node instanceof HTMLElement &&
        node.scrollHeight > node.clientHeight &&
        /auto|scroll/.test(getComputedStyle(node).overflowY)
      )
        return;
      node = node.parentElement;
    }
    event.preventDefault();
    const distance =
      event.deltaY *
      (event.deltaMode === 1 ? 20 : event.deltaMode === 2 ? scroller.clientHeight : 1);
    target = (frame ? target : scroller.scrollTop) + distance;
    if (!frame) {
      lastFrame = performance.now();
      frame = requestAnimationFrame(animate);
    }
  };
  scroller.addEventListener("wheel", wheel, { passive: false });
  scroller.addEventListener("pointerdown", stop);
  scroller.addEventListener("touchstart", stop, { passive: true });
  scroller.addEventListener("keydown", stop);
  return () => {
    stop();
    scroller.removeEventListener("wheel", wheel);
    scroller.removeEventListener("pointerdown", stop);
    scroller.removeEventListener("touchstart", stop);
    scroller.removeEventListener("keydown", stop);
  };
}
