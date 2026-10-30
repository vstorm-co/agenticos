"use client";

import { ContextHelp } from "@/components/ui/context-help";
import { useState } from "react";
import { Server, Trash2 } from "lucide-react";

import { LocalServiceIcon } from "@/components/kb/local-service-icon";
import { ErrorState } from "@/components/states";
import { LocalServiceDialog } from "@/components/kb/local-service-dialog";
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
  Skeleton,
} from "@/components/ui";
import { useLocalServices, usePermissions } from "@/hooks";
import type { LocalServiceRecord } from "@/lib/local-services-api";
import { Perm } from "@/types/permissions";
import { useTranslations } from "next-intl";

/**
 * The servers on the deployment's own network that collections may use: an
 * Ollama to embed through with no key, an OCR sidecar for LiteParse.
 *
 * On the Knowledge list beside the reusable integrations, for the same reason
 * they are: a server is registered once and chosen per collection, and it has
 * no collection page of its own to live on. Hidden without `connections:manage`,
 * the permission the endpoints gate on - a row here decides where an
 * organization's documents are sent, which is the same decision an MCP server
 * or a sandbox host is.
 *
 * A deployment-wide row is the app admin's and is shown to every organization
 * that may see this section, marked as such: it is the only kind an app-scoped
 * collection can embed through, and an organization may use it too.
 */
export function LocalServices() {
  const t = useTranslations("kb");
  const { can, isAppAdmin } = usePermissions();
  const mayManage = can(Perm.connectionsManage);
  const { services, isLoading, error, create, remove } = useLocalServices(mayManage);
  const [adding, setAdding] = useState(false);

  if (!mayManage) return null;

  return (
    <section className="border-border bg-card flex min-w-0 flex-col overflow-hidden rounded-xl border">
      <div className="border-border flex flex-col items-start justify-between gap-3 border-b px-5 py-4 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1">
            <h2 className="text-foreground text-sm font-semibold">{t("localServices")}</h2>
            <ContextHelp>{t("localServicesHint")}</ContextHelp>
          </div>
        </div>
        <Button
          data-tour="knowledge-add-local-service"
          variant="outline"
          size="sm"
          onClick={() => setAdding(true)}
        >
          <Server className="h-4 w-4" />
          {t("addServer")}
        </Button>
      </div>

      {error ? (
        <ErrorState description={error} className="m-4 border-0 py-8" />
      ) : isLoading ? (
        <div role="status" aria-label={t("loadingLocalServices")} className="space-y-4 p-4">
          {[0, 1].map((index) => (
            <div key={index} className="flex items-center gap-3" aria-hidden>
              <Skeleton className="size-8 shrink-0 rounded-lg" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-3 w-4/5" />
              </div>
            </div>
          ))}
        </div>
      ) : services.length === 0 ? (
        <div className="flex items-start gap-3 px-5 py-6">
          <span className="bg-muted text-muted-foreground flex size-10 shrink-0 items-center justify-center rounded-xl">
            <Server className="size-5" aria-hidden />
          </span>
          <p className="text-muted-foreground max-w-md text-sm leading-relaxed">
            {t("noLocalServicesYet")}
          </p>
        </div>
      ) : (
        <ul className="divide-border divide-y">
          {services.map((service) => (
            <LocalServiceRow
              key={service.id}
              service={service}
              // A deployment-wide row is the app admin's to remove; an
              // organization's own is its manager's.
              canRemove={service.organization_id !== null || isAppAdmin}
              onDelete={() => remove(service.id)}
            />
          ))}
        </ul>
      )}

      <LocalServiceDialog
        open={adding}
        onOpenChange={setAdding}
        canRegisterDeploymentWide={isAppAdmin}
        onSubmit={create}
      />
    </section>
  );
}

function LocalServiceRow({
  service,
  canRemove,
  onDelete,
}: {
  service: LocalServiceRecord;
  canRemove: boolean;
  onDelete: () => void;
}) {
  const t = useTranslations("kb");
  const tc = useTranslations("common");
  return (
    <li className="hover:bg-accent flex items-center gap-3 px-4 py-3 transition-colors">
      <span className="bg-muted text-muted-foreground inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg">
        <LocalServiceIcon kind={service.kind} className="h-5 w-5" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-foreground truncate text-sm font-medium">
          {service.organization_id === null
            ? t("deploymentWideNamed", { name: service.name })
            : service.name}
        </p>
        <p className="text-muted-foreground mt-0.5 truncate font-mono text-xs tracking-wider">
          {service.kind === "embedding" ? t("embeddingServer") : t("ocrServer")}
          {` · ${service.base_url}`}
        </p>
      </div>
      {canRemove && (
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground hover:text-destructive h-8 w-8 p-0"
              aria-label={tc("removeNamed", { name: service.name })}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{t("removeNamed", { name: service.name })}</AlertDialogTitle>
              <AlertDialogDescription>{t("collectionsPointingAtItStop")}</AlertDialogDescription>
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
      )}
    </li>
  );
}
