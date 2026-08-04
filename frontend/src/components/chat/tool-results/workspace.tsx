"use client";

import { useState } from "react";
import { Download } from "lucide-react";

import { CopyButton } from "../copy-button";
import { FileIcon, kindOf } from "@/components/sandboxes/file-tile";
import type { FileKind } from "@/components/sandboxes/file-tile";
import { WorkspaceFileViewer } from "@/components/sandboxes/file-viewer";
import { Button } from "@/components/ui";
import { useConversationWorkspace, useFileDownload } from "@/hooks";
import { basename, contentArg, pathArg } from "@/lib/tool-steps";
import { suffixOf, type FileSource } from "@/lib/workspace-files";
import type { ToolCall } from "@/types";
import { useTranslations } from "next-intl";

export { isWorkspaceTool } from "@/lib/tool-steps";

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
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

/** What each kind is called - keys, because a module table has no translator. */
const KIND_KEYS: Record<FileKind, string> = {
  doc: "kindDocument",
  image: "kindImage",
  sheet: "kindSpreadsheet",
  code: "kindCode",
  archive: "kindArchive",
  text: "kindText",
};

/**
 * The file a call produced, as something to open rather than a sentence about it.
 *
 * `write_file` answers "Wrote 1 lines to /workspace/test1.md", which is true and is
 * not what somebody wants from a turn that just made them a document. The card is the
 * end of that turn: what it is called, what kind of thing it is, and the two things
 * anybody does next.
 *
 * **The path is resolved against the conversation's own listing, not trusted.** A
 * tool is called with `test1.md` and answers about `/workspace/test1.md`, while the
 * workspace lists it under whichever of those its backend stored - so a button built
 * from the argument opens a file that is not there about a third of the time. Matching
 * the listing by name is what makes Open and Download mean it; with no match the card
 * is still drawn, without controls that would fail.
 */
function WorkspaceFileCard({
  conversationId,
  path,
}: {
  conversationId: string | undefined;
  path: string;
}) {
  const t = useTranslations("chat.tools");
  const { workspace } = useConversationWorkspace(conversationId ?? null);
  const [opened, setOpened] = useState(false);
  const name = basename(path);
  const suffix = suffixOf(name);
  const entry =
    workspace?.items.find((file) => !file.is_dir && file.path === path) ??
    workspace?.items.find((file) => !file.is_dir && basename(file.path) === name) ??
    null;
  const source: FileSource | null =
    conversationId === undefined ? null : { kind: "conversation", id: conversationId };
  const reachable = source !== null && entry !== null;

  return (
    <div className="border-foreground/12 flex items-center gap-3 rounded-xl border p-2.5">
      <span className="bg-foreground/5 text-foreground/60 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
        <FileIcon path={path} className="h-4 w-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{name}</span>
        <span className="text-muted-foreground text-[11px]">
          {t(KIND_KEYS[kindOf(path)])}
          {suffix !== "" && <> · {suffix.toUpperCase()}</>}
        </span>
      </span>
      {reachable && (
        <FileCardActions source={source} path={entry.path} onOpen={() => setOpened(true)} />
      )}
      {opened && reachable && (
        <WorkspaceFileViewer source={source} path={entry.path} onClose={() => setOpened(false)} />
      )}
    </div>
  );
}

function FileCardActions({
  source,
  path,
  onOpen,
}: {
  source: FileSource;
  path: string;
  onOpen: () => void;
}) {
  const { download, error } = useFileDownload(source);

  return (
    <span className="flex shrink-0 items-center gap-1">
      {error !== null && <span className="text-destructive mr-1 text-[11px]">{error}</span>}
      <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={onOpen}>
        Open
      </Button>
      <Button
        variant="outline"
        size="sm"
        className="h-7 text-xs"
        aria-label={`Download ${basename(path)}`}
        onClick={() => download(path)}
      >
        <Download className="h-3.5 w-3.5" />
        Download
      </Button>
    </span>
  );
}

