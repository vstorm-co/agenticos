"use client";

import { SourceConsentsPanel } from "@/components/triggers/source-consents-panel";
import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import { useRoutineActions } from "@/hooks/use-routine-actions";
import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Label,
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
  const controlsId = useId();
  const { data, isLoading, error, replace, refetch } = useRoutineActions(
    trigger.agent_id,
    trigger.id,
  );
  const [chosen, setChosen] = useState<{ token: string; keys: Set<string> } | null>(null);
  const selected =
    (chosen?.token === data?.review_token ? chosen?.keys : null) ??
    new Set(data?.items.filter((item) => item.consented).map(identity));
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
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
              {data.items.map((action, index) => (
                <div key={identity(action)} className="flex items-start gap-3">
                  <Checkbox
                    id={`${controlsId}-${index}`}
                    aria-describedby={`${controlsId}-${index}-source`}
                    checked={selected.has(identity(action))}
                    disabled={replace.isPending || !action.waivable || !data.can_waive}
                    onCheckedChange={(checked) => {
                      const next = new Set(selected);
                      if (checked) next.add(identity(action));
                      else next.delete(identity(action));
                      setChosen({ token: data.review_token, keys: next });
                    }}
                  />
                  <div className="min-w-0">
                    <Label className="break-all" htmlFor={`${controlsId}-${index}`}>
                      {action.name}
                    </Label>
                    <p
                      id={`${controlsId}-${index}-source`}
                      className="text-muted-foreground text-xs break-words"
                    >
                      {"capability_id" in action
                        ? action.capability_id
                        : t(
                            action.account_scope === "personal"
                              ? "personalAccount"
                              : "organizationAccount",
                            {
                              name: action.account_name,
                            },
                          )}
                      {!action.waivable && ` · ${t("required")}`}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )
        )}
        <DialogFooter>
          <Button
            variant="outline"
            disabled={!data || replace.isPending}
            onClick={() => replace.mutate([], { onSuccess: onClose })}
          >
            {t("revokeAll")}
          </Button>
          <Button
            disabled={!data || !data.can_waive || replace.isPending || !!error}
            onClick={() =>
              replace.mutate(
                data?.items.filter((item) => selected.has(identity(item))).map(routineActionKey) ??
                  [],
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
