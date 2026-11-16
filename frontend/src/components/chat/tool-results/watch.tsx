"use client";

import { toolLookupName } from "@/lib/tool-identity";

import { WatchesCard } from "@/components/watches/watches-card";
import type { ToolCall } from "@/types";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** A successful write is a reference; management still reads the person's current authorized state. */
export function writtenWatches(calls: readonly ToolCall[]): string[] {
  const watches = new Set<string>();
  for (const call of calls) {
    if (
      !["agenticos_create_watch", "agenticos_update_watch"].includes(toolLookupName(call)) ||
      call.status !== "completed"
    )
      continue;
    let result: unknown = call.result;
    if (typeof result === "string") {
      try {
        result = JSON.parse(result);
      } catch {
        continue;
      }
    }
    if (
      result !== null &&
      typeof result === "object" &&
      "id" in result &&
      typeof result.id === "string" &&
      UUID.test(result.id) &&
      "connection_id" in result &&
      typeof result.connection_id === "string" &&
      UUID.test(result.connection_id)
    )
      watches.add(result.id);
  }
  return [...watches];
}

export function WatchResult({ watchId }: { watchId: string }) {
  return <WatchesCard watchId={watchId} />;
}
