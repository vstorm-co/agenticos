import type { TurnFileSource } from "@/types/chat";

/** The server records this origin; never infer it from current composer settings. */
export function turnFileSourceFromEvent(event: unknown): TurnFileSource | undefined {
  if (!event || typeof event !== "object" || !("file_source" in event)) return undefined;
  const source = event.file_source;
  if (!source || typeof source !== "object" || !("kind" in source)) return undefined;
  if (
    source.kind === "local" &&
    "id" in source &&
    typeof source.id === "string" &&
    source.id.length > 0
  )
    return { kind: "local", id: source.id };
  if (
    source.kind === "conversation" &&
    "id" in source &&
    typeof source.id === "string" &&
    source.id.length > 0
  )
    return { kind: "conversation", id: source.id };
  return undefined;
}
