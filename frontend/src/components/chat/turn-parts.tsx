"use client";

import { toolLookupName } from "@/lib/tool-identity";

import { memo } from "react";
import { ChevronRight, Lightbulb, MessageCircleQuestion } from "lucide-react";
import { useTranslations } from "next-intl";

import { useLinger, useSmoothText } from "@/hooks/use-smooth-text";
import { BROWSER_TOOLS, DESKTOP_TOOLS } from "@/lib/browse";
import { toolEntry } from "@/lib/tool-catalog";
import { drawnUnderTheAnswer } from "@/lib/turn-extras";
import { draftOf } from "@/lib/drafts";
import { isVisualTool } from "@/lib/visuals";
import { cn } from "@/lib/utils";
import { useInChatScope } from "@/stores/chat-scope-context";
import type { DelegateRef } from "@/lib/delegations";
import { toolStep, type McpServerRef } from "@/lib/tool-steps";
import type { MessagePart, MessageReply, ToolCall } from "@/types";
import type { TurnFileSource } from "@/types/chat";
import type { Mentionable } from "@/types/mention";
import { AgentSteps } from "./agent-step";
import { TurnDrafts } from "./draft-card";
import { TurnBrowses } from "./browser-card";
import { MarkdownContent } from "./markdown-content";
import { RichText } from "./mention-chip";
import { ToolCallCard } from "./tool-call-card";
import { ToolGroup } from "./tool-group";
import { PhoneCallCard } from "@/components/phone/phone-call-card";
import { ModelSetupCard } from "./model-setup-card";
import { WorkflowRunCard } from "./workflow-run-card";
import { TurnVisuals } from "./visual-panel";
import { YouFace } from "./you-face";
import { ReplyQuote } from "./reply-quote";
import { STALLED_AFTER_MS, useTurnElapsed, WorkFold } from "./work-fold";
import { formatElapsed } from "@/lib/elapsed";

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
  fileSource,
  onCiteClick,
  startedAt,
  durationMs,
  stopped = false,
  failed = false,
  waitingFor,
  lastHeartbeatAt,
  allowSetupActions = false,
}: {
  /** Private configuration actions are opt-in; shared transcripts remain read-only. */
  allowSetupActions?: boolean;
  parts: MessagePart[];
  isStreaming: boolean;
  isUser: boolean;
  /** The organization's MCP connections, or empty where the caller has none to offer. */
  mcpServers: McpServerRef[];
  /** The agents the reader can see, for naming a delegate; empty on a public page. */
  agents?: readonly DelegateRef[];
  openLastStep?: boolean;
  fileSource?: TurnFileSource;
  onCiteClick?: (index: number) => void;
  /** When the turn began, which a live turn counts its working time from. */
  startedAt?: Date;
  /** How long the run took, for a reloaded turn; absent where it is not known. */
  durationMs?: number;
  /** The run was stopped part-way, so its work ends without an answer or a "Done". */
  stopped?: boolean;
  failed?: boolean;
  /** Includes a delegate paused outside the parent's own tool parts. */
  waitingFor?: "approval" | "answer";
  /** When the run behind this turn last stamped itself alive, if known. */
  lastHeartbeatAt?: Date;
}) {
  const runs = runsOf(parts);
  const waiting =
    waitingFor === "answer"
      ? "awaiting_answer"
      : waitingFor === "approval"
        ? "awaiting_approval"
        : parts.some((part) => part.toolCall?.status === "awaiting_answer")
          ? "awaiting_answer"
          : parts.some((part) => part.toolCall?.status === "awaiting_approval")
            ? "awaiting_approval"
            : undefined;
  const elapsed = useTurnElapsed(startedAt, isStreaming && !waiting);
  // A run with no work to fold has no WorkFold to say it has gone quiet, so
  // the turn says so itself once its heartbeat is stale.
  const heartbeatAgeMs = useTurnElapsed(lastHeartbeatAt, isStreaming && !waiting);
  const tSteps = useTranslations("chat.steps");
  const tChat = useTranslations("chat");
  const tTools = useTranslations("chat.tools");
  const latest = parts.at(-1);
  const activity = latest?.toolCall
    ? toolStep(
        latest.toolCall.name,
        latest.toolCall.args,
        false,
        tTools,
        mcpServers,
        latest.toolCall,
      ).label
    : latest?.type === "thinking"
      ? tChat("thinking")
      : undefined;
  // A browse is shown in the turn whether or not the steps around it fold:
  // inside a folded run it would be a live browser nobody can see is running.
  const render = (run: PartRun, visuals = true, afterWork = false) =>
    run.kind === "tools" ? (
      <div key={run.parts[0].id} className="w-full">
        <ToolGroup calls={run.parts.map((part) => part.toolCall!)} mcpServers={mcpServers}>
          <AgentSteps showAll>
            {run.parts.map((part, step) => (
              <ToolCallCard
                key={part.id}
                toolCall={part.toolCall!}
                fileSource={fileSource}
                mcpServers={mcpServers}
                agents={agents}
                // Rich outputs may open on arrival; routine action details stay opt-in.
                startOpen={openLastStep && run.isLast && step === run.parts.length - 1}
                autoExpand={toolEntry(toolLookupName(part.toolCall!))?.opensOnSight === true}
              />
            ))}
          </AgentSteps>
        </ToolGroup>
        {visuals && <TurnVisuals calls={visualCalls([run])} />}
        {visuals && <TurnDrafts calls={draftCalls([run])} />}
      </div>
    ) : run.part.type === "thinking" ? (
      <ThinkingBlock
        key={run.part.id}
        text={run.content}
        open={false}
        // The block still taking deltas, not every block in a streaming
        // turn: the orb marks where the thinking is arriving, and a turn
        // that thought twice would otherwise show two of them.
        isStreaming={isStreaming && run.isLast}
      />
    ) : run.part.type === "model_setup" ? (
      <ModelSetupCard
        key={run.part.id}
        agentId={run.part.setupAgentId}
        interactive={allowSetupActions}
      />
    ) : run.part.type === "steer" ? (
      <SteerBlock key={run.part.id} text={run.content} />
    ) : run.part.type === "phone_call" && run.part.phoneCallId ? (
      <PhoneCallCard key={run.part.id} callId={run.part.phoneCallId} />
    ) : run.part.type === "workflow_run" && run.part.workflowRun ? (
      <WorkflowRunCard key={run.part.id} run={run.part.workflowRun} />
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
        afterWork={afterWork}
      />
    );

  const active = !failed && (isStreaming || waiting !== undefined);
  const split = foldWork(runs, stopped, active);
  if (split === null) {
    const stalledFor =
      isStreaming && !waiting && heartbeatAgeMs !== null && heartbeatAgeMs > STALLED_AFTER_MS
        ? formatElapsed(heartbeatAgeMs, tSteps)
        : null;
    return (
      <>
        {stalledFor !== null && (
          <p role="status" className="text-muted-foreground py-0.5 text-[13px]">
            {tSteps("stalledFor", { duration: stalledFor })}
          </p>
        )}
        {runs.map((run) => render(run))}
      </>
    );
  }
  return (
    <>
      <WorkFold
        key={active ? "live" : "finished"}
        live={active}
        steps={split.steps}
        durationMs={durationMs ?? elapsed}
        stopped={stopped}
        failed={failed}
        running={isStreaming && !waiting && !failed}
        activity={activity}
        waiting={failed ? undefined : waiting}
        lastHeartbeatAt={lastHeartbeatAt}
      >
        {split.folded.map((run, index) => {
          const previous = split.folded[index - 1];
          return render(
            run,
            false,
            previous?.kind === "tools" || previous?.part.type === "thinking",
          );
        })}
      </WorkFold>
      <TurnBrowses calls={browseCalls(runs)} />
      <TurnVisuals calls={visualCalls(split.folded)} />
      <TurnDrafts calls={draftCalls(split.folded)} />
      {split.shown.map((run, index) => render(run, true, index === 0))}
    </>
  );
}

