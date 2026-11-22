import type { ToolCall } from "@/types/chat";
import { toolLookupName } from "./tool-identity";
import { pathArg } from "./tool-steps";

/** SDK file failures can be returned as text even when the invocation completed. */
export function failedWorkspaceWrite(result: unknown): boolean {
  if (typeof result === "string") return /^\s*(?:\[?Error:)/i.test(result);
  return typeof result === "object" && result !== null && "error" in result && !!result.error;
}

/** Only workspace-rooted or relative paths; never URLs, traversal or OS absolute paths. */
export function workspaceLinkPath(value: string): string | null {
  let path: string;
  try {
    path = decodeURIComponent(value);
  } catch {
    return null;
  }
  if (/[\\\u0000-\u001f?#:%]/.test(path) || path.startsWith("//")) return null;
  if (path.startsWith("/workspace/")) path = path.slice("/workspace/".length);
  if (!path || path.startsWith("/")) return null;
  if (path.split("/").some((part) => !part || part === "." || part === "..")) return null;
  return path;
}

/** Stronger than legacy cards: links need a positive SDK receipt, not completed alone. */
export function producedWorkspacePaths(calls: readonly ToolCall[]): Map<string, string> {
  const paths = new Map<string, string>();
  for (const call of calls) {
    const name = toolLookupName(call);
    if (
      call.status !== "completed" ||
      call.presentation_kind != null ||
      !["write_file", "edit_file"].includes(name) ||
      typeof call.result !== "string"
    )
      continue;
    const path = pathArg(call.args);
    if (!path) continue;
    const canonical = workspaceLinkPath(path);
    const receipt =
      name === "write_file"
        ? /^Wrote \d+ lines to (.+)$/.exec(call.result.trim())?.[1]
        : /^Edited (.+?): (?:replaced|inserted|deleted|lines)\b[\s\S]*$/i.exec(
            call.result.trim(),
          )?.[1];
    if (canonical && receipt && workspaceLinkPath(receipt) === canonical)
      paths.set(canonical, path);
  }
  return paths;
}
