"use client";

import { useState } from "react";
import { toast } from "sonner";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from "@/components/ui";
import { submitFailure } from "@/lib/api-error";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import {
  LOCAL_SERVICE_PROVIDERS,
  type LocalServiceInput,
  type LocalServiceKind,
} from "@/lib/local-services-api";
import { useTranslations } from "next-intl";

interface LocalServiceDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Whether the caller may register for the whole deployment - the app admin. */
  canRegisterDeploymentWide: boolean;
  onSubmit: (input: LocalServiceInput) => Promise<unknown>;
}

/**
 * Register one server. The provider is not asked: there is one embedding
 * catalog entry and one OCR parser a local server can stand behind today, so the
 * kind decides it, and a field that could only hold one value is noise.
 */
export function LocalServiceDialog({
  open,
  onOpenChange,
  canRegisterDeploymentWide,
  onSubmit,
}: LocalServiceDialogProps) {
  const t = useTranslations("kb");
  const tErrors = useTranslations("errors");
  const [name, setName] = useState("");
  const [kind, setKind] = useState<LocalServiceKind>("embedding");
  const [baseUrl, setBaseUrl] = useState("");
  const [deploymentWide, setDeploymentWide] = useState(false);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  const close = () => {
    setName("");
    setKind("embedding");
    setBaseUrl("");
    setDeploymentWide(false);
    setErrors({});
    onOpenChange(false);
  };

  const submit = async () => {
    setSaving(true);
    try {
      await onSubmit({
        name: name.trim(),
        kind,
        provider: LOCAL_SERVICE_PROVIDERS[kind],
        base_url: baseUrl.trim(),
        ...(deploymentWide ? { deployment_wide: true } : {}),
      });
      close();
    } catch (error) {
      const failure = submitFailure(error, { fields: ["name", "base_url", "kind"] }, tErrors);
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent className={DIALOG_FORM}>
        <DialogHeader>
          <DialogTitle>{t("addServer")}</DialogTitle>
          <DialogDescription>{t("localServicesHint")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <FormField label={t("name")} htmlFor="local-service-name" error={errors.name}>
            <Input id="local-service-name" value={name} onChange={(e) => setName(e.target.value)} />
          </FormField>
          <div className="space-y-1.5">
            <Label htmlFor="local-service-kind">{t("localServiceKind")}</Label>
            <Select value={kind} onValueChange={(next) => setKind(next as LocalServiceKind)}>
              <SelectTrigger id="local-service-kind" aria-invalid={errors.kind !== undefined}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="embedding">{t("embeddingServer")}</SelectItem>
                <SelectItem value="ocr">{t("ocrServer")}</SelectItem>
              </SelectContent>
            </Select>
            {errors.kind && <p className="text-destructive text-xs">{errors.kind}</p>}
          </div>
          <FormField
            label={t("address")}
            htmlFor="local-service-url"
            description={t("addressHint")}
            error={errors.base_url}
          >
            <Input
              id="local-service-url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={t(kind === "embedding" ? "ollamaAddressExample" : "ocrAddressExample")}
            />
          </FormField>
          {canRegisterDeploymentWide && (
            <div className="flex items-start justify-between gap-4">
              <div>
                <Label htmlFor="local-service-deployment-wide">{t("deploymentWide")}</Label>
                <p className="text-muted-foreground mt-0.5 text-xs">{t("deploymentWideHint")}</p>
              </div>
              <Switch
                id="local-service-deployment-wide"
                checked={deploymentWide}
                onCheckedChange={setDeploymentWide}
              />
            </div>
          )}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={close}>
            {t("cancel")}
          </Button>
          <Button
            type="button"
            onClick={submit}
            disabled={saving || name.trim() === "" || baseUrl.trim() === ""}
          >
            {saving ? t("registering") : t("register")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
