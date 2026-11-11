"use client";

import { useState } from "react";
import { Search, ShieldCheck, ShieldOff } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Checkbox,
  IconButton,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { McpToolInfo } from "@/lib/mcp-connections-api";
import type { McpApproval, McpToolApproval } from "@/types/agents";

/** Past this many tools the list gets a search box. */
const SEARCHABLE = 8;

/**
 * A tool's name as a person reads it: `notion-create-pages` is "Create pages".
 * The server's own prefix is dropped, since every tool in the list carries it.
 */
export function readableToolName(name: string, prefix: string | null): string {
  let rest = name;
  if (prefix !== null) {
    for (const separator of ["-", "_"]) {
      if (rest.toLowerCase().startsWith(`${prefix.toLowerCase()}${separator}`)) {
        rest = rest.slice(prefix.length + 1);
        break;
      }
    }
  }
  const words = rest.replace(/[-_]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * Whether a call to this tool waits for a person: the tool's own approval, else
 * the binding's policy and the server's read-only hint. `approval_needed` in
 * `backend/app/agents/mcp.py` is the rule; this says it the same way.
 */
export function asksFirst(
  tool: McpToolInfo,
  approval: McpApproval,
  toolApproval: McpToolApproval,
): boolean {
  if (Object.hasOwn(toolApproval, tool.name)) return toolApproval[tool.name] === "required";
  return approval === "all" || (approval === "writes" && tool.read_only !== true);
}

/** What a group's select says: one answer for all of its tools, or each their own. */
type GroupApproval = "ask" | "run" | "mixed";

/**
 * Which of a server's tools the agent may call, and which wait for a person -
 * the reads and the changes as two groups, each with its own approval, and
 * every tool with its own beside it.
 *
 * `allowed` null is every tool, which is what a fresh binding means; unticking
 * one narrows to the rest, and ticking the last one back returns to null, so a
 * server that gains a tool later offers it to an agent nobody narrowed.
 *
 * The group selects say the binding's one setting per group, `none` until
 * somebody sets it; `writes` lets reads run and asks before changes. Asking
 * before a read means asking before everything, and letting changes run means
 * letting everything run. Choosing for a group sets every tool in it, so the
 * group's tools lose any setting of their own.
 *
 * A tool set apart from its group is kept in `toolApproval`, and only while it
 * differs: how a server that marks nothing read-only lets its reads run while
 * its writes ask (#2884). A group whose tools differ reads "Per tool", and a
 * tool the server adds later takes its group's setting.
 */
export function McpToolChecklist({
  tools,
  allowed,
  onChange,
  approval,
  toolApproval,
  onApproval,
  prefix,
  disabled,
}: {
  tools: McpToolInfo[];
  allowed: string[] | null;
  onChange: (next: string[] | null) => void;
  approval: McpApproval;
  /** Each tool's own approval, where it has one. */
  toolApproval: McpToolApproval;
  /** One callback for both: choosing for a group changes the two together. */
  onApproval: (approval: McpApproval, toolApproval: McpToolApproval) => void;
  /** The server's catalog key, which its tool names usually start with. */
  prefix: string | null;
  disabled?: boolean;
}) {
  const t = useTranslations("agents");
  const [query, setQuery] = useState("");
  const chosen = new Set(allowed ?? tools.map((tool) => tool.name));
  const needle = query.trim().toLowerCase();
  const matches = (tool: McpToolInfo) =>
    needle === "" ||
    tool.name.toLowerCase().includes(needle) ||
    tool.description.toLowerCase().includes(needle);
  const commit = (next: Set<string>) =>
    onChange(
      next.size === tools.length
        ? null
        : tools.map((tool) => tool.name).filter((name) => next.has(name)),
    );
  const toggle = (names: string[], on: boolean) => {
    const next = new Set(chosen);
    for (const name of names) {
      if (on) next.add(name);
      else next.delete(name);
    }
    commit(next);
  };

  const reads = tools.filter((tool) => tool.read_only === true);
  const writes = tools.filter((tool) => tool.read_only !== true);
  // What the binding's one setting says for each group, before any tool's own.
  const readsAsk = approval === "all";
  const writesAsk = approval !== "none";
  const asks = (tool: McpToolInfo) => asksFirst(tool, approval, toolApproval);
  const summary = (group: McpToolInfo[]): GroupApproval => {
    const asking = group.filter(asks).length;
    return asking === 0 ? "run" : asking === group.length ? "ask" : "mixed";
  };
  /** The tools' own settings, less those `dropped` says to drop. */
  const keeping = (dropped: (name: string) => boolean): McpToolApproval =>
    Object.fromEntries(Object.entries(toolApproval).filter(([name]) => !dropped(name)));
  const inGroup = (group: McpToolInfo[]) => (name: string) =>
    group.some((tool) => tool.name === name);
  const setToolAsks = (tool: McpToolInfo, ask: boolean) => {
    const others = keeping((name) => name === tool.name);
    // Set back to what its group does, the tool follows its group again.
    onApproval(
      approval,
      ask === asksFirst(tool, approval, {})
        ? others
        : { ...others, [tool.name]: ask ? "required" : "never" },
    );
  };

  return (
    <div className="space-y-4">
      {tools.length > SEARCHABLE && (
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
      )}
      {reads.length > 0 && (
        <ToolGroup
          label={t("toolsReads")}
          tools={reads}
          shown={reads.filter(matches)}
          chosen={chosen}
          approval={summary(reads)}
          onAsk={(ask) =>
            onApproval(ask ? "all" : writesAsk ? "writes" : "none", keeping(inGroup(reads)))
          }
          asks={asks}
          onToolAsk={setToolAsks}
          onToggle={toggle}
          prefix={prefix}
          disabled={disabled}
        />
      )}
      <ToolGroup
        // A server that marks nothing read-only is one list of tools, every
        // one of which may change something.
        label={reads.length > 0 ? t("toolsWrites") : t("serverTools")}
        tools={writes}
        shown={writes.filter(matches)}
        chosen={chosen}
        approval={summary(writes)}
        onAsk={(ask) =>
          onApproval(ask ? (readsAsk ? "all" : "writes") : "none", keeping(inGroup(writes)))
        }
        asks={asks}
        onToolAsk={setToolAsks}
        onToggle={toggle}
        prefix={prefix}
        disabled={disabled}
      />
    </div>
  );
}

function ToolGroup({
  label,
  tools,
  shown,
  chosen,
  approval,
  onAsk,
  asks,
  onToolAsk,
  onToggle,
  prefix,
  disabled,
}: {
  label: string;
  tools: McpToolInfo[];
  shown: McpToolInfo[];
  chosen: Set<string>;
  approval: GroupApproval;
  onAsk: (ask: boolean) => void;
  asks: (tool: McpToolInfo) => boolean;
  onToolAsk: (tool: McpToolInfo, ask: boolean) => void;
  onToggle: (names: string[], on: boolean) => void;
  prefix: string | null;
  disabled?: boolean;
}) {
  const t = useTranslations("agents");
  if (tools.length === 0) return null;
  const on = tools.filter((tool) => chosen.has(tool.name)).length;
  const all = on === tools.length;
  return (
    <section className="min-w-0 space-y-1">
      <div className="flex items-center gap-2">
        <Checkbox
          checked={all}
          disabled={disabled}
          onCheckedChange={() =>
            onToggle(
              tools.map((tool) => tool.name),
              !all,
            )
          }
          aria-label={t("toolsGroupAll", { group: label })}
        />
        <h4 className="text-sm font-medium">{label}</h4>
        <span className="text-muted-foreground bg-foreground/[0.05] rounded-full px-1.5 text-[11px] tabular-nums">
          {t("toolsOf", { chosen: on, total: tools.length })}
        </span>
        <Select
          // No value where the tools differ, so the trigger says so; either
          // choice then sets every one of them.
          value={approval === "mixed" ? "" : approval}
          disabled={disabled}
          onValueChange={(next) => onAsk(next === "ask")}
        >
          <SelectTrigger
            icon={ShieldCheck}
            size="sm"
            className="ml-auto w-auto gap-1.5"
            aria-label={t("approvalForGroup", { group: label })}
          >
            <SelectValue placeholder={t("approvalPerTool")} />
          </SelectTrigger>
          <SelectContent align="end">
            <SelectItem value="run">{t("approvalRunFreely")}</SelectItem>
            <SelectItem value="ask">{t("approvalAskFirst")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <ul className="grid gap-x-6 sm:grid-cols-2">
        {shown.map((tool) => (
          <ToolRow
            key={tool.name}
            tool={tool}
            chosen={chosen.has(tool.name)}
            asks={asks(tool)}
            onToggle={(on) => onToggle([tool.name], on)}
            onAsk={(ask) => onToolAsk(tool, ask)}
            prefix={prefix}
            disabled={disabled}
          />
        ))}
      </ul>
    </section>
  );
}

/** One tool: whether the agent may call it, and whether it asks first. */
function ToolRow({
  tool,
  chosen,
  asks,
  onToggle,
  onAsk,
  prefix,
  disabled,
}: {
  tool: McpToolInfo;
  chosen: boolean;
  asks: boolean;
  onToggle: (on: boolean) => void;
  onAsk: (ask: boolean) => void;
  prefix: string | null;
  disabled?: boolean;
}) {
  const t = useTranslations("agents");
  return (
    <li className="border-foreground/[0.06] flex min-w-0 items-center gap-1 border-b">
      <label
        className="hover:bg-foreground/[0.03] flex min-w-0 flex-1 cursor-pointer items-center gap-2.5 rounded-md px-1 py-1.5"
        title={tool.description ? `${tool.name} - ${tool.description}` : tool.name}
      >
        <Checkbox
          checked={chosen}
          disabled={disabled}
          onCheckedChange={(checked) => onToggle(checked === true)}
          aria-label={tool.name}
        />
        <span className="min-w-0 flex-1 truncate text-[13px]">
          {readableToolName(tool.name, prefix)}
        </span>
      </label>
      {/* Beside the label rather than in it, so pressing it is never a tick. */}
      <IconButton
        aria-label={t("approvalForTool", { tool: tool.name })}
        aria-pressed={asks}
        title={asks ? t("approvalAskFirst") : t("approvalRunFreely")}
        disabled={disabled}
        onClick={() => onAsk(!asks)}
        className={asks ? "text-foreground" : "text-muted-foreground/60"}
      >
        {asks ? <ShieldCheck /> : <ShieldOff />}
      </IconButton>
    </li>
  );
}
