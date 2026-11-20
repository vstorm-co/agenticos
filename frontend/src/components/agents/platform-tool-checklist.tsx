"use client";

import { useState } from "react";
import { Search } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  asksFirst,
  chosenTools,
  NewToolsSwitch,
  ToolGroup,
  type GroupApproval,
} from "@/components/agents/mcp-tool-checklist";
import { Input } from "@/components/ui";
import type { McpToolInfo } from "@/lib/mcp-connections-api";
import type { McpApproval, McpToolApproval, PlatformMcpServerRef } from "@/types/agents";
import type { PlatformMcpTool, PlatformToolGroup } from "@/types/mcp";

/** The order the groups are shown in - `PlatformToolGroup`'s own order on the server. */
const GROUP_ORDER: PlatformToolGroup[] = [
  "tables",
  "tasks",
  "workflows",
  "agents",
  "knowledge",
  "skills",
  "projects",
  "automations",
  "apps",
  "runs",
  "connections",
  "account",
  "administration",
];

/** A platform tool as the shared rows read one: a change is a tool not marked read-only. */
function asInfo(tool: PlatformMcpTool): McpToolInfo {
  return { name: tool.name, description: tool.description, read_only: !tool.writes };
}

/**
 * The binding's default as the server applies it: `none` is held to `writes`,
 * because these tools act with the authority of whoever asks.
 */
function floor(approval: McpApproval): McpApproval {
  return approval === "all" ? "all" : "writes";
}

/**
 * The binding with these tools' own approvals, written as the API answers it:
 * sorted by name and left out where there is none, so autosave settles.
 */
export function withToolApproval(
  binding: PlatformMcpServerRef,
  toolApproval: McpToolApproval,
): PlatformMcpServerRef {
  const { tool_approval: _replaced, ...rest } = binding;
  const own = Object.entries(toolApproval).sort(([a], [b]) => (a < b ? -1 : 1));
  return own.length === 0 ? rest : { ...rest, tool_approval: Object.fromEntries(own) };
}

/**
 * The platform's tools grouped by what they work on - tables, agents, workflows,
 * knowledge bases and the rest - each group with one approval for all of its
 * tools, and every tool with its own beside it.
 *
 * Unlike another server's reads and changes, a group here mixes the two, so the
 * group's choice is written to each of its tools, and letting a change run
 * freely is always a decision about one named tool. The binding's default is
 * `all` while every read asks, so a read the platform adds later asks too, and
 * `writes` otherwise. A tool that changes something carries an icon saying so;
 * one that never asks - the person's own language - and one that always does -
 * inviting a member, the organization's initiative - cannot be set.
 */
export function PlatformToolChecklist({
  tools,
  binding,
  onChange,
  disabled,
}: {
  tools: PlatformMcpTool[];
  binding: PlatformMcpServerRef;
  onChange: (next: PlatformMcpServerRef) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("agents");
  const [query, setQuery] = useState("");
  const ungatedNames = new Set(tools.filter((tool) => tool.ungated).map((tool) => tool.name));
  const alwaysNames = new Set(tools.filter((tool) => tool.always_asks).map((tool) => tool.name));
  const approval = floor(binding.approval);
  const toolApproval = binding.tool_approval ?? {};
  const chosen = new Set(binding.allowed_tools ?? tools.map((tool) => tool.name));
  const needle = query.trim().toLowerCase();

  const ungated = (info: McpToolInfo) => ungatedNames.has(info.name);
  const alwaysAsks = (info: McpToolInfo) => alwaysNames.has(info.name);
  const settable = (info: McpToolInfo) => !ungated(info) && !alwaysAsks(info);
  const asks = (info: McpToolInfo) =>
    alwaysAsks(info) || (!ungated(info) && asksFirst(info, approval, toolApproval));

  const toggle = (names: string[], on: boolean) => {
    const next = new Set(chosen);
    const own = { ...toolApproval };
    for (const name of names) {
      if (on) next.add(name);
      else {
        next.delete(name);
        // A tool the agent cannot call has no approval worth keeping or reporting.
        delete own[name];
      }
    }
    onChange(withToolApproval({ ...binding, allowed_tools: chosenTools(tools, next) }, own));
  };
  /**
   * These tools set to ask or not. The default becomes `all` when every read
   * then asks, and each tool keeps its own approval only where it differs.
   */
  const setAsks = (infos: McpToolInfo[], ask: boolean) => {
    const changed = new Set(infos.map((info) => info.name));
    const wanted = tools
      .map(asInfo)
      .filter(settable)
      .map((info) => ({ info, asking: changed.has(info.name) ? ask : asks(info) }));
    const everyReadAsks = wanted.every(({ info, asking }) => asking || info.read_only !== true);
    const nextDefault: McpApproval = everyReadAsks ? "all" : "writes";
    const own: McpToolApproval = {};
    for (const { info, asking } of wanted) {
      if (asking !== asksFirst(info, nextDefault, {})) {
        own[info.name] = asking ? "required" : "never";
      }
    }
    onChange(withToolApproval({ ...binding, approval: nextDefault }, own));
  };
  const summary = (infos: McpToolInfo[]): GroupApproval => {
    const open = infos.filter(settable);
    const asking = open.filter(asks).length;
    return asking === 0 ? "run" : asking === open.length ? "ask" : "mixed";
  };

  const groups = GROUP_ORDER.map((group) => {
    // Reads before changes, each in the server's own order.
    const infos = tools
      .filter((tool) => tool.group === group)
      .sort((a, b) => Number(a.writes) - Number(b.writes))
      .map(asInfo);
    const shown = infos.filter(
      (info) =>
        needle === "" ||
        info.name.toLowerCase().includes(needle) ||
        info.description.toLowerCase().includes(needle),
    );
    return { group, infos, shown };
  }).filter(({ infos, shown }) => infos.length > 0 && shown.length > 0);

  return (
    <div className="space-y-4">
      <NewToolsSwitch
        tools={tools}
        allowed={binding.allowed_tools}
        onChange={(allowed) => onChange({ ...binding, allowed_tools: allowed })}
        disabled={disabled}
      />
      <div className="relative">
        <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2" />
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("toolsSearch")}
          aria-label={t("toolsSearch")}
          className="h-8 rounded-lg pl-8 md:text-[13px]"
        />
      </div>
      {groups.map(({ group, infos, shown }) => (
        <ToolGroup
          key={group}
          label={t("platformToolGroup", { group })}
          tools={infos}
          shown={shown}
          chosen={chosen}
          approval={summary(infos)}
          onAsk={(ask) => setAsks(infos, ask)}
          asks={asks}
          onToolAsk={(info, ask) => setAsks([info], ask)}
          onToggle={toggle}
          prefix={null}
          changes={(info) => info.read_only !== true}
          fixed={(info) =>
            ungated(info)
              ? t("platformUngatedBadge")
              : alwaysAsks(info)
                ? t("platformAlwaysAsksBadge")
                : null
          }
          disabled={disabled}
        />
      ))}
    </div>
  );
}
