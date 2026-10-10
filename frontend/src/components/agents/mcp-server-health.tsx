"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";
import { cn, timeAgo } from "@/lib/utils";

/**
 * Whether a bound server is answering, on its card in the Builder (#2072).
 *
 * A server that stops answering takes its tools from the agent without a word,
 * and the Builder is where somebody is deciding to rely on it. The last probe,
 * when it ran, what it said, and - for whoever may - a way to probe it again.
 */
export function McpServerHealth({
  connection,
  onCheck,
}: {
  connection: OrgMcpConnectionRecord;
  /** Probe it now; absent for somebody who may not manage MCP servers. */
  onCheck?: (connectionId: string) => Promise<unknown>;
}) {
  const t = useTranslations("agents");
  const tErrors = useTranslations("errors");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const [checking, setChecking] = useState(false);
  const down = connection.last_status === "error";
  const ago = connection.last_checked_at
    ? timeAgo(connection.last_checked_at, tTime, locale)
    : null;

  const check = async (probe: (connectionId: string) => Promise<unknown>) => {
    setChecking(true);
    try {
      await probe(connection.id);
    } catch (failure) {
      toast.error(getErrorMessage(failure, tErrors));
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="mt-3 flex items-start gap-2 pl-7 text-xs">
      <span
        aria-hidden
        className={cn(
          "mt-1 h-2 w-2 shrink-0 rounded-full",
          down ? "bg-destructive" : ago ? "bg-emerald-500" : "bg-muted-foreground/40",
        )}
      />
      <span className="min-w-0 flex-1">
        <span className={cn(down ? "text-destructive" : "text-muted-foreground")}>
          {down
            ? ago
              ? t("mcpHealthDownSince", { ago })
              : t("mcpHealthDown")
            : ago
              ? t("mcpHealthChecked", { ago })
              : t("mcpHealthUnchecked")}
        </span>
        {down && connection.last_error && (
          <span className="text-muted-foreground block truncate" title={connection.last_error}>
            {connection.last_error}
          </span>
        )}
      </span>
      {onCheck && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-6 px-2 text-xs"
          disabled={checking}
          onClick={() => void check(onCheck)}
        >
          <RefreshCw className={cn("mr-1 h-3 w-3", checking && "animate-spin")} />
          {t("mcpHealthCheck")}
        </Button>
      )}
    </div>
  );
}
