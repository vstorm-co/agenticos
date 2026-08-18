import { FLOWS } from "@/lib/onboarding/flows";
import type { RunningFlow } from "@/stores/onboarding-store";

/**
 * Where a running flow waits out a full-page navigation.
 *
 * `sessionStorage`, so it is scoped to the one browser tab and dies with it: this
 * carries a walk across a redirect, it does not make onboarding durable. Whether
 * onboarding is *finished* stays server truth on the user row.
 */
const KEY = "agenticos:onboarding-flow";

/**
 * Stow a running flow so the next page load can pick it back up.
 *
 * Called as the page is being replaced — connecting an MCP server over OAuth
 * assigns `window.location` the provider's consent URL, and the callback returns
 * through a second full load. Without this the walk was gone by the time the
 * connection came back, abandoning the rest of a half-built agent: its limits, its
 * publish, and the first run the whole flow exists to reach.
 */
export function stashFlow(flow: RunningFlow): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(flow));
  } catch {
    // Storage refused (private mode, a full quota). Losing the walk is the
    // behaviour we already had; it must not also break the navigation.
  }
}

/**
 * Take back a stowed flow, clearing it — so a flow resumes once, on the load that
 * follows the redirect, and a later reload starts clean.
 *
 * Anything that is not a flow this build recognises is dropped rather than
 * restored: the value survives a deploy, and a step index from an older step list
 * would resume the walk in the middle of a different flow.
 */
export function takeStashedFlow(): RunningFlow | null {
  let raw: string | null = null;
  try {
    raw = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
  } catch {
    return null;
  }
  if (raw === null) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    return isRunningFlow(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function isRunningFlow(value: unknown): value is RunningFlow {
  if (typeof value !== "object" || value === null) return false;
  const flow = value as Record<string, unknown>;
  return (
    typeof flow.flowId === "string" &&
    Object.hasOwn(FLOWS, flow.flowId) &&
    typeof flow.index === "number" &&
    Number.isInteger(flow.index) &&
    flow.index >= 0 &&
    typeof flow.choices === "object" &&
    flow.choices !== null &&
    (flow.flowAgentId === null || typeof flow.flowAgentId === "string")
  );
}