/**
 * What a workspace tool did, shown as the thing it did.
 *
 * The step above says *Wrote test1.md*; this is what opens under it. Four shapes,
 * one per kind of call, because the calls are not alike: a write ends in a file, a
 * read ends in text, a listing ends in a list, and a command ends in output that has
 * to keep its own line breaks.
 *
 * The raw arguments are one click away in the step's own header, which is where
 * somebody debugging a call looks - and is why nothing here needs to be exhaustive.
 */
export function WorkspaceToolResult({
  toolCall,
  resultText,
  conversationId,
}: {
  toolCall: ToolCall;
  resultText: string;
  conversationId?: string;
}) {
  const t = useTranslations("chat.tools");
  const path = pathArg(toolCall.args);
  const written = contentArg(toolCall.args);
  const listed = lines(toolCall.name, resultText);
  const command = asString(toolCall.args?.command) ?? asString(toolCall.args?.cmd);
  const isRunning = toolCall.status === "running" || toolCall.status === "pending";
  const isError = toolCall.status === "error";
  const finished = !isRunning && toolCall.status !== "awaiting_approval";
  const isWrite = toolCall.name === "write_file" || toolCall.name === "edit_file";
  const showsCard = isWrite && finished && !isError && path !== null;

  return (
    <div className="space-y-2">
      {/* The file itself, once there is one. Not while the call is in flight and not
          when it failed: a card offering to open a file that was never written is the
          one wrong thing this could do. */}
      {showsCard && path !== null && (
        <WorkspaceFileCard conversationId={conversationId} path={path} />
      )}

      {command !== null && (
        <pre className="bg-muted text-foreground/80 overflow-x-auto rounded-md px-3 py-2 font-mono text-[11px]">
          <span className="text-muted-foreground select-none">$ </span>
          {command}
        </pre>
      )}

      {/* What was put into the file. An edit carries the replacement rather than the
          whole file, which is the more useful half: an edit is a diff by intent. */}
      {written !== null && <TextPanel text={written} />}

      {/* What a read answered, which is the file. Kept out of the muted one-liner
          below because it is the point of the call, not a status. */}
      {finished && toolCall.name === "read_file" && resultText !== "" && (
        <TextPanel text={resultText} />
      )}

      {isRunning && <p className="text-muted-foreground text-xs italic">{t("running")}</p>}

      {/* A listing is a list. Fifty paths in a `pre` is a wall; fifty rows is
          something an eye can scan for the one it wanted. */}
      {finished && listed !== null && (
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

      {/* A command's output, which is neither a list nor a file: it is a terminal's,
          and folding its line breaks away would make a stack trace unreadable. */}
      {finished && toolCall.name === "execute" && resultText !== "" && (
        <pre className="bg-foreground/[0.04] max-h-64 overflow-auto rounded-md p-3 font-mono text-[11px] whitespace-pre">
          {resultText}
        </pre>
      )}

      {/* Whatever else the tool said back - and not when the card above already said
          it. `write_file` answers "Wrote 1 lines to /workspace/test1.md", which beside
          a card naming the file is the same fact told worse. It stays for the cases
          with no card: a failure, or a path the arguments did not carry. */}
      {finished &&
        listed === null &&
        !showsCard &&
        !["read_file", "execute"].includes(toolCall.name) &&
        resultText !== "" && (
          <p
            className={
              isError ? "text-destructive text-xs" : "text-muted-foreground text-xs italic"
            }
          >
            {resultText.length > 400 ? `${resultText.slice(0, 400)}…` : resultText}
          </p>
        )}
    </div>
  );
}

/** A body of text with a way to take it, which is what somebody wants from one. */
function TextPanel({ text }: { text: string }) {
  return (
    <div className="relative">
      <pre className="bg-muted max-h-64 overflow-auto rounded-md p-3 pr-9 text-[11px] whitespace-pre-wrap">
        {text}
      </pre>
      <CopyButton text={text} className="absolute top-1 right-1 h-6 w-6 rounded-md" />
    </div>
  );
}
