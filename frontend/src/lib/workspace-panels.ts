import { BROWSER_TOOLS, DESKTOP_TOOLS, type Browse } from "@/lib/browse";
import { toolLookupName } from "@/lib/tool-identity";
import type { BrowseSurface } from "@/stores/browser-panel-store";
import type { ChatMessage } from "@/types/chat";

/** A preview's kind comes from its real tool call, never from its title or URL. */
export function browseSurfaces(
  messages: readonly ChatMessage[],
): ReadonlyMap<string, BrowseSurface> {
  const surfaces = new Map<string, BrowseSurface>();
  for (const message of messages)
    for (const call of message.toolCalls ?? []) {
      const name = toolLookupName(call);
      if (DESKTOP_TOOLS.has(name)) surfaces.set(call.id, "computer");
      else if (BROWSER_TOOLS.has(name)) surfaces.set(call.id, "browser");
    }
  return surfaces;
}

/** Frames can precede the tool list; only browser-native metadata is an earlier proof. */
export function browseSurface(
  browse: Browse,
  surfaces: ReadonlyMap<string, BrowseSurface>,
): BrowseSurface | null {
  return surfaces.get(browse.callId) ?? (browse.navigable || browse.nativeId ? "browser" : null);
}

/** Explicit visits stay selected; an empty pane follows only its own kind of view. */
export function selectedWorkspaceBrowse(
  browses: readonly Browse[],
  surfaces: ReadonlyMap<string, BrowseSurface>,
  surface: BrowseSurface | null,
  callId: string | null,
): Browse | null {
  if (surface === null) return null;
  const selected =
    callId === null
      ? browses
          .filter((browse) => !browse.nativeId && browseSurface(browse, surfaces) === surface)
          .at(-1)
      : browses.find((browse) => browse.callId === callId);
  if (!selected) return null;
  const known = browseSurface(selected, surfaces);
  if (known !== null && known !== surface) return null;
  if (surface === "browser" && selected.tabId)
    return (
      browses
        .filter(
          (browse) =>
            browse.tabId === selected.tabId &&
            (callId !== null || !browse.nativeId) &&
            browseSurface(browse, surfaces) === "browser",
        )
        .at(-1) ?? selected
    );
  return selected;
}

export interface WorkspaceStartAccess {
  teamRoom: boolean;
  hasAgent: boolean;
  hostedCapabilities: readonly string[] | null;
  canRun: boolean;
  readOnly: boolean;
  localSelected: boolean;
  busy: boolean;
  connected: boolean;
}

/** UI refusal keys; configuration is evidence of a target, not a runtime health claim. */
export function workspaceStartReason(access: WorkspaceStartAccess, surface: BrowseSurface) {
  if (access.teamRoom) return access.readOnly ? "readOnly" : "roomComposer";
  if (!access.hasAgent) return "chooseAgent";
  if (access.readOnly || !access.canRun) return "readOnly";
  if (access.hostedCapabilities === null) return "unknown";
  if (!access.hostedCapabilities.includes(surface === "browser" ? "browser_use" : "computer_use"))
    return surface === "browser" ? "browserUnavailable" : "computerUnavailable";
  if (access.localSelected) return "localSelected";
  if (access.busy) return "busy";
  if (!access.connected) return "disconnected";
  return null;
}

/** Require a deliberate web destination; credentials and other schemes never enter a turn. */
export function workspaceWebsite(value: string): string | null {
  try {
    const url = new URL(value.trim());
    return (url.protocol === "https:" || url.protocol === "http:") && !url.username && !url.password
      ? url.href
      : null;
  } catch {
    return null;
  }
}
