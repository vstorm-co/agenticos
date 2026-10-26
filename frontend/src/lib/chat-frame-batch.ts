function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** Join adjacent text deltas only; control/tool/part boundaries keep their order. */
export function coalesceChatFrames(events: readonly MessageEvent[]): MessageEvent[] {
  const result: MessageEvent[] = [];
  let pending: {
    event: MessageEvent;
    frame: Record<string, unknown>;
    data: Record<string, unknown>;
    chunks: string[];
  } | null = null;
  const flush = () => {
    if (pending === null) return;
    result.push(
      new MessageEvent("message", {
        data: JSON.stringify({
          ...pending.frame,
          data: { ...pending.data, content: pending.chunks.join("") },
        }),
        origin: pending.event.origin,
      }),
    );
    pending = null;
  };
  for (const event of events) {
    const frame: unknown = typeof event.data === "string" ? JSON.parse(event.data) : null;
    if (
      record(frame) &&
      (frame.type === "text_delta" || frame.type === "thinking_delta") &&
      record(frame.data) &&
      typeof frame.data.content === "string"
    ) {
      if (
        pending !== null &&
        pending.frame.type === frame.type &&
        pending.data.index === frame.data.index
      ) {
        pending.chunks.push(frame.data.content);
      } else {
        flush();
        pending = { event, frame, data: frame.data, chunks: [frame.data.content] };
      }
    } else {
      flush();
      result.push(event);
    }
  }
  flush();
  return result;
}
