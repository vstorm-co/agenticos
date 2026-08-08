"use client";
import { useMemo, useState, type MouseEvent } from "react";
import { Code2 } from "lucide-react";
import type { ToolCall } from "@/types";
import { cn } from "@/lib/utils";
import { toolStep } from "@/lib/tool-steps";
import { toolEntry } from "@/lib/tool-catalog";
import { AgentStep } from "./agent-step";
import { ChartMessage, parseChartResult } from "./chart-message";
import { RAGSearchResults } from "./tool-results/rag";
import { WebSearchResults, parseWebSearch } from "./tool-results/web-search";
import { LoadSkillResult } from "./tool-results/skills";
import { GenericToolResult, RawToolView } from "./tool-results/generic";
import { RunPythonResult } from "./tool-results/run-python";
import { WorkspaceToolResult } from "./tool-results/workspace";
import { useMcpToolServers } from "@/hooks";
import { useTranslations } from "next-intl";

interface ToolCallCardProps {
  toolCall: ToolCall;
  /**
   * The conversation this call happened in, when it is known.
   *
   * Only the workspace tools use it, and only to turn a file they wrote into a file
   * somebody can open - the files live in *this* conversation's workspace, and the
   * route that serves them is addressed through it.
   */
  conversationId?: string;
  /**
   * Open this step on mount.
   *
   * Set for the last call of the newest turn and nothing else: that result is what
   * somebody returning to a conversation is looking at, and every other finished call
   * is a line they can open if they want it.
   */
  startOpen?: boolean;
}

/**
 * One tool call, as a step in the turn's narration.
 *
 * It used to be a card: a border, a fill, a status pill, a chevron, a raw-view
 * button, per call. A turn that listed a directory, read a file and wrote another
 * arrived as three boxes of chrome wrapped around three short sentences, with the
 * answer pushed below them. Now it is a line - *Wrote test1.md* - that opens into
 * whatever the call actually produced.
 *
 * What opens is unchanged and deliberately so: every renderer under `tool-results/`
 * is still here, and the raw view is still one click away for somebody debugging a
 * call. The step decides *whether* something is worth opening by default, and the
 * defaults are the calls whose whole value is the thing they produced - a chart, a
 * question waiting on an answer, code that ran, and a file that was written.
 */
