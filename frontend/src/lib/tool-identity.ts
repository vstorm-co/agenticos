/** A stored registry id wins; only legacy calls fall back to the visible name. */
export interface ToolIdentity {
  name: string;
  tool_id?: string | null;
  presentation_kind?: "draft" | "generic" | "platform" | null;
}

export function toolLookupName(call: ToolIdentity): string {
  return call.presentation_kind === "generic" ? "" : (call.tool_id ?? call.name);
}
