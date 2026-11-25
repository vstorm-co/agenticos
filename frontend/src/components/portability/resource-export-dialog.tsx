"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useBundleTransfer } from "@/hooks/use-bundle-transfer";
import { downloadBundleTransfer, type BundleRootKind } from "@/lib/portability-api";
import { Download, FileText, Link2, ShieldCheck } from "lucide-react";
import { useAuthStore, useOrgStore } from "@/stores";
import { useTranslations } from "next-intl";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useResourceExport } from "@/hooks/use-portability";
import { ExportLayers } from "./export-layers";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";

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
  const id = useId();
  const { preview, download } = useResourceExport(rootKind, resourceId, open);
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
      <DialogContent className={`${DIALOG_FORM} ${DIALOG_COLUMN}`}>
        <DialogHeader>
          <DialogTitle>
            {t(rootKind === "workflow" ? "exportWorkflowTitle" : "exportTitle")}
          </DialogTitle>
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
            <fieldset className="space-y-2">
              <legend className="mb-2 text-sm font-medium">{t("includedContent")}</legend>
              {data.bundle.resources.map((item, index) => {
                const root = data.bundle.roots.includes(item.key);
                const layers =
                  data.options.find((option) => option.key === item.key)?.layers ?? item.included;
                const included = layers.length > 0;
                return (
                  <div
                    key={item.key}
                    className="border-border min-w-0 space-y-3 rounded-xl border px-3 py-2"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      {included ? (
                        <Checkbox
                          id={`${id}-${index}`}
                          checked={!excluded.has(item.key)}
                          disabled={root || busy}
                          onCheckedChange={(checked) => {
                            resetZip();
                            setExcluded((previous) => {
                              const next = new Set(previous);
                              if (checked) next.delete(item.key);
                              else next.add(item.key);
                              return next;
                            });
                          }}
                        />
                      ) : (
                        <Link2
                          className="text-muted-foreground size-4 shrink-0"
                          aria-hidden="true"
                        />
                      )}
                      <Label
                        htmlFor={included ? `${id}-${index}` : undefined}
                        className="flex min-h-11 min-w-0 flex-1 flex-col items-start justify-center gap-1"
                      >
                        <span className="font-medium break-words">{item.name}</span>
                        <span className="text-muted-foreground text-xs font-normal">
                          {root
                            ? t(
                                rootKind === "workflow"
                                  ? "workflowRootDefinition"
                                  : "rootDefinition",
                              )
                            : included
                              ? t("layerDefinition")
                              : t("referenceOnly")}
                        </span>
                      </Label>
                      {root && (
                        <FileText
                          className="text-muted-foreground size-4 shrink-0"
                          aria-hidden="true"
                        />
                      )}
                    </div>
                    {included && !excluded.has(item.key) && (
                      <ExportLayers
                        layers={layers}
                        selected={layersByKey[item.key] ?? ["definition"]}
                        format={format}
                        disabled={busy}
                        knowledgeBase={item.kind === "knowledge_base"}
                        onChange={(selected) => {
                          resetZip();
                          setLayersByKey((previous) => ({ ...previous, [item.key]: selected }));
                        }}
                      />
                    )}
                  </div>
                );
              })}
            </fieldset>
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
