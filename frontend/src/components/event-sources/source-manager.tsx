"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Plus, Webhook } from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { ErrorState } from "@/components/states";
import {
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  ListCardEmpty,
} from "@/components/ui";
import { CopyableValue } from "@/components/workflows/triggers/copyable-value";
import { useEventSources } from "@/hooks/use-event-sources";
import { usePermissions } from "@/hooks/use-permissions";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import type { EventSource, EventSourceCreated } from "@/lib/event-sources-api";
import { cn } from "@/lib/utils";
import { Perm } from "@/types/permissions";
import { SourceForm } from "./source-form";
import { SourceTable } from "./source-table";

export function SourceManager() {
  const t = useTranslations("eventSources");
  const permissions = usePermissions();
  const { can } = permissions;
  const canView = can(Perm.eventSourcesView);
  const sources = useEventSources(canView);
  const loadError = permissions.error || sources.error;
  const [editing, setEditing] = useState<EventSource | "new" | null>(null);
  const [revealed, setRevealed] = useState<EventSourceCreated | null>(null);
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-4">
      <div data-tour="event-sources-header">
        <PageHeader
          title={t("title")}
          description={t("description")}
          actions={
            can(Perm.eventSourcesEdit) ? (
              <Button data-tour="event-sources-create" onClick={() => setEditing("new")}>
                <Plus className="size-4" aria-hidden />
                {t("createNew")}
              </Button>
            ) : undefined
          }
        />
      </div>
      <SourceTable
        rows={canView ? sources.data?.items : []}
        loading={permissions.isLoading || sources.isLoading}
        onEdit={setEditing}
        error={
          loadError ? (
            <ErrorState
              description={t("loadError")}
              cta={{
                label: t("retry"),
                onClick: () => void (permissions.error ? permissions.refetch() : sources.refetch()),
              }}
              className="m-4"
            />
          ) : null
        }
        empty={<ListCardEmpty icon={Webhook} title={t(canView ? "empty" : "noView")} />}
      />
      {editing && (
        <SourceForm
          key={editing === "new" ? "new" : editing.id}
          source={editing === "new" ? undefined : editing}
          onCancel={() => setEditing(null)}
          onSaved={(source) => {
            setEditing(null);
            if (source.reveal_secret) setRevealed(source);
          }}
        />
      )}
      <Dialog
        open={revealed !== null}
        onOpenChange={(open) => {
          if (!open) setRevealed(null);
        }}
      >
        <DialogContent className={cn(DIALOG_FORM, DIALOG_COLUMN)}>
          <DialogHeader>
            <DialogTitle>{t("revealOnce")}</DialogTitle>
          </DialogHeader>
          {revealed && (
            <div className={cn(DIALOG_BODY, "space-y-3")}>
              <CopyableValue
                id="created-source-url"
                label={t("liveUrl")}
                value={revealed.webhook_url}
              />
              <CopyableValue
                id="created-source-secret"
                label={t("secret")}
                value={revealed.reveal_secret ?? ""}
              />
            </div>
          )}
          <DialogFooter>
            <Button onClick={() => setRevealed(null)}>{t("done")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
