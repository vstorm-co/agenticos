"use client";

import { ActionSelection } from "./action-selection";
import { DIALOG_COLUMN, DIALOG_WIDE } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { SourceConsentsPanel } from "@/components/triggers/source-consents-panel";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { useRoutineActions } from "@/hooks/use-routine-actions";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Spinner,
} from "@/components/ui";
import { ErrorState } from "@/components/states/error-state";
import type { Trigger } from "@/types/triggers";
import { routineActionIdentity as identity, routineActionKey } from "@/lib/routine-actions-api";

export function ActionConsentsDialog({
  trigger,
  onClose,
}: {
  trigger: Trigger;
  onClose: () => void;
}) {
  const t = useTranslations("triggers.actionConsents");
  const { data, isLoading, error, replace, refetch } = useRoutineActions(
    trigger.agent_id,
    trigger.id,
  );
  const [chosen, setChosen] = useState<{ token: string; keys: Set<string> } | null>(null);
  const selected =
    (chosen?.token === data?.review_token ? chosen?.keys : null) ??
    new Set(data?.items.filter((item) => item.consented && item.waivable).map(identity));
  const maxActions = data?.max_actions ?? 100;
  const overLimit = selected.size > maxActions;
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className={cn(DIALOG_WIDE, DIALOG_COLUMN)}>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
          <SourceConsentsPanel trigger={trigger} />
          {isLoading ? (
            <Spinner />
          ) : error ? (
            <ErrorState cta={{ label: t("retry"), onClick: () => void refetch() }} />
          ) : (
            data && (
              <div className="space-y-4">
                {!data.can_waive && (
                  <p className="text-muted-foreground text-sm">{t("notAllowed")}</p>
                )}
                {!!data.unavailable_sources?.length && (
                  <p className="text-muted-foreground text-sm">
                    {t("checkConnections", { names: data.unavailable_sources.join(", ") })}
                  </p>
                )}
                {data.items.length === 0 && (
                  <p className="text-muted-foreground text-sm">{t("empty")}</p>
                )}
                {data.review_changes?.map((change) => (
                  <p key={change} role="status" className="text-sm">
                    {t(`changed.${change}`)}
                  </p>
                ))}
                {data.items.some(
                  (item) => item.previously_consented && !item.consented && item.waivable,
                ) && (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={replace.isPending || !data.can_waive}
                    onClick={() =>
                      setChosen({
                        token: data.review_token,
                        keys: new Set([
                          ...selected,
                          ...data.items
                            .filter((item) => item.previously_consented && item.waivable)
                            .map(identity),
                        ]),
                      })
                    }
                  >
                    {t("reselectPrevious")}
                  </Button>
                )}
                <p role={overLimit ? "alert" : "status"} className="text-sm">
                  {t(overLimit ? "tooMany" : "selected", {
                    count: selected.size,
                    limit: maxActions,
                  })}
                </p>
                <ActionSelection
                  items={data.items}
                  selected={selected}
                  disabled={replace.isPending || !data.can_waive}
                  onChange={(keys) => setChosen({ token: data.review_token, keys })}
                />
              </div>
            )
          )}
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            disabled={!data || replace.isPending}
            onClick={() => replace.mutate([], { onSuccess: onClose })}
          >
            {t("revokeAll")}
          </Button>
          <Button
            disabled={!data || !data.can_waive || replace.isPending || !!error || overLimit}
            onClick={() =>
              replace.mutate(
                data?.items
                  .filter((item) => item.waivable && selected.has(identity(item)))
                  .map(routineActionKey) ?? [],
                {
                  onSuccess: onClose,
                },
              )
            }
          >
            {t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
