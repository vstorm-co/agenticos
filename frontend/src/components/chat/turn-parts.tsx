"use client";

import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { toolEntry } from "@/lib/tool-catalog";
import type { McpServerRef } from "@/lib/tool-steps";
import type { MessagePart } from "@/types";
import { AgentSteps } from "./agent-step";
import { MarkdownContent } from "./markdown-content";
import { ToolCallCard } from "./tool-call-card";

/**
 * A turn's body: its reasoning, its work and its words, in the order they arrived.
 *
 * Extracted out of `MessageItem` so the hosted page renders the *same* turn rather
 * than a second interpretation of one. The page had its own: a `whitespace-pre-wrap`
 * bubble for the answer, an italic paragraph for the reasoning and a bare label per
 * tool call - which is three renderers to keep in step with these, and the #144
 * defect waiting to happen again.
 *
 * What stayed in `MessageItem` is everything about being a *member*: the avatar and
 * the account behind it, the agent's name and version, the cost, the rating buttons,
 * regenerate, the sources panel and the attachments a signed-in reader may open.
 * None of it belongs on a public page, which is the whole reason the split falls
 * here.
 *
 * `mcpServers` is passed rather than fetched, and that is what makes the component
 * usable on both surfaces: the servers turn `linear_create_issue` into
 * "Linear · Create issue", and reading them from the API inside the step would be
 * two authenticated queries on a page where nobody is signed in - and there is no
 * query client on that route to run them.
 */
export function TurnParts({
  parts,
  isStreaming,
  isUser,
  mcpServers,
  openLastStep = false,
  conversationId,
  onCiteClick,
}: {
  parts: MessagePart[];
  isStreaming: boolean;
  isUser: boolean;
  /** The organization's MCP connections, or empty where the caller has none to offer. */
  mcpServers: McpServerRef[];
  openLastStep?: boolean;
  conversationId?: string;
  onCiteClick?: (index: number) => void;
}) {
  return (
    <>
      {runsOf(parts).map((run) =>
        run.kind === "tools" ? (
          <div key={run.parts[0].id} className="w-full">
            {/* The rail folds its own earlier steps away, but it cannot see what is
                in them - so whether this run holds something a person has to answer
                is decided here, where the statuses and the names are. */}
            <AgentSteps
              showAll={mustShowEveryStep(run.parts)}
              done={run.parts.length > 1 && !isStreaming}
            >
              {run.parts.map((part, step) => (
                <ToolCallCard
                  key={part.id}
                  toolCall={part.toolCall!}
                  conversationId={conversationId}
                  mcpServers={mcpServers}
                  // The last call of that turn, which is the one whose result the
                  // reader is here for.
                  startOpen={openLastStep && run.isLast && step === run.parts.length - 1}
                />
              ))}
            </AgentSteps>
          </div>
        ) : run.part.type === "thinking" ? (
          <ThinkingBlock
            key={run.part.id}
            text={run.content}
            open={isStreaming && run.isLast}
            isStreaming={isStreaming}
          />
        ) : (
          <TextBubble
            key={run.part.id}
            text={run.content}
            showCursor={isStreaming && run.isLast}
            isUser={isUser}
            onCiteClick={onCiteClick}
          />
        ),
      )}
    </>
  );
}

export function ThinkingBlock({
  text,
  open,
  isStreaming,
}: {
  text: string;
  open: boolean;
  isStreaming: boolean;
}) {
  const t = useTranslations("chat");
  return (
    <details className="group" open={open}>
      {/* A line, not a box. The reasoning is an aside on the way to an answer, and a
          bordered panel around it gives it more weight on the page than the answer
          itself - which is backwards, and was the loudest thing in every turn. */}
      <summary className="text-muted-foreground hover:text-foreground/80 flex cursor-pointer items-center gap-2 text-[13px] select-none">
        <Sparkles className="h-3.5 w-3.5 shrink-0 opacity-60" aria-hidden />
        {t("thoughtAboutIt")}
        {isStreaming && (
          <span className="bg-foreground/40 inline-block h-1 w-1 animate-pulse rounded-full" />
        )}
      </summary>
      {/* Markdown, not a `<pre>`. Reasoning is written the way the answer is - the
          models that expose it head each block with `**Analyzing attached files**`
          and use lists inside them - so a monospaced block rendered the asterisks
          and the underscores literally, in a face that says "this is output"
          about the one part of a turn that is prose. Still the muted, smaller,
          scrollable aside it was; only the text is read properly now. */}
      <div className="text-muted-foreground border-foreground/10 mt-2 max-h-72 overflow-y-auto border-l pl-3.5 text-[13px] leading-relaxed">
        <MarkdownContent content={text} />
      </div>
    </details>
  );
}

