// Flush once this many bytes are queued, so a few huge frames cannot pile up.
const MAX_QUEUED_BYTES = 1_048_576;

/** Ordered socket delivery once per paint, with a bound for hidden tabs and bursts. */
export class FrameInbox {
  private events: MessageEvent[] = [];
  private queuedBytes = 0;
  private frame: number | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(private readonly deliver: (events: readonly MessageEvent[]) => void) {}

  push(event: MessageEvent): void {
    this.events.push(event);
    // Only text frames are measured; the socket carries JSON text.
    const data: unknown = event.data;
    this.queuedBytes += typeof data === "string" ? data.length * 2 : 0;
    if (this.events.length >= 256 || this.queuedBytes >= MAX_QUEUED_BYTES) {
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
    this.queuedBytes = 0;
  }
}
