"use client";

import { Search } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { usePlatformMcpTools } from "@/hooks";
import { cn } from "@/lib/utils";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import { MCP_TOOL_SEARCH_THRESHOLD, mcpToolCount } from "@/lib/mcp-servers";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";
import type { AgentSpec } from "@/types/agents";

/**
 * A rough per-tool cost of an MCP tool's name, description and argument schema
 * in the model's context. The connection records carry no schemas, so the
 * figure shown is an order of magnitude, and the copy says so.
 */
const TOKENS_PER_TOOL = 400;

interface McpToolLoadNoticeProps {
  spec: AgentSpec;
  connections: OrgMcpConnectionRecord[];
  personalConnections: McpConnectionRecord[];
  /** Switches Tool search on in the draft; nothing here does it unasked. */
  onEnableToolSearch: () => void;
  disabled?: boolean;
  className?: string;
}

/**
 * Says when an agent's MCP servers put more tools in front of its model than it
 * can choose between well, and offers Tool search.
 *
 * Every bound tool's definition rides on every request, so thirty-odd tools
 * cost thousands of tokens a turn before anyone has typed a word, and a model
 * picking among that many picks worse. Tool search hides them until the agent
 * looks one up. It changes what the model sees, so it stays the editor's call:
 * the notice offers it and never switches it on by itself.
 */
export function McpToolLoadNotice({
  spec,
  connections,
  personalConnections,
  onEnableToolSearch,
  disabled,
  className,
}: McpToolLoadNoticeProps) {
  const t = useTranslations("pages.agents");
  const bindsPlatform = spec.mcp_servers.some((ref) => ref.account === "platform");
  const platform = usePlatformMcpTools({ enabled: bindsPlatform });
  const count = mcpToolCount(
    spec.mcp_servers,
    connections,
    personalConnections,
    platform.tools.length,
  );
  const searching = spec.capabilities.some((binding) => binding.id === "tool_search");
  if (count <= MCP_TOOL_SEARCH_THRESHOLD || searching) return null;

  return (
    <div
      role="status"
      className={cn(
        "flex flex-wrap items-center gap-3 rounded-xl border border-amber-500/40 bg-amber-500/5 px-4 py-3 text-sm",
        className,
      )}
    >
      <Search className="h-4 w-4 shrink-0 text-amber-600" aria-hidden />
      <span className="min-w-0 flex-[1_1_16rem]">
        {t("mcpToolLoad", { count, tokens: count * TOKENS_PER_TOOL })}
      </span>
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={disabled}
        onClick={onEnableToolSearch}
      >
        {t("mcpToolLoadEnable")}
      </Button>
    </div>
  );
}
