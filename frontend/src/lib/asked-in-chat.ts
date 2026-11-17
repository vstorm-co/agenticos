import type { ToolApproval } from "@/types/runs";

/**
 * The handle to show beside an asker's name: none when the name already is the
 * handle, which is what the server falls back to for a sender with no display name.
 */
export function visibleHandle(chat: NonNullable<ToolApproval["asked_in_chat"]>): string | null {
  const handle = chat.handle ?? null;
  return handle !== null && !chat.name.endsWith(handle) ? handle : null;
}
