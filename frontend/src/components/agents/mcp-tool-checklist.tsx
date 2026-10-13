"use client";

import { useState } from "react";
import { Search } from "lucide-react";
import { useTranslations } from "next-intl";

import { Checkbox, Input } from "@/components/ui";
import type { McpToolInfo } from "@/lib/mcp-connections-api";

/** Past this many tools the list gets a search box. */
const SEARCHABLE = 8;

/**
 * Which of a server's tools the agent may call, ticked in place.
 *
 * `allowed` null is every tool, which is what a fresh binding means; unticking one
 * narrows to the rest, and ticking the last one back returns to null, so a server
 * that gains a tool later offers it to an agent nobody narrowed.
 */
export function McpToolChecklist({
  tools,
  allowed,
  onChange,
  disabled,
}: {
  tools: McpToolInfo[];
  allowed: string[] | null;
  onChange: (next: string[] | null) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("agents");
  const [query, setQuery] = useState("");
  const chosen = new Set(allowed ?? tools.map((tool) => tool.name));
  const needle = query.trim().toLowerCase();
  const shown =
    needle === ""
      ? tools
      : tools.filter(
          (tool) =>
            tool.name.toLowerCase().includes(needle) ||
            tool.description.toLowerCase().includes(needle),
        );
  const commit = (next: Set<string>) =>
    onChange(
      next.size === tools.length
        ? null
        : tools.map((tool) => tool.name).filter((name) => next.has(name)),
    );
  const toggle = (name: string, on: boolean) => {
    const next = new Set(chosen);
    if (on) next.add(name);
    else next.delete(name);
    commit(next);
  };
  const everything = chosen.size === tools.length;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground text-xs tabular-nums">
          {t("toolsChosen", { chosen: chosen.size, total: tools.length })}
        </span>
        <button
          type="button"
          disabled={disabled}
          onClick={() => commit(everything ? new Set() : new Set(tools.map((tool) => tool.name)))}
          className="text-muted-foreground hover:text-foreground ml-auto text-xs underline-offset-2 hover:underline disabled:opacity-50"
        >
          {everything ? t("toolsNone") : t("toolsAll")}
        </button>
      </div>
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
      <ul className="border-foreground/10 divide-foreground/[0.06] max-h-60 divide-y overflow-y-auto rounded-xl border">
        {shown.map((tool) => (
          <li key={tool.name}>
            <label className="hover:bg-foreground/[0.03] flex cursor-pointer items-start gap-2.5 px-3 py-2">
              <Checkbox
                checked={chosen.has(tool.name)}
                disabled={disabled}
                onCheckedChange={(on) => toggle(tool.name, on === true)}
                className="mt-0.5"
                aria-label={tool.name}
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-mono text-xs">{tool.name}</span>
                {tool.description && (
                  <span className="text-muted-foreground block truncate text-xs">
                    {tool.description}
                  </span>
                )}
              </span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}
