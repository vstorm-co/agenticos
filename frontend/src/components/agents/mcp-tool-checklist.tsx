"use client";

import { useState } from "react";
import { Search } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Checkbox,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { McpToolInfo } from "@/lib/mcp-connections-api";
import type { McpApproval } from "@/types/agents";

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
 * Which of a server's tools the agent may call, and which wait for a person -
 * the reads and the changes as two groups, each with its own approval.
 *
 * `allowed` null is every tool, which is what a fresh binding means; unticking
 * one narrows to the rest, and ticking the last one back returns to null, so a
 * server that gains a tool later offers it to an agent nobody narrowed.
 *
 * The approval is the binding's one setting, `writes` by default: reads run,
 * changes ask. The two group selects are its three values said per group -
 * asking before a read means asking before everything, and letting changes
 * run means letting everything run.
 */
export function McpToolChecklist({
  tools,
  allowed,
  onChange,
  approval,
  onApproval,
  prefix,
  disabled,
}: {
  tools: McpToolInfo[];
  allowed: string[] | null;
  onChange: (next: string[] | null) => void;
  approval: McpApproval;
  onApproval: (next: McpApproval) => void;
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
  const readsAsk = approval === "all";
  const writesAsk = approval !== "none";

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
          ask={readsAsk}
          onAsk={(ask) => onApproval(ask ? "all" : writesAsk ? "writes" : "none")}
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
        ask={writesAsk}
        onAsk={(ask) => onApproval(ask ? (readsAsk ? "all" : "writes") : "none")}
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
  ask,
  onAsk,
  onToggle,
  prefix,
  disabled,
}: {
  label: string;
  tools: McpToolInfo[];
  shown: McpToolInfo[];
  chosen: Set<string>;
  ask: boolean;
  onAsk: (ask: boolean) => void;
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
          value={ask ? "ask" : "run"}
          disabled={disabled}
          onValueChange={(next) => onAsk(next === "ask")}
        >
          <SelectTrigger
            size="sm"
            className="ml-auto w-auto gap-1.5"
            aria-label={t("approvalForGroup", { group: label })}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent align="end">
            <SelectItem value="run">{t("approvalRunFreely")}</SelectItem>
            <SelectItem value="ask">{t("approvalAskFirst")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <ul className="grid gap-x-6 sm:grid-cols-2">
        {shown.map((tool) => (
          <li key={tool.name} className="border-foreground/[0.06] min-w-0 border-b">
            <label
              className="hover:bg-foreground/[0.03] flex min-w-0 cursor-pointer items-center gap-2.5 rounded-md px-1 py-1.5"
              title={tool.description ? `${tool.name} - ${tool.description}` : tool.name}
            >
              <Checkbox
                checked={chosen.has(tool.name)}
                disabled={disabled}
                onCheckedChange={(checked) => onToggle([tool.name], checked === true)}
                aria-label={tool.name}
              />
              <span className="min-w-0 flex-1 truncate text-[13px]">
                {readableToolName(tool.name, prefix)}
              </span>
            </label>
          </li>
        ))}
      </ul>
    </section>
  );
}
