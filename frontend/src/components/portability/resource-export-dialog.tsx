"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useBundleTransfer } from "@/hooks/use-bundle-transfer";
import { downloadBundleTransfer, type BundleRootKind } from "@/lib/portability-api";
import { Download, ShieldCheck, Maximize2, Minimize2 } from "lucide-react";
import { useAuthStore, useOrgStore } from "@/stores";
import { useTranslations } from "next-intl";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useResourceExport } from "@/hooks/use-portability";
import { ExportResourceList } from "./export-resource-list";
import { useAgent } from "@/hooks/use-agents";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_WIDE, DIALOG_WINDOW } from "@/lib/dialog-sizes";

function ExportResourceContent({
  resourceId,
  rootKind,
  open,
  onOpenChange,
}: {
  resourceId: string;
  rootKind: BundleRootKind;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("portability");
  const tErrors = useTranslations("errors");
  const common = useTranslations("common");
  const [expanded, setExpanded] = useState(false);
  const id = useId();
  const { preview, download } = useResourceExport(rootKind, resourceId, open);
  const { agent } = useAgent(rootKind === "agent" && open ? resourceId : null);
  const [layersByKey, setLayersByKey] = useState<Record<string, string[]>>({});
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [format, setFormat] = useState<"yaml" | "json" | "zip">("yaml");
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const zip = useBundleTransfer(open, `export:${rootKind}:${resourceId}`);
  const zipDownload = useMutation({ mutationFn: downloadBundleTransfer });
  const downloaded = useRef<string | null>(null);
  const downloadZip = zipDownload.mutate;
  useEffect(() => {
    const row = zip.transfer.data;
    if (row?.can_download && downloaded.current !== row.id) {
      downloaded.current = row.id;
      downloadZip(row.id);
    }
  }, [zip.transfer.data, downloadZip]);
  const busy = download.isPending || zip.busy || zipDownload.isPending;
  const resetZip = () => {
    zip.reset();
    zipDownload.reset();
    setRequestId(crypto.randomUUID());
  };
  const data = preview.data;
  const error = preview.error ?? download.error ?? zip.error ?? zipDownload.error;
  const submit = data
    ? () => {
        const resources = Object.fromEntries(
          data.bundle.resources.map((item) => [
            item.key,
            excluded.has(item.key)
              ? []
              : (layersByKey[item.key] ?? ["definition"]).filter(
                  (layer) =>
                    (format === "zip" || layer === "definition") &&
                    (
                      data.options.find((option) => option.key === item.key)?.layers ??
                      item.included
                    ).includes(layer),
                ),
          ]),
        );
        if (format === "zip") {
          if (zip.transfer.data?.can_download) zipDownload.mutate(zip.transfer.data.id);
          else zip.exportZip.mutate({ rootId: resourceId, rootKind, resources, requestId });
        } else download.mutate({ format, resources });
      }
    : undefined;
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (!busy) onOpenChange(value);
      }}
    >
      <DialogContent className={expanded ? DIALOG_WINDOW : `${DIALOG_WIDE} ${DIALOG_COLUMN}`}>
        <DialogHeader>
          <div className="flex items-center justify-between gap-3 pr-7">
            <DialogTitle>
              {t(rootKind === "workflow" ? "exportWorkflowTitle" : "exportTitle")}
            </DialogTitle>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={common(expanded ? "workspaceCollapse" : "workspaceExpand")}
              onClick={() => setExpanded(!expanded)}
            >
              {expanded ? (
                <Minimize2 className="size-4" aria-hidden />
              ) : (
                <Maximize2 className="size-4" aria-hidden />
              )}
            </Button>
          </div>
          <DialogDescription>
            {t(rootKind === "workflow" ? "exportWorkflowDescription" : "exportDescription")}
          </DialogDescription>
        </DialogHeader>
        <div className={`${DIALOG_BODY} space-y-5`}>
          <div className="bg-muted/40 text-muted-foreground flex gap-3 rounded-xl p-3 text-sm">
            <ShieldCheck className="size-5 shrink-0" aria-hidden="true" />
            <p>{t("secretsHint")}</p>
          </div>
          {preview.isPending && <p role="status">{t("loading")}</p>}
          <div className="space-y-2">
            <Label htmlFor={`${id}-format`}>{t("format")}</Label>
            <Select
              value={format}
              disabled={busy}
              onValueChange={(value) => {
                resetZip();
                setFormat(value === "zip" ? "zip" : value === "json" ? "json" : "yaml");
              }}
            >
              <SelectTrigger id={`${id}-format`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="yaml">YAML</SelectItem>
                <SelectItem value="json">JSON</SelectItem>
                <SelectItem value="zip">{t("zipFormat")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {data && (
            <ExportResourceList
              data={data}
              format={format}
              busy={busy}
              excluded={excluded}
              layersByKey={layersByKey}
              rootIdentity={
                agent
                  ? {
                      agentId: agent.id,
                      slug: agent.slug,
                      hasAvatar: agent.has_avatar,
                      colorSlot: agent.avatar_color,
                    }
                  : undefined
              }
              onInclude={(key, included) => {
                resetZip();
                setExcluded((previous) => {
                  const next = new Set(previous);
                  if (included) next.delete(key);
                  else next.add(key);
                  return next;
                });
              }}
              onLayers={(key, selected) => {
                resetZip();
                setLayersByKey((previous) => ({ ...previous, [key]: selected }));
              }}
            />
          )}
          {zip.busy && (
            <p role="status" className="text-muted-foreground text-sm">
              {t("transferWorking")}
            </p>
          )}
          {zip.transfer.data?.status === "failed" && (
            <p role="alert" className="text-destructive text-sm">
              {t("transferFailed")}
            </p>
          )}
          {(zip.restoreFailed ||
            zip.transfer.data?.status === "failed" ||
            zip.transfer.data?.status === "expired") && (
            <Button variant="outline" onClick={resetZip}>
              {t("startNewTransfer")}
            </Button>
          )}
          {error && (
            <p role="alert" className="text-destructive text-sm">
              {getErrorMessage(error, tErrors, t("operationError"))}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>
            {t("close")}
          </Button>
          <Button disabled={!data || busy} onClick={submit}>
            <Download className="size-4" />
            {busy ? t("downloading") : t("download")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ExportResourceDialog(props: Parameters<typeof ExportResourceContent>[0]) {
  const user = useAuthStore((state) => state.user?.id ?? null);
  const org = useOrgStore((state) => state.activeOrgId);
  return (
    <ExportResourceContent
      key={JSON.stringify([user, org, props.rootKind, props.resourceId])}
      {...props}
    />
  );
}
