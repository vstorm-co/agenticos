"use client";

import { useLocale, useTranslations } from "next-intl";

import type { AccessAdded } from "@/types/authoring";

/**
 * What a suggestion gives the agent that it could not reach before - a
 * capability, a collection, a context file, MCP tools - each named, and that
 * every tool among them that writes asks for approval. Widened MCP tools keep
 * asking after an Undo, which the line says before anybody accepts.
 */
export function AddsAccess({
  adds,
  names,
}: {
  adds: AccessAdded[];
  /** Names of what the change refers to, by id - only those the reader may see. */
  names: Record<string, string>;
}) {
  const t = useTranslations("authoring.field.access");
  const locale = useLocale();
  const list = new Intl.ListFormat(locale, { type: "conjunction" });
  const name = (id: string) => names[id] ?? id;
  const items = adds.map((item) =>
    item.kind === "mcp_tools"
      ? t("mcpTools", {
          count: item.tools.length,
          tools: list.format(item.tools),
          server: name(item.id),
        })
      : t(item.kind, { name: name(item.id), count: item.tools.length }),
  );
  return (
    <div role="note" className="rounded-md border border-amber-500/40 px-3 py-2 text-xs">
      <p className="font-medium">{t("title", { items: list.format(items) })}</p>
      {adds.some((item) => item.kind === "mcp_tools") && (
        <p className="text-muted-foreground">{t("keeps")}</p>
      )}
    </div>
  );
}
