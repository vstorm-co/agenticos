"use client";

import { Ellipsis, KeyRound, Pause, Pencil, Play, Radio, Trash2, Webhook } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";
import { CopyButton } from "@/components/chat/copy-button";
import { ShareResourceButton } from "@/components/sharing/share-resource-button";
import {
  Badge,
  Button,
  ConfirmDialog,
  DataTable,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Skeleton,
  type Column,
} from "@/components/ui";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { useEventSourceUsage, useEventSourceWrites } from "@/hooks/use-event-sources";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_CONFIRM, DIALOG_FORM } from "@/lib/dialog-sizes";
import type { EventSource, SourceCredentials } from "@/lib/event-sources-api";
import { cn } from "@/lib/utils";
import { SourceCredentialsFields } from "./source-form";
import { LiveSample } from "./live-sample";

export function SourceTable({
  rows,
  loading,
  empty,
  error,
  onEdit,
}: {
  rows: EventSource[] | undefined;
  loading: boolean;
  empty: ReactNode;
  error: ReactNode;
  onEdit: (source: EventSource) => void;
}) {
  const t = useTranslations("eventSources");
  const workflows = useTranslations("pages.workflows");
  const columns: Column<EventSource>[] = [
    {
      key: "name",
      header: t("name"),
      className: "w-[23%] @max-md/table:w-full",
      cell: (source) => (
        <div className="flex min-w-0 items-center gap-3">
          {source.provider === "webhook" ? (
            <Webhook className="text-muted-foreground size-5 shrink-0" aria-hidden />
          ) : (
            <ProviderIcon provider={source.provider} brand={source.provider} />
          )}
          <div className="min-w-0">
            <h2 className="truncate font-medium" title={source.name}>
              {source.name}
            </h2>
            <p className="text-muted-foreground text-xs">{t(`providers.${source.provider}`)}</p>
          </div>
        </div>
      ),
    },
    {
      key: "status",
      header: t("status"),
      className: "@md/table:w-[12%]",
      cell: (source) => (
        <Badge variant={source.is_active ? "success" : "secondary"}>
          {t(source.is_active ? "active" : "paused")}
        </Badge>
      ),
    },
    {
      key: "visibility",
      header: t("visibility"),
      className: "@md/table:w-[15%]",
      cell: (source) => (
        <Badge variant={source.visibility === "private" ? "outline" : "secondary"}>
          {t(source.visibility === "private" ? "private" : "organization")}
        </Badge>
      ),
    },
    {
      key: "endpoint",
      header: t("liveUrl"),
      className: "@md/table:w-[24%] @max-md/table:w-full",
      cell: (source) => (
        <div className="flex min-w-0 items-center gap-1">
          <code
            className="text-muted-foreground min-w-0 truncate text-xs"
            title={source.webhook_url}
          >
            {source.webhook_url}
          </code>
          <CopyButton
            text={source.webhook_url}
            label={workflows("copyNamed", { name: t("liveUrl") })}
            className="shrink-0 opacity-100"
          />
        </div>
      ),
    },
    {
      key: "subscribers",
      header: t("subscribers"),
      className: "@max-md/table:w-full",
      cell: (source) => <SourceSubscribers source={source} />,
    },
    {
      key: "actions",
      header: <span className="sr-only">{t("actions")}</span>,
      align: "right",
      className: "px-2 sm:px-2 @md/table:w-40 @max-md/table:w-full",
      cell: (source) => (
        <div className="flex items-center justify-end gap-1">
          {source.can_use && (
            <Dialog>
              <DialogTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t("listenTo", { name: source.name })}
                  title={t("listen")}
                >
                  <Radio className="size-4" aria-hidden />
                </Button>
              </DialogTrigger>
              <DialogContent className={cn(DIALOG_FORM, DIALOG_COLUMN)}>
                <DialogHeader>
                  <DialogTitle>{t("listenTo", { name: source.name })}</DialogTitle>
                </DialogHeader>
                <div className={DIALOG_BODY}>
                  <LiveSample sourceId={source.id} />
                </div>
              </DialogContent>
            </Dialog>
          )}
          {source.can_edit && <SourceActions source={source} onEdit={() => onEdit(source)} />}
        </div>
      ),
    },
  ];
  return (
    <DataTable
      columns={columns}
      rows={rows}
      loading={loading}
      getRowKey={(source) => source.id}
      empty={empty}
      error={error}
      className="@md/table:[&_table]:table-fixed"
      stackOnNarrow
    />
  );
}

