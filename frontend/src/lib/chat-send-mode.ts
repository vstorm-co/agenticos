export type ChatSendMode = "queue" | "steer";

/** A preference belongs to one signed-in account, organization and agent. */
export function chatSendModeScope(
  accountId: string | null | undefined,
  organizationId: string | null | undefined,
  agentId: string | null | undefined,
): string | null {
  if (
    typeof accountId !== "string" ||
    accountId.trim().length === 0 ||
    typeof organizationId !== "string" ||
    organizationId.trim().length === 0 ||
    agentId === undefined ||
    (agentId !== null && (typeof agentId !== "string" || agentId.trim().length === 0))
  )
    return null;
  // JSON null is the explicit general-assistant scope. Missing identity is never
  // replaced with a string sentinel that could collide with a real agent id.
  return JSON.stringify([accountId, organizationId, agentId]);
}

/** Values read from local storage are untrusted and may come from older builds. */
export function isChatSendMode(value: unknown): value is ChatSendMode {
  return value === "queue" || value === "steer";
}

export function isChatSendModeScope(value: string): boolean {
  try {
    const ids: unknown = JSON.parse(value);
    return (
      Array.isArray(ids) &&
      ids.length === 3 &&
      typeof ids[0] === "string" &&
      ids[0].trim().length > 0 &&
      typeof ids[1] === "string" &&
      ids[1].trim().length > 0 &&
      (ids[2] === null || (typeof ids[2] === "string" && ids[2].trim().length > 0))
    );
  } catch {
    return false;
  }
}
