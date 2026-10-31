"use client";

import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui";
import { usePortalPollInterval } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { POLL_INTERVAL_MINUTES } from "@/lib/org-mcp-connections-api";
import type { PortalCatalogEntry } from "@/types/portals";

/** The portals whose connected account is a mailbox the platform checks for new mail. */
const MAILBOX_PORTALS = new Set(["google", "microsoft"]);

/**
 * How often the organization's connected mailbox is checked for new mail.
 *
 * One setting for the mailbox, not for the trigger it is shown on: a single read
 * serves every trigger and workflow listening there, so the copy says so. Shown
 * only for a connected Gmail or Outlook mailbox; changing it needs `mcp:manage`,
 * as connecting the mailbox does (`canManage`), and without it the current value is just read.
 */
export function MailboxInterval({
  portal,
  canManage,
}: {
  portal: PortalCatalogEntry;
  /** Whether the caller holds `mcp:manage`, which changing the setting needs. */
  canManage: boolean;
}) {
  const t = useTranslations("portals.mailboxInterval");
  const tErrors = useTranslations("errors");
  const save = usePortalPollInterval();
  const minutes = portal.poll_interval_minutes;
  if (
    !MAILBOX_PORTALS.has(portal.key) ||
    portal.connection_id === null ||
    portal.connection_state !== "connected" ||
    minutes === null
  ) {
    return null;
  }
  const connectionId = portal.connection_id;

  const change = async (next: string) => {
    try {
      await save.mutateAsync({ connectionId, minutes: Number(next) });
      toast.success(t("saved"));
    } catch (caught) {
      toast.error(getErrorMessage(caught, tErrors, t("saveError")));
    }
  };

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-2">
        <span id={`mailbox-interval-${portal.key}`} className="text-xs font-medium">
          {t("label")}
        </span>
        {canManage ? (
          <Select value={String(minutes)} onValueChange={(next) => void change(next)}>
            <SelectTrigger
              className="h-8 w-auto min-w-28"
              aria-labelledby={`mailbox-interval-${portal.key}`}
              disabled={save.isPending}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {POLL_INTERVAL_MINUTES.map((option) => (
                <SelectItem key={option} value={String(option)}>
                  {t("option", { count: option })}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <span className="text-xs">{t("option", { count: minutes })}</span>
        )}
      </div>
      <p className="text-muted-foreground text-xs">{t("shared")}</p>
    </div>
  );
}
