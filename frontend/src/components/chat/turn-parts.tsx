"use client";

import { NativeDisclosure } from "@/components/ui/native-disclosure";

import { toolLookupName } from "@/lib/tool-identity";

import { memo, useMemo } from "react";
import { Lightbulb } from "lucide-react";
import { useTranslations } from "next-intl";

import { useLinger, useSmoothText } from "@/hooks/use-smooth-text";
import { BROWSER_TOOLS, DESKTOP_TOOLS } from "@/lib/browse";
import { TurnProducedOutputs, producedCalls } from "./turn-produced-outputs";
import type { TurnFileSource } from "@/types/chat";
import { groupWorkParts, isQuestionRun, runsOf, type PartRun } from "@/lib/turn-timeline";
export { runsOf } from "@/lib/turn-timeline";
export type { PartRun } from "@/lib/turn-timeline";
import { draftOf } from "@/lib/drafts";
import { isVisualTool } from "@/lib/visuals";
import { cn } from "@/lib/utils";
import { useInChatScope } from "@/stores/chat-scope-context";
import type { DelegateRef } from "@/lib/delegations";
import { toolStep, type McpServerRef } from "@/lib/tool-steps";
import type { MessagePart, MessageReply, ToolCall } from "@/types";
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
import { ChartMessage, parseChartResult } from "./chart-message";
import { YouFace } from "./you-face";
import { ReplyQuote } from "./reply-quote";
import { useTurnElapsed, WorkFold } from "./work-fold";
import { useQuestionInteraction } from "./question-interaction";
import { QuestionTurnCard } from "./question-turn-card";

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
  onCiteClick,
  startedAt,
  durationMs,
  stopped = false,
  failed = false,
  waitingFor,
  allowSetupActions = false,
  messageId,
  fileSource,
}: {
  messageId?: string;
  fileSource?: TurnFileSource;
  /** Private configuration actions are opt-in; shared transcripts remain read-only. */
  allowSetupActions?: boolean;
  parts: MessagePart[];
  isStreaming: boolean;
  isUser: boolean;
  /** The organization's MCP connections, or empty where the caller has none to offer. */
  mcpServers: McpServerRef[];
  /** The agents the reader can see, for naming a delegate; empty on a public page. */
  agents?: readonly DelegateRef[];
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
}) {
  const interaction = useQuestionInteraction();
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
  const tChat = useTranslations("chat");
  const tTools = useTranslations("chat.tools");
  const hasQuestion =
    (interaction !== null && interaction.messageId === messageId) ||
    runs.some(
      (run) => isQuestionRun(run) || (run.kind === "other" && run.part.type === "ask_user"),
    );
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
    isQuestionRun(run) && run.kind === "tools" ? (
      <QuestionTurnCard
        key={run.parts[0].toolCall!.id}
        calls={run.parts.flatMap((part) => (part.toolCall ? [part.toolCall] : []))}
        interaction={
          interaction?.toolCallIds.some((id) => run.parts.some((part) => part.toolCall?.id === id))
            ? interaction
            : undefined
        }
      />
    ) : run.kind === "tools" ? (
      <div key={run.parts[0].id} className="w-full">
        <ToolGroup
          collapsible={visuals}
          calls={run.parts.map((part) => part.toolCall!)}
          mcpServers={mcpServers}
        >
          <AgentSteps showAll>
            {run.parts.map((part) => (
              <ToolCallCard
                key={part.id}
                toolCall={part.toolCall!}
                mcpServers={mcpServers}
                agents={agents}
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
      <QuestionTurnCard
        key={run.part.id}
        calls={[]}
        askedBy={run.part.askedBy}
        answered={(run.questionParts ?? [run.part]).map((part) => ({
          header: part.askedBy ?? "",
          question: part.question ?? "",
          answer: part.answer === "(skipped)" ? [] : part.answer ? [part.answer] : null,
        }))}
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
  const groups = groupWorkParts(runs);
  const workCount = groups.filter((group) => group.kind === "work").length;
  const lastWork = groups.findLast((group) => group.kind === "work");
  const firstBrowserWork = groups.find(
    (group) => group.kind === "work" && browseCalls(group.runs).length > 0,
  );
  // Tab selection spans narration and reasoning groups. Resolve the whole turn
  // in one stable location so a later page updates its card instead of copying it.
  const browserCalls = browseCalls(runs);
  const outputIds = new Set(
    producedCalls(
      runs.flatMap((run) =>
        run.kind === "tools"
          ? run.parts.flatMap((part) => (part.toolCall ? [part.toolCall] : []))
          : [],
      ),
    ).map((call) => call.id),
  );
  const rendered = groups.map((group, index) => {
    if (group.kind === "visible") {
      return render(group.run, true, groups[index - 1]?.kind === "work");
    }
    const latestWork = group === lastWork;
    const live = latestWork && active && (waiting !== undefined || index === groups.length - 1);
    const first = group.runs[0];
    const steps = group.runs.reduce(
      (count, run) => count + (run.kind === "tools" ? run.parts.length : 0),
      0,
    );
    return (
      <div
        key={first.kind === "tools" ? first.parts[0].toolCall!.id : first.part.id}
        data-chat-anchor={first.kind === "tools" ? first.parts[0].toolCall!.id : first.part.id}
        className="space-y-2"
      >
        <WorkFold
          steps={steps}
          durationMs={workCount === 1 && !hasQuestion ? (durationMs ?? elapsed) : null}
          stopped={latestWork && stopped}
          failed={latestWork && failed}
          running={live && isStreaming && !waiting}
          activity={live ? activity : undefined}
          waiting={live && !(hasQuestion && waiting === "awaiting_answer") ? waiting : undefined}
        >
          {group.runs.map((run) => render(run, false))}
        </WorkFold>
        {group === firstBrowserWork && <TurnBrowses calls={browserCalls} />}
        <TurnCharts calls={chartCalls(group.runs)} />
        <TurnProducedOutputs
          calls={group.runs.flatMap((run) =>
            run.kind === "tools"
              ? run.parts.flatMap((part) =>
                  part.toolCall && outputIds.has(part.toolCall.id) ? [part.toolCall] : [],
                )
              : [],
          )}
          fileSource={fileSource}
        />
        <TurnVisuals calls={visualCalls(group.runs)} />
        <TurnDrafts calls={draftCalls(group.runs)} />
      </div>
    );
  });
  if (
    interaction &&
    interaction.messageId === messageId &&
    !runs.some(
      (run) =>
        isQuestionRun(run) &&
        run.kind === "tools" &&
        run.parts.some((part) => interaction.toolCallIds.includes(part.toolCall!.id)),
    )
  ) {
    rendered.push(<QuestionTurnCard key={interaction.id} calls={[]} interaction={interaction} />);
  }
  return rendered;
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
    <NativeDisclosure className="group" open={open}>
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
    </NativeDisclosure>
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
          "bg-foreground/[0.07] text-foreground relative rounded-2xl",
          compact ? "px-3 py-1.5" : "px-3 py-2 sm:px-4 sm:py-2.5",
          replyTo && "max-w-[min(85%,28rem)] min-w-[min(100%,12rem)]",
        )}
      >
        {replyTo && <ReplyQuote reply={replyTo} agents={replyAgents} embedded />}
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
export function chartCalls(runs: PartRun[]): ToolCall[] {
  return runs.flatMap((run) =>
    run.kind === "tools"
      ? run.parts.flatMap((part) =>
          part.toolCall &&
          toolLookupName(part.toolCall) === "create_chart" &&
          part.toolCall.status === "completed"
            ? [part.toolCall]
            : [],
        )
      : [],
  );
}

function TurnCharts({ calls }: { calls: ToolCall[] }) {
  return calls.map((call) => <TurnChart key={call.id} call={call} />);
}

const TurnChart = memo(function TurnChart({ call }: { call: ToolCall }) {
  const spec = useMemo(() => parseChartResult(call.result), [call.result]);
  return spec === null ? null : (
    <div className="my-4">
      <ChartMessage spec={spec} />
    </div>
  );
});

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
