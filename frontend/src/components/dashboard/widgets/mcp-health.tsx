"use client";

import { useLocale, useTranslations } from "next-intl";

import { useOrgMcpConnections } from "@/hooks";
import { timeAgo } from "@/lib/utils";
import { StatusList } from "../primitives/status-list";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/**
 * The organization's MCP servers and their last probe. A server that stops
 * answering quietly takes its tools from every agent using it - which is why
 * this sits under "needs attention" rather than on a settings page alone.
 */
export function McpHealthWidget({ title, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.mcp-health");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const { connections, isLoading, error, refresh } = useOrgMcpConnections();

  return (
    <WidgetFrame title={title} seeAll={seeAll}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => void refresh()} />
      ) : connections.length === 0 ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <div className="flex h-full flex-col justify-between gap-2">
          <StatusList
            rows={connections.map((connection) => ({
              label: connection.name,
              sub:
                connection.last_status === "error"
                  ? (connection.last_error ?? undefined)
                  : undefined,
              pill:
                connection.last_status === "error"
                  ? connection.last_checked_at
                    ? t("downSince", { ago: timeAgo(connection.last_checked_at, tTime, locale) })
                    : t("down")
                  : connection.last_checked_at
                    ? t("checked", { ago: timeAgo(connection.last_checked_at, tTime, locale) })
                    : t("unchecked"),
              tone:
                connection.last_status === "error"
                  ? "err"
                  : connection.last_status === "ok"
                    ? "ok"
                    : "neutral",
            }))}
          />
          <p className="text-muted-foreground text-xs">{t("subline")}</p>
        </div>
      )}
    </WidgetFrame>
  );
}