export function ToolCallCard({ toolCall, conversationId, startOpen = false }: ToolCallCardProps) {
  const t = useTranslations("chat.tools");
  // What this side knows about the tool: its icon, its wording, and which renderer
  // opens underneath it. One table, keyed on the id the backend registers - see
  // `lib/tool-catalog.ts`. A tool with no entry - an MCP tool, or one a binding
  // renamed - reads as generic, which is the honest answer for a name nothing here
  // has ever seen.
  const entry = toolEntry(toolCall.name);
  const renderer = entry?.render ?? "generic";
  // Memoized above the state below, which reads it: a chart that came back as an
  // error string has nothing to show, and must not be opened on sight.
  //
  // `parseChartResult` does `JSON.parse` for string results, returning a NEW object
  // each call. Without this memo, every streaming delta (text/thinking) re-renders
  // this step → new spec ref → ChartMessage re-renders → Recharts re-layouts →
  // ResponsiveContainer briefly reports -1 dimensions → `RenderedTicksReporter`
  // setState → React detects too-many updates and bails with "Maximum update depth
  // exceeded".
  const chartSpec = useMemo(
    () =>
      renderer === "chart" && toolCall.status === "completed"
        ? parseChartResult(toolCall.result)
        : null,
    [renderer, toolCall.status, toolCall.result],
  );
  // A chart is the one entry whose payoff can fail to arrive: `create_chart` that
  // came back as an error string has nothing to show, so opening it would put a
  // stack of JSON where the picture was meant to be.
  const produced = renderer !== "chart" || chartSpec !== null;
  // Worth opening without being asked, wherever it sits in the turn - see
  // `opensOnSight` in `lib/tool-catalog.ts`.
  const opensOnSight = entry?.opensOnSight === true && produced;

  // Open on arrival, not on sight - with `opensOnSight` as the exception. A call that
  // finishes while somebody is watching shows what it produced - code that ran, a file
  // that was written - and the same call re-read from history is one line in a
  // transcript they came back to for something else. Opening those on mount made every
  // past turn a wall, which is what a replayed conversation looked like. A chart is the
  // other way round: only the last step of a turn is handed `startOpen`, so three
  // charts arrived as two headers and one picture.
  const [expanded, setExpanded] = useState(
    toolCall.status === "completed" && (startOpen || opensOnSight),
  );
  const [showRaw, setShowRaw] = useState(false);

  const resultText =
    toolCall.result !== undefined
      ? typeof toolCall.result === "string"
        ? toolCall.result
        : JSON.stringify(toolCall.result, null, 2)
      : "";

  const isRAGSearch =
    renderer === "rag" && toolCall.status === "completed" && typeof toolCall.result === "string";
  const webResults =
    renderer === "web-search" &&
    toolCall.status === "completed" &&
    typeof toolCall.result === "string"
      ? parseWebSearch(toolCall.result)
      : null;

  const mcpServers = useMcpToolServers();
  const isRunning = toolCall.status === "running" || toolCall.status === "pending";
  // Its own state, not a kind of running: a parked call produces no result until
  // somebody decides, so a spinner here is a lie that never resolves.
  const isParked = toolCall.status === "awaiting_approval";
  const isError = toolCall.status === "error";
  // The servers are what turn `linear_create_issue` into "Linear · Create issue".
  // Nothing on a tool call says where it came from, so the prefix is matched against
  // the connections this caller has - see `useMcpToolServers`.
  const step = toolStep(toolCall.name, toolCall.args, !isRunning && !isParked, mcpServers);

  // Whether this call finished *while mounted*, which is what "somebody watched it
  // happen" means. Not `useChanged`, which reports the mount pass too - and the mount
  // pass is exactly the replayed-history case this must not treat as live. Written
  // during render, so a step that just produced something is never shown collapsed for
  // a frame first.
  const [seenStatus, setSeenStatus] = useState(toolCall.status);
  if (seenStatus !== toolCall.status) {
    setSeenStatus(toolCall.status);
    if (toolCall.status === "completed" && entry?.opensWhenDone === true && produced) {
      setExpanded(true);
    }
  }

  // `render: "none"` is a call with nothing worth opening - `list_skills` says the
  // agent looked, and the list it got back is a prompt fragment rather than something
  // a person reads.
  const openable = renderer !== "none";

  return (
    <AgentStep
      label={step.label}
      detail={isRunning ? null : step.detail}
      kind={step.kind}
      logoDomain={step.logoDomain}
      state={isParked ? "parked" : isRunning ? "running" : isError ? "error" : "done"}
      expanded={expanded && openable}
      onToggle={
        openable
          ? () =>
              setExpanded((prev) => {
                const next = !prev;
                if (!next) setShowRaw(false);
                return next;
              })
          : undefined
      }
      actions={
        openable ? (
          <button
            type="button"
            onClick={(event: MouseEvent) => {
              event.stopPropagation();
              setShowRaw((raw) => !raw);
            }}
            title={showRaw ? t("showFormatted") : t("showRaw")}
            aria-label={showRaw ? t("showFormatted") : t("showRaw")}
            className={cn(
              "text-muted-foreground/60 hover:text-foreground shrink-0 rounded-md p-1",
              showRaw && "text-foreground",
            )}
          >
            <Code2 className="h-3 w-3" />
          </button>
        ) : undefined
      }
    >
      {showRaw ? (
        <RawToolView toolCall={toolCall} resultText={resultText} />
      ) : isRAGSearch ? (
        <RAGSearchResults result={resultText} />
      ) : webResults !== null ? (
        <WebSearchResults data={webResults} />
      ) : chartSpec !== null ? (
        <ChartMessage spec={chartSpec} />
      ) : renderer === "run-python" ? (
        <RunPythonResult toolCall={toolCall} resultText={resultText} />
      ) : renderer === "load-skill" ? (
        <LoadSkillResult resultText={resultText} status={toolCall.status} />
      ) : renderer === "workspace" ? (
        <WorkspaceToolResult
          toolCall={toolCall}
          resultText={resultText}
          conversationId={conversationId}
        />
      ) : (
        // Everything else, and every renderer whose payload turned out not to be one:
        // a `web_search` that errored, a `create_chart` that came back as a sentence.
        <GenericToolResult toolCall={toolCall} resultText={resultText} />
      )}
    </AgentStep>
  );
}