export const ThinkingBlock = memo(function ThinkingBlock({
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
      <summary className="text-muted-foreground hover:text-foreground/80 flex min-h-8 cursor-pointer items-center gap-2 px-1.5 text-[13px] select-none">
        {/* A bulb, not the orb. The orb is the turn at work, and it sits on the
            line above while the turn runs - two of them stacked read as the same
            thing said twice. This row is an aside you can open, drawn like the
            steps beside it: its own mark in the same slot, then its name. */}
        <span aria-hidden className="flex size-5 shrink-0 items-center justify-center">
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
      <div className="text-muted-foreground border-border/70 mt-2 ml-4 max-h-72 overflow-y-auto border-l pl-5 text-[13px] leading-relaxed">
        <MarkdownContent content={text} />
      </div>
    </details>
  );
});

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
    <details className="group text-muted-foreground text-[13px]">
      <summary className="hover:text-foreground flex min-h-8 cursor-pointer items-center gap-2 rounded-md py-1 focus-visible:outline-2 focus-visible:outline-offset-2">
        <span className="flex size-5 shrink-0 items-center justify-center" aria-hidden>
          <MessageCircleQuestion className="size-3.5" />
        </span>
        <span className="shrink-0 font-medium">
          {askedBy ? t("askUserAskedBy", { name: askedBy }) : t("askUserAsked")}
        </span>
        <span className="line-clamp-1 min-w-0 break-words group-open:line-clamp-none">
          {question}
        </span>
        <ChevronRight
          aria-hidden
          className="size-3.5 shrink-0 transition-transform group-open:rotate-90"
        />
      </summary>
      <div className="border-border mt-1 ml-1.5 space-y-2 border-l py-1 pl-4">
        <div className="text-xs font-medium">{t("askUserAnswered")}</div>
        <p className="text-foreground/80 break-words whitespace-pre-wrap">{answer}</p>
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
/** How long a streamed word takes to fade in - `.stream-word` in globals.css. */
const WORD_FADE_MS = 700;

