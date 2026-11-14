"use client";

import { useState } from "react";
import { Copy, Plug, Plus, Server, Trash2 } from "lucide-react";

import { LocalServiceIcon } from "@/components/kb/local-service-icon";
import { LocalServiceDialog } from "@/components/kb/local-service-dialog";
import { LocalServiceRemove } from "@/components/kb/local-services";
import type { LocalServiceRecord } from "@/lib/local-services-api";
import { ConnectorIcon } from "@/components/rag/connector-icon";
import { ErrorState } from "@/components/states";
import { SyncSourceWizard } from "@/components/rag/sync-source-wizard";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
  DataTable,
  ListCard,
  type Column,
  Button,
  ListCardEmpty,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Spinner,
} from "@/components/ui";
import { useLocalServices, usePermissions, useReusableIntegrations } from "@/hooks";
import { useOrgStore } from "@/stores";
import type { SyncSourceCreate, SyncSourceRead } from "@/lib/rag-api";
import type { KnowledgeBase } from "@/types";
import { Perm } from "@/types/permissions";
import { useChanged } from "@/hooks/use-changed";
import { useTranslations } from "next-intl";
import { DIALOG_FORM } from "@/lib/dialog-sizes";

interface KnowledgeIntegrationsProps {
  /** Collections an integration can be cloned into - the page's own list. */
  targets: KnowledgeBase[];
}

/**
 * Connectors configured once and cloned into collections as they are needed.
 *
 * This sits on the collection *list* rather than on any one collection because
 * that is what it is for: an integration with no `collection_name` is the thing
 * several collections are fed from, and it has no single page of its own to
 * live on. Using one is still done from the collection that wants it - the
 * wizard on `/kb/{id}` offers the same rows under "Use existing" - so what is
 * here is only what that moment cannot do: making one, seeing the ones nobody
 * has used yet, and throwing one away.
 *
 * Hidden without `connections:manage` - the permission the endpoints behind it
 * gate on, so this mirrors the server instead of hardcoding a role list that
 * would go stale the moment a role is reshaped. A caller without it would see
 * a section that could only fail; the collections they may feed are on their
 * own pages regardless.
 */
