/** Native browser handles are resolved only inside the owning paired app. */
import { invokeShell, ShellError } from "@/lib/desktop/shell";

export type NativeBrowserAction =
  | "show"
  | "hide"
  | "close"
  | "navigate"
  | "back"
  | "forward"
  | "reload"
  | "take_over"
  | "give_back"
  | "state";
export interface NativeBrowserBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}
export interface NativeBrowserState {
  url: string;
  title: string;
  held: boolean;
}

export function controlNativeBrowser(
  id: string,
  action: NativeBrowserAction,
  options: { bounds?: NativeBrowserBounds; url?: string; mount?: string } = {},
): Promise<unknown> {
  return invokeShell("native_browser_view", { id, action, ...options });
}

export async function nativeBrowserState(id: string): Promise<NativeBrowserState> {
  const value = await controlNativeBrowser(id, "state");
  if (
    typeof value !== "object" ||
    value === null ||
    !("url" in value) ||
    typeof value.url !== "string" ||
    !("title" in value) ||
    typeof value.title !== "string" ||
    !("held" in value) ||
    typeof value.held !== "boolean"
  )
    throw new ShellError("malformed", "native_browser_state");
  return { url: value.url, title: value.title, held: value.held };
}
