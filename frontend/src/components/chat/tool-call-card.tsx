"use client";

import { toolLookupName } from "@/lib/tool-identity";
import { memo, useMemo, useState } from "react";
import { toolIcon } from "@/lib/step-icons";
import type { ToolCall } from "@/types";
import { toolStep } from "@/lib/tool-steps";
import { toolEntry } from "@/lib/tool-catalog";
import { RawToolView } from "./tool-results/generic";
import { AgentStep } from "./agent-step";
import { platformCallError } from "./tool-results/platform-objects";
import { AgentAvatar } from "@/components/agents/agent-avatar";
import { delegateNamed, type DelegateRef } from "@/lib/delegations";
import type { McpServerRef } from "@/lib/tool-steps";
import { useTranslations } from "next-intl";

interface ToolCallCardProps {
  toolCall: ToolCall;
  /**
   * The organization's MCP connections, for naming a call that came from one.
   *
   * Passed rather than fetched here, and that is what lets a public page render a
   * step at all: reading them off the API is two authenticated queries, and the
   * hosted route has neither a session nor a query client. A caller with none to
   * offer passes an empty list, which is what makes `linear_create_issue` read as
   * a humanized name instead of failing.
   */
  mcpServers: McpServerRef[];
  /**
   * The agents the reader can see, for naming the one a delegation asked.
   *
   * Passed like `mcpServers` and for the same reason; a surface with none still
   * names the delegate from its slug.
   */
  agents?: readonly DelegateRef[];
}

/** Diagnostic details stay raw; charts, media and question cards belong in the transcript. */
export const ToolCallCard = memo(function ToolCallCard({
  toolCall,
  mcpServers,
  agents = [],
}: ToolCallCardProps) {
  const t = useTranslations("chat.tools");
  const renderer = toolEntry(toolLookupName(toolCall))?.render;
  const [expanded, setExpanded] = useState(false);
  const resultText = useMemo(() => {
    if (!expanded || toolCall.result === undefined) return "";
    return typeof toolCall.result === "string"
      ? toolCall.result
      : JSON.stringify(toolCall.result, null, 2);
  }, [expanded, toolCall.result]);

  const isRunning = toolCall.status === "running" || toolCall.status === "pending";
  // Its own state, not a kind of running: a parked call produces no result until
  // somebody decides, so a spinner here is a lie that never resolves.
  const isParked = toolCall.status === "awaiting_approval" || toolCall.status === "awaiting_answer";
  const isError = toolCall.status === "error" || platformCallError(toolCall) !== null;
  // The servers are what turn `linear_create_issue` into "Linear · Create issue".
  // Nothing on a tool call says where it came from, so the prefix is matched against
  // the connections this caller has - see `useMcpToolServers`.
  const step = toolStep(
    toolCall.name,
    toolCall.args,
    !isRunning && !isParked,
    t,
    mcpServers,
    toolCall,
  );

  // One agent asking another reads as that, with the delegate's own face.
  const delegate =
    renderer === "delegation" && typeof toolCall.args?.subagent_type === "string"
      ? delegateNamed(toolCall.args.subagent_type, agents)
      : null;
  return (
    <AgentStep
      label={
        delegate === null
          ? step.label
          : t(
              isRunning
                ? "askingAgent"
                : toolCall.status === "unfinished"
                  ? "stoppedAskingAgent"
                  : "askedAgent",
              { name: delegate.name },
            )
      }
      detail={delegate !== null ? null : step.detail}
      kind={step.kind}
      icon={toolIcon(step.kind === "mcp" ? toolCall.name : toolLookupName(toolCall), step.kind)}
      logoDomain={step.logoDomain}
      mark={
        delegate === null ? undefined : (
          <AgentAvatar
            agentId={delegate.id ?? delegate.slug}
            slug={delegate.slug}
            hasAvatar={delegate.has_avatar}
            colorSlot={delegate.avatar_color}
            size="sm"
            className="-my-1 h-5 w-5"
          />
        )
      }
      state={isParked ? "parked" : isRunning ? "running" : isError ? "error" : "done"}
      parkedOn={toolCall.status === "awaiting_answer" ? "answer" : "approval"}
      expanded={expanded}
      onToggle={() => setExpanded((previous) => !previous)}
    >
      <RawToolView toolCall={toolCall} resultText={resultText} />
    </AgentStep>
  );
});
