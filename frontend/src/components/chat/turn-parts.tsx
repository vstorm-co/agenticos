"use client";

import { Lightbulb, MessageCircleQuestion } from "lucide-react";
import { useTranslations } from "next-intl";

import { useLinger, useSmoothText } from "@/hooks/use-smooth-text";
import { toolEntry } from "@/lib/tool-catalog";
import { isVisualTool } from "@/lib/visuals";
import { cn } from "@/lib/utils";
import { useInChatScope } from "@/stores/chat-scope-context";
import type { DelegateRef } from "@/lib/delegations";
import type { McpServerRef } from "@/lib/tool-steps";
import type { MessagePart, ToolCall } from "@/types";
import type { Mentionable } from "@/types/mention";
import { AgentSteps } from "./agent-step";
import { TurnBrowses } from "./browser-card";
import { MarkdownContent } from "./markdown-content";
import { RichText } from "./mention-chip";
import { ToolCallCard } from "./tool-call-card";
import { TurnVisuals } from "./visual-panel";
import { YouFace } from "./you-face";
import { useTurnElapsed, WorkFold, WorkingLine } from "./work-fold";

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
  agents = [],
  openLastStep = false,
  conversationId,
  onCiteClick,
  startedAt,
  durationMs,
  stopped = false,
}: {
  parts: MessagePart[];
  isStreaming: boolean;
  isUser: boolean;
  /** The organization's MCP connections, or empty where the caller has none to offer. */
  mcpServers: McpServerRef[];
  /** The agents the reader can see, for naming a delegate; empty on a public page. */
  agents?: readonly DelegateRef[];
  openLastStep?: boolean;
  conversationId?: string;
  onCiteClick?: (index: number) => void;
  /** When the turn began, which a live turn counts its working time from. */
  startedAt?: Date;
  /** How long the run took, for a reloaded turn; absent where it is not known. */
  durationMs?: number;
  /** The run was stopped part-way, so its work ends without an answer or a "Done". */
  stopped?: boolean;
}) {
  const runs = runsOf(parts);
  const elapsed = useTurnElapsed(startedAt, isStreaming);
  // A browse is shown in the turn whether or not the steps around it fold:
  // inside a folded run it would be a live browser nobody can see is running.
  const render = (run: PartRun, browses = true) =>
    run.kind === "tools" ? (
      <div key={run.parts[0].id} className="w-full">
        {/* The rail folds its own earlier steps away, but it cannot see what is
                in them - so whether this run holds something a person has to answer
                is decided here, where the statuses and the names are. */}
        <AgentSteps
          showAll={mustShowEveryStep(run.parts)}
          done={run.parts.length > 1 && !isStreaming && !stopped}
        >
          {run.parts.map((part, step) => (
            <ToolCallCard
              key={part.id}
              toolCall={part.toolCall!}
              conversationId={conversationId}
              mcpServers={mcpServers}
              agents={agents}
              // The last call of that turn, which is the one whose result the
              // reader is here for.
              startOpen={openLastStep && run.isLast && step === run.parts.length - 1}
            />
          ))}
        </AgentSteps>
        {browses && <TurnBrowses calls={browseCalls([run])} />}
        {browses && <TurnVisuals calls={visualCalls([run])} />}
      </div>
    ) : run.part.type === "thinking" ? (
      <ThinkingBlock
        key={run.part.id}
        text={run.content}
        open={isStreaming && run.isLast}
        // The block still taking deltas, not every block in a streaming
        // turn: the orb marks where the thinking is arriving, and a turn
        // that thought twice would otherwise show two of them.
        isStreaming={isStreaming && run.isLast}
      />
    ) : run.part.type === "steer" ? (
      <SteerBlock key={run.part.id} text={run.content} />
    ) : run.part.type === "ask_user" ? (
      <AskUserBlock
        key={run.part.id}
        question={run.part.question ?? ""}
        answer={run.part.answer ?? ""}
        askedBy={run.part.askedBy}
      />
    ) : (
      <TextBubble
        key={run.part.id}
        text={run.content}
        showCursor={isStreaming && run.isLast}
        isUser={isUser}
        onCiteClick={onCiteClick}
      />
    );

  if (isStreaming) {
    return (
      <>
        {runs.some(isWork) && <WorkingLine elapsedMs={elapsed} />}
        {runs.map((run) => render(run))}
      </>
    );
  }
  const split = foldWork(runs, stopped);
  if (split === null) return <>{runs.map((run) => render(run))}</>;
  return (
    <>
      <WorkFold steps={split.steps} durationMs={durationMs ?? elapsed} stopped={stopped}>
        {split.folded.map((run) => render(run, false))}
      </WorkFold>
      <TurnBrowses calls={browseCalls(split.folded)} />
      <TurnVisuals calls={visualCalls(split.folded)} />
      {split.shown.map((run) => render(run))}
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
        {/* A bulb, not the orb. The orb is the turn at work, and it sits on the
            line above while the turn runs - two of them stacked read as the same
            thing said twice. This row is an aside you can open, drawn like the
            steps beside it: its own mark in the same slot, then its name. */}
        <span aria-hidden className="flex h-6 w-6 shrink-0 items-center justify-center">
          <Lightbulb className="h-3.5 w-3.5" />
        </span>
        <span className={cn(isStreaming && "shimmer-text")}>{t("thoughtAboutIt")}</span>
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
 * What the person sent into the running task (#2087), drawn as their every other
 * message is - their face, "You", a filled bubble on the right - at the point in
 * the turn where it reached the model; the text after it is the agent acting on
 * it. An aside saying "You added:" made the person's own words read as a note
 * the agent had taken.
 */
export function SteerBlock({ text }: { text: string }) {
  const t = useTranslations("chat");
  const compact = useInChatScope();
  return (
    <div className="flex flex-col items-end gap-2 py-2">
      <div className="flex flex-row-reverse items-center gap-2">
        <span
          className={cn(
            "flex shrink-0 items-center justify-center overflow-hidden rounded-full",
            compact ? "h-6 w-6" : "h-7 w-7",
          )}
        >
          <YouFace />
        </span>
        <span
          className={cn(
            "font-medium",
            compact ? "text-muted-foreground text-xs" : "text-foreground text-sm",
          )}
        >
          {t("rail.you")}
        </span>
      </div>
      <div className="max-w-[85%]">
        <TextBubble text={text} showCursor={false} isUser />
      </div>
    </div>
  );
}

/**
 * A question the agent put to the person mid-turn, and the answer it acted on.
 *
 * Replayed only: live, the question is the composer's `ask_user` form and the
 * answer goes back through it. Once the turn is stored, the pause has no home in
 * `content`, `thinking` or the tool calls - so a reopened conversation would show
 * neither the question nor the answer the rest of the turn depended on (#502). An
 * aside rather than a bubble, so it reads as a step in the turn, not a message.
 */
export function AskUserBlock({
  question,
  answer,
  askedBy,
}: {
  question: string;
  answer: string;
  askedBy?: string;
}) {
  const t = useTranslations("chat");
  return (
    <div className="border-foreground/10 text-muted-foreground space-y-1.5 border-l pl-3.5 text-[13px]">
      <div className="flex items-center gap-2">
        <MessageCircleQuestion className="h-3.5 w-3.5 shrink-0 opacity-60" aria-hidden />
        {/* Who asked, where a delegate did. The main agent asking is the ordinary
            case and says nothing extra; a specialist asking is the thing a reader
            cannot reconstruct from the transcript otherwise (#1042). */}
        <span className="font-medium">
          {askedBy ? t("askUserAskedBy", { name: askedBy }) : t("askUserAsked")}
        </span>
      </div>
      <p className="text-foreground/80 break-words whitespace-pre-wrap">{question}</p>
      <div className="font-medium">{t("askUserAnswered")}</div>
      <p className="text-foreground/80 break-words whitespace-pre-wrap">{answer}</p>
    </div>
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
/** How long a streamed word takes to fade in - `.stream-word` in globals.css. */
const WORD_FADE_MS = 700;

export function TextBubble({
  text,
  showCursor,
  isUser,
  onCiteClick,
  mentions,
}: {
  text: string;
  showCursor: boolean;
  isUser: boolean;
  onCiteClick?: (index: number) => void;
  /** What the person picked with `@`, shown where it sits in their text. */
  mentions?: readonly Mentionable[];
}) {
  const visible = useSmoothText(text, showCursor && !isUser);
  // The narrow chat beside a page reads at the size of the page around it.
  const compact = useInChatScope();
  // Words keep their fade-in spans until the last one has finished fading: a fast
  // model ends its turn while its final words are still surfacing.
  const flowing = useLinger(showCursor || visible.length < text.length, WORD_FADE_MS);
  if (isUser) {
    // A panel rather than the inverted slab this was. `bg-foreground` made the
    // question the brightest object on the page, louder than the answer under
    // it - which is backwards: the question is what somebody already knows they
    // asked. A fill of the ink at low strength rather than a hairline around a
    // fill three percent off the page: the shape holds in both themes without a
    // line drawn round it.
    return (
      <div
        className={cn(
          "bg-foreground/[0.07] text-foreground relative rounded-2xl",
          compact ? "px-3 py-1.5" : "px-3 py-2 sm:px-4 sm:py-2.5",
        )}
      >
        <p className={cn("break-words whitespace-pre-wrap", compact ? "text-[13px]" : "text-sm")}>
          <RichText text={text} mentions={mentions ?? []} />
        </p>
      </div>
    );
  }

  return (
    // While the turn streams, each new block - a paragraph, a list, a table - rises
    // into place and each new word fades in, instead of appearing; both come off
    // when the turn ends, so nothing already read ever animates again.
    <div
      className={cn(
        "prose-sm max-w-none leading-relaxed",
        compact ? "text-[13.5px]" : "text-[15px]",
        showCursor && "stream-in",
      )}
    >
      <MarkdownContent content={visible} onCiteClick={onCiteClick} streaming={flowing} />
      {showCursor && (
        <span className="stream-cursor ml-1 inline-block h-4 w-1.5 animate-pulse rounded-full bg-current" />
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
export type PartRun =
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
    if (part.type === "ask_user") {
      runs.push({ kind: "other", part, content: "", isLast: false });
      continue;
    }
    if (part.type === "steer" && part.content) {
      runs.push({ kind: "other", part, content: part.content, isLast: false });
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
/**
 * The calls that open a browser window in these runs, in the order they were made:
 * every `browse_web`, and the first `browser_open` - the one that starts the agent
 * driving the tab itself. A later `browser_open` in the same turn navigates that
 * same tab, as its clicks do, so it is drawn in the window already there rather
 * than as a second one beside it.
 */
export function browseCalls(runs: PartRun[]): ToolCall[] {
  let driving = false;
  return runs.flatMap((run) =>
    run.kind === "tools"
      ? run.parts.flatMap((part) => {
          const call = part.toolCall;
          if (call?.name === "browse_web") return [call];
          if (call?.name !== "browser_open" || driving) return [];
          driving = true;
          return [call];
        })
      : [],
  );
}

/**
 * The calls that draw in these runs, in the order they were made. Like a browse,
 * a drawing is shown whether or not the steps around it fold: it is what the
 * turn produced, not a step of the work.
 */
export function visualCalls(runs: PartRun[]): ToolCall[] {
  return runs.flatMap((run) =>
    run.kind === "tools"
      ? run.parts.flatMap((part) =>
          part.toolCall && isVisualTool(part.toolCall.name) ? [part.toolCall] : [],
        )
      : [],
  );
}

export function mustShowEveryStep(parts: MessagePart[]): boolean {
  return parts.some((part) => {
    const call = part.toolCall;
    if (!call) return false;
    if (
      call.status === "error" ||
      call.status === "awaiting_approval" ||
      call.status === "awaiting_answer"
    ) {
      return true;
    }
    return toolEntry(call.name)?.opensOnSight === true;
  });
}

/** Narration short enough to be part of the work rather than part of the answer. */
const NARRATION_CHARS = 400;

/** Whether a stretch is the agent working - calling tools or thinking. */
function isWork(run: PartRun): boolean {
  return run.kind === "tools" || run.part.type === "thinking";
}

/**
 * A finished turn's work before its answer, split from what stays on the page.
 *
 * Folded: every run of tool calls and every thought before the last text, and the
 * short narration between them ("Let me check the list."). Kept, in order: a run a
 * person has to see (`mustShowEveryStep`), a question the agent asked, what the
 * person added mid-turn, and a passage long enough to be an answer of its own.
 * Null when there is no answer to fold the work above, or no work in front of it -
 * except for a stopped turn, whose work folds whole: it ends where it was cut off,
 * and the line saying so is the account of it.
 */
export function foldWork(
  runs: PartRun[],
  stopped = false,
): { folded: PartRun[]; shown: PartRun[]; steps: number } | null {
  const lastText = runs.findLastIndex((run) => run.kind === "other" && run.part.type === "text");
  const answer = lastText <= 0 && stopped ? runs.length : lastText;
  if (answer <= 0) return null;
  const folded: PartRun[] = [];
  const kept: PartRun[] = [];
  for (const run of runs.slice(0, answer)) {
    const foldable =
      run.kind === "tools"
        ? !mustShowEveryStep(run.parts)
        : run.part.type === "thinking" ||
          (run.part.type === "text" && run.content.length <= NARRATION_CHARS);
    (foldable ? folded : kept).push(run);
  }
  if (!folded.some(isWork)) return null;
  const steps = folded.reduce((sum, run) => sum + (run.kind === "tools" ? run.parts.length : 0), 0);
  return { folded, shown: [...kept, ...runs.slice(answer)], steps };
}
