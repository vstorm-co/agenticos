"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ShareResourceButton } from "@/components/sharing/share-resource-button";
import { PageHeader } from "@/components/dashboard/page-header";
import { ErrorState, LoadingState } from "@/components/states";
import { Badge, Button, Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui";
import { CopyableValue } from "@/components/workflows/triggers/copyable-value";
import {
  useEventSources,
  useEventSourceUsage,
  useEventSourceWrites,
} from "@/hooks/use-event-sources";
import { usePermissions } from "@/hooks/use-permissions";
import { DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import type { EventSource, EventSourceCreated, SourceCredentials } from "@/lib/event-sources-api";
import { Perm } from "@/types/permissions";
import { SourceCredentialsFields, SourceForm } from "./source-form";

export function SourceManager() {
  const t = useTranslations("eventSources");
  const permissions = usePermissions();
  const { can } = permissions;
  const sources = useEventSources(can(Perm.eventSourcesView));
  const [editing, setEditing] = useState<EventSource | "new" | null>(null);
  const [revealed, setRevealed] = useState<EventSourceCreated | null>(null);
  return (
    <div className="flex flex-1 flex-col space-y-4">
      <div data-tour="event-sources-header">
        <PageHeader
          title={t("title")}
          description={t("description")}
          actions={
            can(Perm.eventSourcesEdit) ? (
              <Button data-tour="event-sources-create" onClick={() => setEditing("new")}>
                {t("createNew")}
              </Button>
            ) : undefined
          }
        />
      </div>
      {permissions.isLoading || sources.isLoading ? (
        <LoadingState variant="pending" />
      ) : permissions.error || sources.error ? (
        <ErrorState
          description={t("loadError")}
          cta={{
            label: t("retry"),
            onClick: () => void (permissions.error ? permissions.refetch() : sources.refetch()),
          }}
        />
      ) : !can(Perm.eventSourcesView) ? (
        <p className="text-muted-foreground">{t("noView")}</p>
      ) : sources.data?.items.length === 0 ? (
        <p className="text-muted-foreground rounded-lg border border-dashed p-8 text-center">
          {t("empty")}
        </p>
      ) : (
        <div className="space-y-3">
          {sources.data?.items.map((source) => (
            <SourceCard key={source.id} source={source} onEdit={() => setEditing(source)} />
          ))}
        </div>
      )}
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
        <DialogContent className={`${DIALOG_FORM} ${DIALOG_COLUMN}`}>
          <DialogHeader>
            <DialogTitle>{t("revealOnce")}</DialogTitle>
          </DialogHeader>
          {revealed && (
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto">
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
              <Button onClick={() => setRevealed(null)}>{t("done")}</Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SourceCard({ source, onEdit }: { source: EventSource; onEdit: () => void }) {
  const t = useTranslations("eventSources");
  const usage = useEventSourceUsage(source.id);
  const writes = useEventSourceWrites();
  const [replacing, setReplacing] = useState(false);
  const [credentials, setCredentials] = useState<SourceCredentials>({});
  const [confirmDelete, setConfirmDelete] = useState(false);
  return (
    <section className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h2 className="font-medium">{source.name}</h2>
          <Badge variant="outline">{t(`providers.${source.provider}`)}</Badge>
          <Badge variant="secondary">
            {source.visibility === "private" ? t("private") : t("organization")}
          </Badge>
          <Badge variant="outline">{source.is_active ? t("active") : t("paused")}</Badge>
        </div>
        {source.can_edit && (
          <div className="flex flex-wrap gap-2">
            <ShareResourceButton
              resourceType="event_source"
              resourceId={source.id}
              name={source.name}
              canManage={source.can_edit}
              compact
            />
            <Button size="sm" variant="outline" onClick={onEdit}>
              {t("edit")}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={writes.update.isPending}
              onClick={() =>
                writes.update.mutate({ id: source.id, input: { is_active: !source.is_active } })
              }
            >
              {source.is_active ? t("pause") : t("resume")}
            </Button>
            <Button size="sm" variant="outline" onClick={() => setReplacing((value) => !value)}>
              {t("replaceCredentials")}
            </Button>
          </div>
        )}
      </div>
      <CopyableValue
        id={`source-url-${source.id}`}
        label={t("liveUrl")}
        value={source.webhook_url}
      />
      <p className="text-muted-foreground text-xs">{t("pauseHelp")}</p>
      {usage.error ? (
        <p role="alert" className="text-destructive text-xs">
          {t("usageError")}
        </p>
      ) : (
        <div className="space-y-1 text-sm">
          <p>{t("usage", { count: usage.data?.total ?? 0 })}</p>
          {usage.data?.items.map((item) => (
            <p key={item.id} className="text-muted-foreground">
              {item.name} · {t(item.kind)} · {item.is_active ? t("active") : t("paused")}
            </p>
          ))}
        </div>
      )}
      {replacing && (
        <div className="space-y-3 rounded-md border p-3">
          <SourceCredentialsFields
            method={source.auth.method}
            value={credentials}
            onChange={setCredentials}
          />
          <Button
            disabled={
              writes.credentials.isPending ||
              (source.auth.method === "basic"
                ? !credentials.username || !credentials.password
                : !credentials.secret)
            }
            onClick={() =>
              writes.credentials.mutate(
                { id: source.id, credentials },
                {
                  onSuccess: () => {
                    setCredentials({});
                    setReplacing(false);
                  },
                },
              )
            }
          >
            {t("replaceCredentials")}
          </Button>
        </div>
      )}
      {source.can_edit && (
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="destructive"
            disabled={!usage.data || usage.data.total > 0 || writes.remove.isPending}
            onClick={() =>
              confirmDelete ? writes.remove.mutate(source.id) : setConfirmDelete(true)
            }
          >
            {confirmDelete ? t("confirmDelete") : t("delete")}
          </Button>
          {!!usage.data?.total && (
            <p className="text-muted-foreground text-xs">{t("deleteBlocked")}</p>
          )}
        </div>
      )}
    </section>
  );
}