/**
 * What was said, by whichever side said it.
 *
 * **Only the person gets a bubble.** An assistant turn is prose - headings, lists,
 * code, a table - and a rounded grey box around it makes every answer look like a
 * chat message from 2016: the fill fights the code blocks nested inside it, the
 * padding eats the width a table needs, and a turn made of three parts arrives as
 * three separate boxes with hairlines between them. Unwrapped, the answer is the
 * page, which is what every tool of this kind settled on. The user's message keeps
 * its bubble precisely because it is the short one, and the contrast is what makes a
 * long transcript scannable at all.
 */
export function TextBubble({
  text,
  showCursor,
  isUser,
  onCiteClick,
}: {
  text: string;
  showCursor: boolean;
  isUser: boolean;
  onCiteClick?: (index: number) => void;
}) {
  if (isUser) {
    return (
      <div className="bg-foreground text-background relative rounded-2xl rounded-tr-sm px-3 py-2 sm:px-4 sm:py-2.5">
        <p className="text-sm break-words whitespace-pre-wrap">{text}</p>
      </div>
    );
  }

  return (
    <div className="prose-sm max-w-none text-[15px] leading-relaxed">
      <MarkdownContent content={text} onCiteClick={onCiteClick} />
      {showCursor && (
        <span className="ml-1 inline-block h-4 w-1.5 animate-pulse rounded-full bg-current" />
      )}
    </div>
  );
}

/**
 * One stretch of a turn: a run of tool steps, or a single part of another kind.
 *
 * The two shapes are separate so the render has nothing to defend against - a run of
 * tools always has a first step, and a part of another kind always has the text that
 * earned it a run.
 */
type PartRun =
  | {
      kind: "tools";
      /** Never empty: the run exists because a call opened it. */
      parts: [MessagePart, ...MessagePart[]];
      /** Whether this run ends the turn, which is what may still be streaming. */
      isLast: boolean;
    }
  | { kind: "other"; part: MessagePart; content: string; isLast: boolean };

/**
 * The turn's parts, with consecutive tool calls gathered into one run.
 *
 * Grouping is what makes the steps read as one thread: the rail they hang from has to
 * be a single element, because a border on each row leaves gaps between them and a
 * dashed line says something this does not mean. A part of any other kind - text, or
 * thinking - closes the run, which is right: the agent said something, so what follows
 * is a new stretch of work.
 *
 * Empty text and thinking parts are dropped rather than rendered as empty bubbles,
 * which is what the flat map did with them.
 */
export function runsOf(parts: MessagePart[]): PartRun[] {
  const runs: PartRun[] = [];
  for (const part of parts) {
    if (part.type === "tool" && part.toolCall) {
      const open = runs.at(-1);
      if (open?.kind === "tools") open.parts.push(part);
      else runs.push({ kind: "tools", parts: [part], isLast: false });
      continue;
    }
    if (
      (part.type === "text" || part.type === "thinking") &&
      part.content !== undefined &&
      part.content !== ""
    ) {
      runs.push({ kind: "other", part, content: part.content, isLast: false });
    }
  }
  const last = runs.at(-1);
  if (last !== undefined) last.isLast = true;
  return runs;
}

/**
 * Whether this run must show every step rather than fold all but the last.
 *
 * Three reasons, and they are all "the reader would otherwise miss something":
 * a call that failed, one parked waiting for their approval, and a step whose
 * result *is* the answer - a chart. The rail's default is right for work nobody
 * asked to watch, and wrong for a turn that drew three charts: two of them
 * became the line "2 earlier steps", so the same turn showed three pictures live
 * and one after a reload.
 *
 * Which steps are payloads comes from `opensOnSight` in `lib/tool-catalog.ts`,
 * the same row the card reads to decide whether to open itself - so a tool is
 * described in one place and the rail and the card cannot disagree about it.
 */
export function mustShowEveryStep(parts: MessagePart[]): boolean {
  return parts.some((part) => {
    const call = part.toolCall;
    if (!call) return false;
    if (call.status === "error" || call.status === "awaiting_approval") return true;
    return toolEntry(call.name)?.opensOnSight === true;
  });
}