export function KnowledgeIntegrations({ targets }: KnowledgeIntegrationsProps) {
  const t = useTranslations("kb");
  const { can, isAppAdmin } = usePermissions();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const mayManage = can(Perm.connectionsManage);

  const { integrations, connectors, isLoading, error, create, remove, cloneInto } =
    useReusableIntegrations(mayManage ? activeOrgId : null);

  const local = useLocalServices(mayManage);
  const [addingServer, setAddingServer] = useState(false);

  const [wizardOpen, setWizardOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [cloning, setCloning] = useState<SyncSourceRead | null>(null);

  if (!mayManage) return null;

  // A refusal is left to travel: the wizard is what marks the field the server
  // named and goes back to the step holding it.
  const handleCreate = async (data: SyncSourceCreate) => {
    setSubmitting(true);
    try {
      await create(data);
      setWizardOpen(false);
    } finally {
      setSubmitting(false);
    }
  };

  type Row =
    { kind: "source"; source: SyncSourceRead } | { kind: "service"; service: LocalServiceRecord };
  const rows: Row[] = [
    ...integrations.map((source): Row => ({ kind: "source", source })),
    ...local.services.map((service): Row => ({ kind: "service", service })),
  ];
  const columns: Column<Row>[] = [
    {
      key: "name",
      header: t("name"),
      cell: (row) => (
        <div className="flex min-w-0 items-center gap-3">
          {row.kind === "source" ? (
            <ConnectorIcon type={row.source.connector_type} size="sm" />
          ) : (
            <span className="bg-muted text-muted-foreground grid size-8 shrink-0 place-items-center rounded-lg">
              <LocalServiceIcon kind={row.service.kind} className="size-4" />
            </span>
          )}
          <span className="min-w-0 font-medium break-words">
            {row.kind === "source"
              ? row.source.name
              : row.service.organization_id === null
                ? t("deploymentWideNamed", { name: row.service.name })
                : row.service.name}
          </span>
        </div>
      ),
    },
    {
      key: "kind",
      header: t("localServiceKind"),
      cell: (row) =>
        row.kind === "source"
          ? (connectors.find((entry) => entry.type === row.source.connector_type)?.name ??
            row.source.connector_type)
          : t(row.service.kind === "embedding" ? "embeddingServer" : "ocrServer"),
    },
    {
      key: "details",
      header: t("integrationDetails"),
      cell: (row) => (
        <span className="text-muted-foreground break-all">
          {row.kind === "source"
            ? row.source.schedule_minutes
              ? t("everyMinutes", { minutes: row.source.schedule_minutes })
              : t("manualSchedule")
            : row.service.base_url}
        </span>
      ),
    },
    {
      key: "actions",
      header: t("integrationActions"),
      align: "right",
      className: "sm:w-px sm:whitespace-nowrap",
      cell: (row) =>
        row.kind === "source" ? (
          <IntegrationActions
            source={row.source}
            canClone={targets.length > 0}
            onClone={() => setCloning(row.source)}
            onDelete={() => remove(row.source.id)}
          />
        ) : (
          <LocalServiceRemove
            service={row.service}
            canRemove={row.service.organization_id !== null || isAppAdmin}
            onDelete={() => local.remove(row.service.id)}
          />
        ),
    },
  ];

  return (
    <ListCard
      title={t("reusableIntegrations")}
      counted={
        isLoading || local.isLoading
          ? null
          : error || local.error
            ? t("integrationsDescription")
            : t("integrationsCount", { count: rows.length })
      }
      fill
      contentClassName="flex min-h-0 flex-1 flex-col p-0"
      controls={
        <div className="flex flex-wrap items-center gap-2">
          <span data-tour="knowledge-local-services">
            <Button
              data-tour="knowledge-add-local-service"
              variant="outline"
              size="sm"
              onClick={() => setAddingServer(true)}
            >
              <Server className="size-4" aria-hidden />
              {t("addServer")}
            </Button>
          </span>
          {connectors.length > 0 && (
            <Button
              data-tour="knowledge-add-integration"
              size="sm"
              onClick={() => setWizardOpen(true)}
            >
              <Plus className="size-4" aria-hidden />
              {t("addIntegration")}
            </Button>
          )}
        </div>
      }
    >
      <p className="text-muted-foreground border-b px-4 py-3 text-xs leading-relaxed sm:px-5">
        {t("integrationsDescription")}
      </p>
      {error && <ErrorState description={error} className="m-4 border-0 py-4" />}
      {local.error && <ErrorState description={local.error} className="m-4 border-0 py-4" />}
      <DataTable
        columns={columns}
        rows={rows}
        getRowKey={(row) =>
          row.kind === "source" ? `source:${row.source.id}` : `service:${row.service.id}`
        }
        loading={isLoading || local.isLoading}
        stackOnNarrow
        fillHeight
        className="rounded-t-none rounded-b-xl border-0"
        empty={
          error || local.error ? (
            <></>
          ) : (
            <ListCardEmpty
              icon={Plug}
              title={t("integrationsEmpty")}
              description={t(connectors.length > 0 ? "nothingHereYetAdd" : "noConnectorsAvailable")}
            />
          )
        }
      />
      <LocalServiceDialog
        open={addingServer}
        onOpenChange={setAddingServer}
        canRegisterDeploymentWide={isAppAdmin}
        onSubmit={local.create}
      />
      <SyncSourceWizard
        open={wizardOpen}
        onOpenChange={setWizardOpen}
        connectors={connectors}
        // No collections offered: picking one here would file the integration
        // under a single knowledge base, which is the one thing this list is
        // not for.
        collections={[]}
        onSubmit={handleCreate}
        submitting={submitting}
      />

      <CloneIntoDialog
        source={cloning}
        targets={targets}
        onOpenChange={(open) => !open && setCloning(null)}
        onClone={cloneInto}
      />
    </ListCard>
  );
}

function IntegrationActions({
  source,
  canClone,
  onClone,
  onDelete,
}: {
  source: SyncSourceRead;
  canClone: boolean;
  onClone: () => void;
  onDelete: () => void;
}) {
  const t = useTranslations("kb");
  const tc = useTranslations("common");
  return (
    <div className="flex shrink-0 items-center justify-end gap-2">
      <Button
        className="shrink-0 whitespace-nowrap"
        variant="outline"
        size="sm"
        onClick={onClone}
        disabled={!canClone}
      >
        <Copy className="h-3.5 w-3.5" />
        {t("use")}
      </Button>
      <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground hover:text-destructive h-8 w-8 p-0"
            aria-label={tc("removeNamed", { name: source.name })}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("removeNamed", { name: source.name })}</AlertDialogTitle>
            <AlertDialogDescription>{t("knowledgeBasesAlreadyUsing")}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={onDelete}
            >
              {t("remove")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function CloneIntoDialog({
  source,
  targets,
  onOpenChange,
  onClone,
}: {
  source: SyncSourceRead | null;
  targets: KnowledgeBase[];
  onOpenChange: (open: boolean) => void;
  onClone: (sourceId: string, target: KnowledgeBase, name: string) => Promise<void>;
}) {
  const t = useTranslations("kb");
  const [targetId, setTargetId] = useState("");
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // A different source is a different form. Cleared during render, so the
  // previous source's answers are never shown against the new one.
  if (useChanged(source)) {
    setTargetId("");
    setName("");
  }

  if (!source) return null;

  const target = targets.find((kb) => kb.id === targetId);

  const handleSubmit = async () => {
    if (!target) return;
    setSubmitting(true);
    try {
      await onClone(source.id, target, name.trim() || `${source.name} (${target.name})`);
      onOpenChange(false);
    } catch {
      /* reported by the hook */
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className={DIALOG_FORM}>
        <DialogHeader>
          <DialogTitle>{t("useSourceInCollection", { name: source.name })}</DialogTitle>
          <DialogDescription>{t("itsCredentialsAreCopied")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          <div className="bg-muted/40 flex min-w-0 items-center gap-3 rounded-lg border p-3">
            <ConnectorIcon type={source.connector_type} size="sm" />
            <p className="min-w-0 text-sm font-medium break-all">{source.name}</p>
          </div>
          <div className="space-y-1.5">
            <Label className="text-sm font-medium">{t("knowledgeBase")}</Label>
            <Select value={targetId} onValueChange={setTargetId}>
              <SelectTrigger
                className="h-10 w-full min-w-0 rounded-lg"
                aria-label={t("knowledgeBase")}
              >
                <SelectValue placeholder={t("selectKnowledgeBase")} />
              </SelectTrigger>
              <SelectContent>
                {targets.map((kb) => (
                  <SelectItem key={kb.id} value={kb.id}>
                    {kb.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="clone-target-name" className="text-sm font-medium">
              {t("nameCopy")}
            </Label>
            <Input
              id="clone-target-name"
              placeholder={t("leaveEmptyAutoGenerate")}
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="h-10 w-full min-w-0 rounded-lg"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            {t("cancel3")}
          </Button>
          <Button onClick={handleSubmit} disabled={!target || submitting}>
            {submitting && <Spinner className="h-3.5 w-3.5" />}
            {submitting ? t("adding") : t("use")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
