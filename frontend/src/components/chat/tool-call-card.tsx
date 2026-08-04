"use client";
import { useMemo, useState, type MouseEvent } from "react";
import { Code2 } from "lucide-react";
import type { ToolCall } from "@/types";
import { cn } from "@/lib/utils";
import { isWorkspaceTool, toolStep } from "@/lib/tool-steps";
import { AgentStep } from "./agent-step";
import { ChartMessage, parseChartResult } from "./chart-message";
import { DateTimeResult } from "./tool-results/datetime";
import { RAGSearchResults } from "./tool-results/rag";
import { WebSearchResults, parseWebSearch } from "./tool-results/web-search";
import { LoadSkillResult } from "./tool-results/skills";
import { AskUserResult } from "./tool-results/ask-user";
import { GenericToolResult, RawToolView } from "./tool-results/generic";
import { RunPythonResult } from "./tool-results/run-python";
import { WorkspaceToolResult } from "./tool-results/workspace";
import { FetchUrlResult } from "./tool-results/fetch-url";
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
  const isRunPython = toolCall.name === "run_python";
  const isWorkspaceCall = isWorkspaceTool(toolCall.name);
  const isWrite = toolCall.name === "write_file" || toolCall.name === "edit_file";
  // Open on arrival, not on sight. A call that finishes while somebody is watching
  // shows what it produced - a chart, code that ran, a file that was written - and the
  // same call re-read from history is one line in a transcript they came back to for
  // something else. Opening those on mount made every past turn a wall, which is what
  // a replayed conversation looked like.
  //
  // A question is the exception in the other direction: it is a control, and it stays
  // open whether it is waiting for an answer or showing the one that was given.
  const [expanded, setExpanded] = useState(
    toolCall.name === "ask_user" || (startOpen && toolCall.status === "completed"),
  );
  const [showRaw, setShowRaw] = useState(false);

  const resultText =
    toolCall.result !== undefined
      ? typeof toolCall.result === "string"
        ? toolCall.result
        : JSON.stringify(toolCall.result, null, 2)
      : "";

  const isDateTime = toolCall.name === "get_current_datetime" && toolCall.status === "completed";
  const isRAGSearch =
    (toolCall.name === "search_knowledge_base" || toolCall.name === "search_documents") &&
    toolCall.status === "completed" &&
    typeof toolCall.result === "string";
  const webResults =
    (toolCall.name === "web_search_tool" || toolCall.name === "search_web") &&
    toolCall.status === "completed" &&
    typeof toolCall.result === "string"
      ? parseWebSearch(toolCall.result)
      : null;
  const isWebSearch = webResults !== null;
  const isAskUser = toolCall.name === "ask_user";
  const isFetch =
    (toolCall.name === "fetch_url" || toolCall.name === "fetch") &&
    typeof toolCall.args?.url === "string";
  const isLoadSkill = toolCall.name === "load_skill";
  const isListSkills = toolCall.name === "list_skills";
  // Memoize the parsed chart spec - `parseChartResult` does `JSON.parse` for
  // string results, returning a NEW object each call. Without this memo, every
  // streaming delta (text/thinking) re-renders this step → new spec ref →
  // ChartMessage re-renders → Recharts re-layouts → ResponsiveContainer briefly
  // reports -1 dimensions → `RenderedTicksReporter` setState → React detects
  // too-many updates and bails with "Maximum update depth exceeded".
  const chartSpec = useMemo(
    () =>
      toolCall.name === "create_chart_tool" && toolCall.status === "completed"
        ? parseChartResult(toolCall.result)
        : null,
    [toolCall.name, toolCall.status, toolCall.result],
  );
  const isChart = chartSpec !== null;

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
    if (toolCall.status === "completed" && (isWrite || isRunPython || isChart)) setExpanded(true);
  }

  // `list_skills` has nothing worth opening: the step says the agent looked, and the
  // list it got back is a prompt fragment rather than something a person reads.
  const openable = !isListSkills;

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
      ) : toolCall.status === "completed" && isDateTime ? (
        <DateTimeResult result={resultText} />
      ) : toolCall.status === "completed" && isRAGSearch ? (
        <RAGSearchResults result={resultText} />
      ) : toolCall.status === "completed" && isWebSearch && webResults ? (
        <WebSearchResults data={webResults} />
      ) : isFetch ? (
        <FetchUrlResult url={String(toolCall.args?.url ?? "")} content={resultText} />
      ) : toolCall.status === "completed" && isChart && chartSpec ? (
        <ChartMessage spec={chartSpec} />
      ) : isAskUser ? (
        <AskUserResult args={toolCall.args} resultText={resultText} />
      ) : isRunPython ? (
        <RunPythonResult toolCall={toolCall} resultText={resultText} />
      ) : isLoadSkill ? (
        <LoadSkillResult resultText={resultText} status={toolCall.status} />
      ) : isWorkspaceCall ? (
        <WorkspaceToolResult
          toolCall={toolCall}
          resultText={resultText}
          conversationId={conversationId}
        />
      ) : (
        <GenericToolResult toolCall={toolCall} resultText={resultText} />
      )}
    </AgentStep>
  );
}