function SourceSubscribers({ source }: { source: EventSource }) {
  const t = useTranslations("eventSources");
  const usage = useEventSourceUsage(source.id);
  if (usage.error) return <p className="text-destructive-ink text-xs">{t("usageError")}</p>;
  if (!usage.data) return <Skeleton className="h-4 w-20" />;
  return (
    <div className="text-muted-foreground space-y-1 text-xs">
      <p>{t("usage", { count: usage.data.total })}</p>
      {usage.data.items.map((item) => (
        <p key={item.id} className="wrap-break-word">
          {item.name} · {t(item.kind)}
          {item.is_active !== null && <> · {t(item.is_active ? "active" : "paused")}</>}
        </p>
      ))}
    </div>
  );
}

function SourceActions({ source, onEdit }: { source: EventSource; onEdit: () => void }) {
  const t = useTranslations("eventSources");
  const common = useTranslations("common");
  const usage = useEventSourceUsage(source.id);
  const writes = useEventSourceWrites();
  const [replacing, setReplacing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const hasSubscribers = !!usage.data?.total;

  return (
    <div className="flex items-center justify-end gap-1">
      <ShareResourceButton
        resourceType="event_source"
        resourceId={source.id}
        name={source.name}
        canManage
        compact
        className="size-8 border-transparent bg-transparent p-0 [&>span]:sr-only"
      />
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={common("editNamed", { name: source.name })}
        title={t("edit")}
        onClick={onEdit}
      >
        <Pencil className="size-4" aria-hidden />
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={common("resourceActions", { name: source.name })}
          >
            <Ellipsis className="size-4" aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            disabled={writes.update.isPending}
            title={source.is_active ? t("pauseHelp") : undefined}
            onSelect={() =>
              writes.update.mutate({ id: source.id, input: { is_active: !source.is_active } })
            }
          >
            {source.is_active ? <Pause className="size-4" /> : <Play className="size-4" />}
            {t(source.is_active ? "pause" : "resume")}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setReplacing(true)}>
            <KeyRound className="size-4" />
            {t("replaceCredentials")}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            className="text-destructive focus:text-destructive"
            disabled={!usage.data || hasSubscribers || writes.remove.isPending}
            onSelect={() => setDeleting(true)}
          >
            <Trash2 className="size-4" />
            {t("delete")}
          </DropdownMenuItem>
          {hasSubscribers && (
            <p className="text-muted-foreground max-w-56 px-2 pb-1 text-xs">{t("deleteBlocked")}</p>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      {replacing && (
        <ReplaceCredentialsDialog source={source} onClose={() => setReplacing(false)} />
      )}
      {deleting && (
        <ConfirmDialog
          open
          onOpenChange={setDeleting}
          title={common("deleteNamedConfirm", { name: source.name })}
          confirmLabel={t("confirmDelete")}
          destructive
          loading={writes.remove.isPending}
          onConfirm={() => writes.remove.mutate(source.id, { onSuccess: () => setDeleting(false) })}
        />
      )}
    </div>
  );
}

function ReplaceCredentialsDialog({
  source,
  onClose,
}: {
  source: EventSource;
  onClose: () => void;
}) {
  const t = useTranslations("eventSources");
  const { credentials: replacement } = useEventSourceWrites();
  const [credentials, setCredentials] = useState<SourceCredentials>({});
  const method = source.auth.method;
  const ready =
    method === "basic" ? !!credentials.username && !!credentials.password : !!credentials.secret;
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        className={cn(DIALOG_CONFIRM, DIALOG_COLUMN)}
        dismissible={!replacement.isPending}
      >
        <DialogHeader>
          <DialogTitle>{t("replaceCredentials")}</DialogTitle>
          <DialogDescription>{source.name}</DialogDescription>
        </DialogHeader>
        <div className={DIALOG_BODY}>
          <fieldset disabled={replacement.isPending}>
            <SourceCredentialsFields
              method={method}
              value={credentials}
              onChange={setCredentials}
            />
          </fieldset>
        </div>
        <DialogFooter>
          <Button variant="outline" disabled={replacement.isPending} onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button
            disabled={!ready || replacement.isPending}
            loading={replacement.isPending}
            onClick={() =>
              replacement.mutate({ id: source.id, credentials }, { onSuccess: onClose })
            }
          >
            {t("replaceCredentials")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
