/** Ordered socket delivery once per paint, with a bound for hidden tabs and bursts. */
export class FrameInbox {
  private events: MessageEvent[] = [];
  private frame: number | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(private readonly deliver: (events: readonly MessageEvent[]) => void) {}

  push(event: MessageEvent): void {
    this.events.push(event);
    if (this.events.length >= 256) {
      this.flush();
    } else if (this.frame === null) {
      this.frame = requestAnimationFrame(() => this.flush());
      // Background tabs may stop animation frames entirely; terminal frames
      // and session readiness must still reach the consumer.
      this.timer = setTimeout(() => this.flush(), 50);
    }
  }

  flush(): void {
    const events = this.events;
    this.clear();
    if (events.length > 0) this.deliver(events);
  }

  clear(): void {
    if (this.frame !== null) cancelAnimationFrame(this.frame);
    if (this.timer !== null) clearTimeout(this.timer);
    this.frame = null;
    this.timer = null;
    this.events = [];
  }
}
