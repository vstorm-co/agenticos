"use client";

import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { DIALOG_COLUMN } from "@/lib/dialog-sizes";
import type { ChannelBot, ChannelDiagnostics } from "@/types/channels";

export function ChannelDiagnosticsDialog({
  bot,
  onClose,
}: {
  bot: ChannelBot | null;
  onClose: () => void;
}) {
  const t = useTranslations("pages.channels.diagnostics");
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.channelBots.diagnostics(bot?.id ?? ""),
    queryFn: () => apiClient.get<ChannelDiagnostics>(`/channels/bots/${bot?.id}/diagnostics`),
    enabled: bot !== null,
    staleTime: 0,
  });
  return (
    <Dialog
      open={bot !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className={DIALOG_COLUMN}>
        <DialogHeader>
          <DialogTitle>{t("title", { bot: bot?.name ?? "" })}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        {isLoading && (
          <p role="status" className="text-muted-foreground text-sm">
            {t("loading")}
          </p>
        )}
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {t("error")}
          </p>
        )}
        {data && (
          <ul className="space-y-3">
            {data.checks.map((check, index) => (
              <li
                key={`${check.code}-${index}`}
                className="flex items-start justify-between gap-4 text-sm"
              >
                <div>
                  <p>{t(`checks.${check.code}`)}</p>
                  {check.detail && (
                    <p className="text-muted-foreground text-xs break-words">{check.detail}</p>
                  )}
                </div>
                <Badge variant={check.status === "blocked" ? "destructive" : "secondary"}>
                  {t(`states.${check.status}`)}
                </Badge>
              </li>
            ))}
          </ul>
        )}
        <p className="text-muted-foreground text-xs">{t("audience")}</p>
        <Button
          variant="outline"
          onClick={() => void refetch()}
          disabled={isLoading || bot === null}
        >
          {t("refresh")}
        </Button>
      </DialogContent>
    </Dialog>
  );
}
