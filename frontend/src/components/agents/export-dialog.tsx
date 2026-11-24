"use client";

import { useId, useState } from "react";
import { Download, FileText, Link2, ShieldCheck } from "lucide-react";
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
import { useAgentExport } from "@/hooks/use-portability";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";

export function ExportAgentDialog({
  agentId,
  open,
  onOpenChange,
}: {
  agentId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("portability");
  const tErrors = useTranslations("errors");
  const id = useId();
  const { preview, download } = useAgentExport(agentId, open);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [format, setFormat] = useState<"yaml" | "json">("yaml");
  const data = preview.data;
  const error = preview.error ?? download.error;
  const submit = data
    ? () => {
        const resources = Object.fromEntries(
          data.bundle.resources.map((item) => [
            item.key,
            excluded.has(item.key) ? [] : item.included,
          ]),
        );
        download.mutate({ format, resources });
      }
    : undefined;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={`${DIALOG_FORM} ${DIALOG_COLUMN}`}>
        <DialogHeader>
          <DialogTitle>{t("exportTitle")}</DialogTitle>
          <DialogDescription>{t("exportDescription")}</DialogDescription>
        </DialogHeader>
        <div className={`${DIALOG_BODY} space-y-5`}>
          <div className="bg-muted/40 text-muted-foreground flex gap-3 rounded-xl p-3 text-sm">
            <ShieldCheck className="size-5 shrink-0" aria-hidden="true" />
            <p>{t("secretsHint")}</p>
          </div>
          {preview.isPending && <p role="status">{t("loading")}</p>}
          {data && (
            <fieldset className="space-y-2">
              <legend className="mb-2 text-sm font-medium">{t("includedContent")}</legend>
              {data.bundle.resources.map((item, index) => {
                const root = data.bundle.roots.includes(item.key);
                const included = item.definition !== null;
                return (
                  <div
                    key={item.key}
                    className="border-border flex min-w-0 items-center gap-3 rounded-xl border px-3 py-2"
                  >
                    {included ? (
                      <Checkbox
                        id={`${id}-${index}`}
                        checked={!excluded.has(item.key)}
                        disabled={root || download.isPending}
                        onCheckedChange={(checked) =>
                          setExcluded((previous) => {
                            const next = new Set(previous);
                            if (checked) next.delete(item.key);
                            else next.add(item.key);
                            return next;
                          })
                        }
                      />
                    ) : (
                      <Link2 className="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
                    )}
                    <Label
                      htmlFor={included ? `${id}-${index}` : undefined}
                      className="flex min-h-11 min-w-0 flex-1 flex-col items-start justify-center gap-1"
                    >
                      <span className="font-medium break-words">{item.name}</span>
                      <span className="text-muted-foreground text-xs font-normal">
                        {root
                          ? t("rootDefinition")
                          : included
                            ? t("definitionAndContent")
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
                );
              })}
            </fieldset>
          )}
          <div className="space-y-2">
            <Label htmlFor={`${id}-format`}>{t("format")}</Label>
            <Select
              value={format}
              onValueChange={(value) => setFormat(value === "json" ? "json" : "yaml")}
            >
              <SelectTrigger id={`${id}-format`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="yaml">YAML</SelectItem>
                <SelectItem value="json">JSON</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {error && (
            <p role="alert" className="text-destructive text-sm">
              {getErrorMessage(error, tErrors, t("operationError"))}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("close")}
          </Button>
          <Button disabled={!data || download.isPending} onClick={submit}>
            <Download className="size-4" />
            {download.isPending ? t("downloading") : t("download")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
