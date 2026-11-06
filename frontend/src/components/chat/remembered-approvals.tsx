"use client";

import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useToolConsents } from "@/hooks/use-tool-consents";
import { toolLabel } from "@/lib/tool-catalog";

export function RememberedApprovals() {
  const t = useTranslations("chat");
  const tTools = useTranslations("chat.tools");
  const { query, revoke } = useToolConsents();
  if (query.isPending) return null;
  return (
    <div className="space-y-2">
      <p className="text-sm font-medium">{t("approvalRememberedTitle")}</p>
      {query.isError ? (
        <Button size="sm" variant="secondary" onClick={() => void query.refetch()}>
          {t("approvalRememberRetry")}
        </Button>
      ) : null}
      {query.data?.length === 0 && (
        <p className="text-muted-foreground text-xs">{t("approvalRememberedEmpty")}</p>
      )}
      <ul className="max-h-40 scrollbar-thin space-y-2 overflow-y-auto overscroll-contain">
        {query.data?.map((consent) => (
          <li key={consent.id} className="flex items-center gap-3">
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs">
                {consent.agent_name} · {toolLabel(consent.tool_id, tTools)}
              </p>
              <p className="text-muted-foreground text-xs">
                {t(
                  consent.remember_scope === "conversation"
                    ? "approvalRememberChat"
                    : "approvalRememberAgent",
                )}
                {consent.account ? ` · ${consent.account}` : ""}
              </p>
            </div>
            <Button
              size="sm"
              variant="secondary"
              disabled={revoke.isPending}
              onClick={() => revoke.mutate(consent.id)}
            >
              {t("approvalRememberForget")}
            </Button>
          </li>
        ))}
      </ul>
      {revoke.isError && (
        <p role="alert" className="text-destructive text-xs">
          {t("approvalRememberFailed")}
        </p>
      )}
    </div>
  );
}
