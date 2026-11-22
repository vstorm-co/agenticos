"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { DiffView } from "@/components/authoring/diff-view";
import { ErrorState, LoadingState } from "@/components/states";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { qk } from "@/lib/query-keys";
import { getErrorMessage } from "@/lib/api-error";
import { applyShippedAgentUpdate, readShippedAgentUpdate } from "@/lib/shipped-agent-api";

export function ShippedUpdateDialog({
  agentId,
  onClose,
}: {
  agentId: string;
  onClose: () => void;
}) {
  const t = useTranslations("pages.agents.shippedUpdate");
  const errors = useTranslations("errors");
  const queryClient = useQueryClient();
  const preview = useQuery({
    queryKey: qk.agents.shippedUpdate(agentId),
    queryFn: () => readShippedAgentUpdate(agentId),
    staleTime: 0,
  });
  const apply = useMutation({
    mutationFn: (revision: string) => applyShippedAgentUpdate(agentId, revision),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: qk.agents.all() }),
        queryClient.invalidateQueries({ queryKey: qk.environments.list(agentId) }),
      ]);
      onClose();
    },
  });
  const update = preview.data;
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !apply.isPending) onClose();
      }}
    >
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t("review")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        {preview.isPending ? (
          <LoadingState variant="skeleton-list" rows={2} />
        ) : preview.isError ? (
          <ErrorState title={getErrorMessage(preview.error, errors)} />
        ) : update?.changes.length ? (
          <div className="max-h-[55dvh] space-y-4 overflow-y-auto">
            {update.changes.map((change) => (
              <section key={`${change.version}:${change.field}`} className="space-y-2">
                <h3 className="text-sm font-medium">
                  {t(change.version)} · {change.field}
                </h3>
                <DiffView before={change.before} after={change.after} />
              </section>
            ))}
          </div>
        ) : (
          <p className="text-muted-foreground text-sm">{t("current")}</p>
        )}
        {apply.error && (
          <p role="alert" className="text-destructive text-sm">
            {getErrorMessage(apply.error, errors)}
          </p>
        )}
        <DialogFooter>
          {apply.error && (
            <Button
              variant="outline"
              onClick={() => {
                apply.reset();
                void preview.refetch();
              }}
            >
              {t("reload")}
            </Button>
          )}
          {update && update.changes.length > 0 && (
            <Button
              disabled={preview.isFetching || apply.isPending || apply.isError}
              onClick={() => apply.mutate(update.revision)}
            >
              {t("apply")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
