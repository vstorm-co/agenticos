"use client";

import { useLocale, useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  DataTable,
  type Column,
} from "@/components/ui";
import type { CacheByAgentModel } from "@/types/runs";

/**
 * Where full-price tokens hide: each agent on each model whose cached prompt
 * prefix collapsed over the window (#2109).
 *
 * A *bust* is the start of a request moving while the provider should still
 * have held it - tools in a new order, a timestamp in the instructions - and is
 * billed at the full input rate; an *expiry* had simply outlived the provider's
 * retention. Absent when every cache held, which is the case worth not drawing.
 */
export function CacheBustsCard({ rows }: { rows: readonly CacheByAgentModel[] }) {
  const t = useTranslations("pages.runs.cache");
  const locale = useLocale();
  if (rows.length === 0) return null;
  const number = (value: number) => value.toLocaleString(locale);

  const columns: Column<CacheByAgentModel>[] = [
    {
      key: "agent",
      header: t("agentAndModel"),
      className: "pl-5",
      cell: (row) => (
        <span className="flex items-center gap-2">
          <span aria-hidden>
            <AgentAvatar
              agentId={row.agent_id}
              slug={row.agent_slug}
              size="sm"
              className="h-5 w-5"
            />
          </span>
          <span className="min-w-0">
            <span className="block">{row.agent_name}</span>
            <span className="text-muted-foreground block truncate font-mono text-xs">
              {row.model_label ?? t("noModel")}
            </span>
          </span>
        </span>
      ),
    },
    {
      key: "busts",
      header: t("busts"),
      align: "right",
      cell: (row) => <span className="font-mono text-xs tabular-nums">{number(row.busts)}</span>,
    },
    {
      key: "expiries",
      header: t("expiries"),
      align: "right",
      cell: (row) => (
        <span className="text-muted-foreground font-mono text-xs tabular-nums">
          {number(row.expiries)}
        </span>
      ),
    },
    {
      key: "missed",
      header: t("missedTokens"),
      align: "right",
      className: "pr-5",
      cell: (row) => (
        <span className="font-mono text-xs tabular-nums">{number(row.missed_tokens)}</span>
      ),
    },
  ];

  return (
    <Card>
      <CardHeader className="space-y-1 border-b px-5 py-4">
        <CardTitle className="text-sm">{t("title")}</CardTitle>
        <CardDescription className="text-xs">{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <DataTable<CacheByAgentModel>
          columns={columns}
          rows={[...rows]}
          getRowKey={(row) => `${row.agent_id}:${row.model_label ?? ""}`}
          empty=""
          className="rounded-none border-0 bg-transparent"
        />
      </CardContent>
    </Card>
  );
}
