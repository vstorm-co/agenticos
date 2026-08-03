"use client";

import { FileText, FolderOpen, Search, TerminalSquare } from "lucide-react";

import { CopyButton } from "../copy-button";
import type { ToolCall } from "@/types";

/** The workspace tools this renders. Anything else falls through to the generic card. */
const WORKSPACE_TOOLS = ["ls", "glob", "grep", "read_file", "write_file", "edit_file", "execute"];

export function isWorkspaceTool(name: string): boolean {
  return WORKSPACE_TOOLS.includes(name);
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

/** What this call is about, in one line: a path, a pattern, or a command. */
function subject(toolCall: ToolCall): { icon: typeof FileText; text: string } | null {
  const args = toolCall.args ?? {};
  const path = asString(args.path) ?? asString(args.file_path);
  const pattern = asString(args.pattern);
  const command = asString(args.command) ?? asString(args.cmd);

  if (toolCall.name === "execute" && command !== null)
    return { icon: TerminalSquare, text: command };
  if (toolCall.name === "grep" && pattern !== null)
    return { icon: Search, text: path === null ? pattern : `${pattern} in ${path}` };
  if (toolCall.name === "glob" && pattern !== null) return { icon: Search, text: pattern };
  if (path !== null) return { icon: toolCall.name === "ls" ? FolderOpen : FileText, text: path };
  return null;
}

/**
 * What a file the agent wrote is *for* — the body of `write_file`, or of `edit_file`.
 *
 * `edit_file` carries the replacement rather than the whole file, which is the more
 * useful thing to show: an edit is a diff by intent, and the file it edited is one
 * click away in the workspace panel.
 */
function body(toolCall: ToolCall): string | null {
  const args = toolCall.args ?? {};
  return (
    asString(args.content) ??
    asString(args.text) ??
    asString(args.new_string) ??
    asString(args.new_str) ??
    null
  );
}

/** A listing's output split into lines, or null when it is not one. */
function lines(name: string, result: string): string[] | null {
  if (!["ls", "glob", "grep"].includes(name)) return null;
  const found = result
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  return found.length === 0 ? null : found;
}

/**
 * A sandbox tool call, shown as what it did rather than as its arguments.
 *
 * The card used to print the JSON it was called with and its return line
 * underneath — so "wrote a file called test.md containing hej" arrived as
 * `{"path": "test.md", "content": "hej"}` above `Wrote 1 lines to
 * /workspace/test.md`. Everything needed to read it was there and none of it was
 * legible.
 *
 * So: the path (or the pattern, or the command) as a heading, the content as a code
 * block with a copy button, a listing as a list. The raw view is still one click
 * away in the card's own header, which is where somebody debugging a call should
 * look — and is why nothing here needs to be exhaustive.
 */
export function WorkspaceToolResult({
  toolCall,
  resultText,
}: {
  toolCall: ToolCall;
  resultText: string;
}) {
  const head = subject(toolCall);
  const written = body(toolCall);
  const listed = lines(toolCall.name, resultText);
  const Icon = head?.icon ?? FileText;

  const isRunning = toolCall.status === "running" || toolCall.status === "pending";
  const isError = toolCall.status === "error";

  return (
    <div className="space-y-2 py-1">
      {head !== null && (
        <p className="flex items-center gap-2 text-xs">
          <Icon className="text-muted-foreground h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="min-w-0 flex-1 truncate font-mono">{head.text}</span>
        </p>
      )}

      {written !== null && (
        <div className="relative">
          <pre className="bg-muted max-h-64 overflow-auto rounded-md p-3 text-[11px] whitespace-pre-wrap">
            {written}
          </pre>
          <CopyButton text={written} className="absolute top-1 right-1 h-6 w-6 rounded-md" />
        </div>
      )}

      {isRunning && <p className="text-muted-foreground text-xs italic">Running…</p>}

      {/* A listing is a list. Fifty paths in a `pre` is a wall; fifty rows is
          something an eye can scan for the one it wanted. */}
      {!isRunning && listed !== null && (
        <ul className="divide-border/60 divide-y">
          {listed.slice(0, 50).map((line) => (
            <li key={line} className="truncate py-1 font-mono text-[11px]">
              {line}
            </li>
          ))}
          {listed.length > 50 && (
            <li className="text-muted-foreground py-1 text-[11px]">
              and {listed.length - 50} more — open the raw view for all of them
            </li>
          )}
        </ul>
      )}

      {/* Whatever the tool said back, when it is not a listing and not the body we
          already showed. `write_file` answers "Wrote 1 lines to /workspace/test.md",
          which is worth one muted line and no more. */}
      {!isRunning && listed === null && resultText !== "" && (
        <p
          className={isError ? "text-destructive text-xs" : "text-muted-foreground text-xs italic"}
        >
          {resultText.length > 400 ? `${resultText.slice(0, 400)}…` : resultText}
        </p>
      )}
    </div>
  );
}