export function TextBubble({
  text,
  showCursor,
  isUser,
  onCiteClick,
  mentions,
  afterWork = false,
  replyTo,
  replyAgents = [],
}: {
  text: string;
  replyTo?: MessageReply;
  replyAgents?: readonly DelegateRef[];
  showCursor: boolean;
  isUser: boolean;
  onCiteClick?: (index: number) => void;
  /** What the person picked with `@`, shown where it sits in their text. */
  mentions?: readonly Mentionable[];
  /** It follows the turn's steps or thoughts, so it opens the answer. */
  afterWork?: boolean;
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
          "bg-foreground/[0.07] text-foreground relative max-w-full min-w-0 rounded-2xl",
          compact ? "px-3 py-2" : "px-4 py-3",
          replyTo && "max-w-[min(85%,28rem)] min-w-[min(100%,12rem)]",
        )}
      >
        {replyTo && <ReplyQuote reply={replyTo} agents={replyAgents} embedded />}
        <p
          className={cn(
            "[overflow-wrap:anywhere] break-words whitespace-pre-wrap",
            compact ? "text-[13px]" : "text-sm",
          )}
        >
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
        "prose-sm max-w-full min-w-0 leading-relaxed [overflow-wrap:anywhere]",
        compact ? "text-[13.5px]" : "text-[15px]",
        // A little more air after the steps than between two rows of them: the
        // answer starts here, and set as tight as a step it read as one more.
        afterWork && !compact && "pt-1",
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
      // Drawn under the answer instead - buttons, a card - by `TurnExtras`.
      if (drawnUnderTheAnswer(toolLookupName(part.toolCall))) continue;
      const open = runs.at(-1);
      if (open?.kind === "tools") open.parts.push(part);
      else runs.push({ kind: "tools", parts: [part], isLast: false });
      continue;
    }
    if (
      part.type === "ask_user" ||
      part.type === "workflow_run" ||
      part.type === "phone_call" ||
      part.type === "model_setup"
    ) {
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

/** All browser operations in turn order, so the card tracks each tab's latest page. */
export function browseCalls(runs: PartRun[]): ToolCall[] {
  return runs.flatMap((run) =>
    run.kind === "tools"
      ? run.parts.flatMap((part) =>
          part.toolCall &&
          (BROWSER_TOOLS.has(toolLookupName(part.toolCall)) ||
            DESKTOP_TOOLS.has(toolLookupName(part.toolCall)))
            ? [part.toolCall]
            : [],
        )
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
          part.toolCall && isVisualTool(toolLookupName(part.toolCall)) ? [part.toolCall] : [],
        )
      : [],
  );
}

/** The calls that write a draft in these runs, in the order they were made. */
export function draftCalls(runs: PartRun[]): ToolCall[] {
  return runs.flatMap((run) =>
    run.kind === "tools"
      ? run.parts.flatMap((part) =>
          part.toolCall && draftOf(part.toolCall) !== null ? [part.toolCall] : [],
        )
      : [],
  );
}

/**
 * Keep the live timeline chronological. Only a settled turn separates its final
 * text from the work history. Text delivered before asking the person a question
 * is also output, even when more work follows on resume. Prose length and
 * reasoning markup never decide whether something was a progress update.
 */
export function foldWork(
  runs: PartRun[],
  stopped = false,
  active = false,
): { folded: PartRun[]; shown: PartRun[]; steps: number } | null {
  const hasWork = runs.some((run) => run.kind === "tools" || run.part.type === "thinking");
  if (!hasWork) return null;
  const delivered = new Set<PartRun>();
  if (!active) {
    for (let index = 0; index < runs.length; index += 1) {
      const run = runs[index]!;
      const question =
        run.kind === "other"
          ? run.part.type === "ask_user"
          : run.parts[0]?.toolCall !== undefined &&
            toolLookupName(run.parts[0].toolCall) === "ask_user_question";
      if (!question) continue;
      for (let previous = index - 1; previous >= 0; previous -= 1) {
        const candidate = runs[previous]!;
        if (candidate.kind !== "other" || candidate.part.type !== "text") break;
        delivered.add(candidate);
      }
    }
  }
  let answer = runs.length;
  if (!active && !stopped) {
    while (answer > 0) {
      const previous = runs[answer - 1]!;
      if (previous.kind !== "other" || previous.part.type !== "text") break;
      answer -= 1;
    }
  }
  const folded = runs.slice(0, answer).filter((run) => !delivered.has(run));
  return {
    folded,
    shown: runs.filter((run, index) => index >= answer || delivered.has(run)),
    steps: folded.reduce((sum, run) => sum + (run.kind === "tools" ? run.parts.length : 0), 0),
  };
}
