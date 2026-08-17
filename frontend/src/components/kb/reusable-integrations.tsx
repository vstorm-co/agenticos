"use client";

import { useState } from "react";
import { Copy, Database, Plug, Trash2 } from "lucide-react";

import { BrandIcon, connectorBrand } from "@/components/icons/brand-icon";
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
  Button,
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
import { usePermissions, useReusableIntegrations } from "@/hooks";
import { useOrgStore } from "@/stores";
import type { SyncSourceCreate, SyncSourceRead } from "@/lib/rag-api";
import type { KnowledgeBase } from "@/types";
import { Perm } from "@/types/permissions";
import { useChanged } from "@/hooks/use-changed";
import { useTranslations } from "next-intl";

interface ReusableIntegrationsProps {
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
export function ReusableIntegrations({ targets }: ReusableIntegrationsProps) {
  const t = useTranslations("kb");
  const { can } = usePermissions();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const mayManage = can(Perm.connectionsManage);

  const { integrations, connectors, isLoading, error, create, remove, cloneInto } =
    useReusableIntegrations(mayManage ? activeOrgId : null);

  const [wizardOpen, setWizardOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [cloning, setCloning] = useState<SyncSourceRead | null>(null);

  if (!mayManage) return null;

  const handleCreate = async (data: SyncSourceCreate) => {
    setSubmitting(true);
    try {
      await create(data);
      setWizardOpen(false);
    } catch {
      // Reported by the hook. Swallowed here so the wizard stays open on the
      // step that holds the field the server rejected - and so a refusal is not
      // an unhandled rejection in the click handler.
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-foreground text-sm font-semibold">{t("reusableIntegrations")}</h2>
          <p className="text-muted-foreground mt-0.5 text-xs">{t("configuredOnceUsedAs")}</p>
        </div>
        {connectors.length > 0 && (
          <Button variant="outline" size="sm" onClick={() => setWizardOpen(true)}>
            <Plug className="h-4 w-4" />
            {t("addIntegration")}
          </Button>
        )}
      </div>

      {error ? (
        <p className="text-destructive text-xs">{error}</p>
      ) : isLoading ? (
        <p className="text-muted-foreground text-xs">{t("loadingIntegrations")}</p>
      ) : integrations.length === 0 ? (
        <p className="text-muted-foreground border-border rounded-xl border border-dashed px-4 py-3 text-xs">
          {t("nothingHereYetAdd")}
        </p>
      ) : (
        <ul className="border-border bg-card divide-border divide-y overflow-hidden rounded-xl border">
          {integrations.map((source) => (
            <IntegrationRow
              key={source.id}
              source={source}
              canClone={targets.length > 0}
              onClone={() => setCloning(source)}
              onDelete={() => remove(source.id)}
            />
          ))}
        </ul>
      )}

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
    </section>
  );
}

function IntegrationRow({
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
  const brand = connectorBrand(source.connector_type);
  return (
    <li className="hover:bg-accent flex items-center gap-3 px-4 py-3 transition-colors">
      <span className="bg-muted text-muted-foreground inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg">
        {brand ? <BrandIcon name={brand} className="h-4 w-4" /> : <Database className="h-4 w-4" />}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-foreground truncate text-sm font-medium">{source.name}</p>
        <p className="text-muted-foreground mt-0.5 font-mono text-[10px] tracking-wider uppercase">
          {source.connector_type}
          {source.schedule_minutes
            ? ` · ${t("everyMinutes", { minutes: source.schedule_minutes })}`
            : ` · ${t("manualSchedule")}`}
        </p>
      </div>
      <Button variant="outline" size="sm" onClick={onClone} disabled={!canClone}>
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
    </li>
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
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("useSourceInCollection", { name: source.name })}</DialogTitle>
          <DialogDescription>{t("itsCredentialsAreCopied")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label className="text-foreground/80 text-xs font-medium tracking-wider uppercase">
              {t("knowledgeBase")}
            </Label>
            <Select value={targetId} onValueChange={setTargetId}>
              <SelectTrigger className="h-10 rounded-xl" aria-label={t("knowledgeBase")}>
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
            <Label
              htmlFor="clone-target-name"
              className="text-foreground/80 text-xs font-medium tracking-wider uppercase"
            >
              {t("nameCopy")}
            </Label>
            <Input
              id="clone-target-name"
              placeholder={t("leaveEmptyAutoGenerate")}
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="h-10 rounded-xl"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            {t("cancel3")}
          </Button>
          <Button onClick={handleSubmit} disabled={!target || submitting}>
            {submitting && <Spinner className="h-3.5 w-3.5" />}
            {submitting ? t("adding") : t("addKnowledgeBase")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
