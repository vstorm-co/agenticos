"use client";

import { useState } from "react";
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
import type { RoutineActionOption } from "@/lib/routine-actions-api";

const identity = (action: RoutineActionOption) => `${action.capability_id}:${action.tool_id}`;

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
    new Set(data?.items.filter((item) => item.consented).map(identity));
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
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
              {data.items.length === 0 && (
                <p className="text-muted-foreground text-sm">{t("empty")}</p>
              )}
              {data.items.map((action) => (
                <div key={identity(action)} className="flex items-start gap-3">
                  <Checkbox
                    id={identity(action)}
                    checked={selected.has(identity(action))}
                    disabled={
                      replace.isPending ||
                      !action.waivable ||
                      (!data.can_waive && !selected.has(identity(action)))
                    }
                    onCheckedChange={(checked) => {
                      const next = new Set(selected);
                      if (checked) next.add(identity(action));
                      else next.delete(identity(action));
                      setChosen({ token: data.review_token, keys: next });
                    }}
                  />
                  <div>
                    <Label htmlFor={identity(action)}>{action.name}</Label>
                    <p className="text-muted-foreground text-xs">
                      {action.capability_id}
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
            disabled={!data || replace.isPending || !!error}
            onClick={() =>
              replace.mutate(
                data?.items
                  .filter((item) => selected.has(identity(item)))
                  .map(({ capability_id, tool_id }) => ({ capability_id, tool_id })) ?? [],
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
