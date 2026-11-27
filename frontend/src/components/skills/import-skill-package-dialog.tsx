"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { UploadButton, formatSize } from "./skill-files";
import { useTenantGuard, useTenantId } from "@/hooks/use-organizations";
import { getErrorMessage } from "@/lib/api-error";
import {
  applySkillPackage,
  previewSkillPackage,
  type SkillPackageFormat,
  type SkillPackagePreview,
} from "@/lib/skill-package-api";
import { qk } from "@/lib/query-keys";

interface PackageSelection {
  files: File[];
  format: SkillPackageFormat;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImported: (id: string) => void;
}
export function ImportSkillPackageDialog(props: Props) {
  const tenant = useTenantId();
  return <PackageDialog key={`${tenant}:${props.open}`} {...props} />;
}
function PackageDialog({ open, onOpenChange, onImported }: Props) {
  const t = useTranslations("skills.package");
  const errors = useTranslations("errors");
  const tenant = useTenantId();
  const current = useTenantGuard();
  const client = useQueryClient();
  const [selection, setSelection] = useState<PackageSelection | null>(null);
  const [preview, setPreview] = useState<SkillPackagePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  async function inspect(files: File[], format: SkillPackageFormat) {
    if (!files.length || busy) return;
    setBusy(true);
    setFailure(null);
    setPreview(null);
    setSelection(null);
    try {
      const result = await previewSkillPackage(files, format);
      if (!current(tenant)) return;
      setSelection({ files, format });
      setPreview(result);
    } catch (error) {
      if (current(tenant)) setFailure(getErrorMessage(error, errors));
    } finally {
      if (current(tenant)) setBusy(false);
    }
  }
  async function apply(selection: PackageSelection, fingerprint: string) {
    setBusy(true);
    setFailure(null);
    try {
      const receipt = await applySkillPackage(selection.files, selection.format, fingerprint);
      if (!current(tenant)) return;
      await client.invalidateQueries({ queryKey: qk.skills.all() });
      if (!current(tenant)) return;
      toast.success(t("imported"));
      onOpenChange(false);
      onImported(receipt.skill_id);
    } catch (error) {
      if (current(tenant)) setFailure(getErrorMessage(error, errors));
    } finally {
      if (current(tenant)) setBusy(false);
    }
  }
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (!busy) onOpenChange(value);
      }}
    >
      <DialogContent
        className="max-h-[85dvh] overflow-y-auto sm:max-w-xl"
        data-tour="skills-package-import"
      >
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <p className="text-muted-foreground text-xs">{t("limits")}</p>
        <fieldset disabled={busy} className="flex flex-wrap gap-2 disabled:opacity-50">
          <UploadButton
            label={t("directory")}
            directory
            onPick={(files) => void inspect(files, "directory")}
          />
          <UploadButton label={t("zip")} onPick={(files) => void inspect(files, "zip")} />
        </fieldset>
        {busy && !preview && (
          <p role="status" className="text-sm">
            {t("reading")}
          </p>
        )}
        {failure && (
          <p role="alert" className="text-destructive text-sm">
            {failure}
          </p>
        )}
        {preview && (
          <div className="space-y-3 rounded-xl border p-4">
            <h3 className="font-medium">{preview.name}</h3>
            <p className="text-muted-foreground text-sm">{preview.description}</p>
            <p className="text-xs">
              {t("summary", { count: preview.files.length, size: formatSize(preview.total_bytes) })}
            </p>
            <ul className="max-h-52 space-y-1 overflow-auto text-xs">
              <li className="font-mono">SKILL.md</li>
              {preview.files.map((file) => (
                <li key={file.name} className="flex justify-between gap-3">
                  <span className="min-w-0 font-mono break-all">{file.name}</span>
                  <span className="text-muted-foreground shrink-0">
                    {formatSize(file.size_bytes)} ·{" "}
                    {file.encoding === "base64" ? t("binary") : t("text")}
                  </span>
                </li>
              ))}
            </ul>
            <p className="text-muted-foreground text-xs">{t("private")}</p>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            loading={busy}
            disabled={!selection || !preview || busy}
            onClick={
              selection && preview ? () => void apply(selection, preview.fingerprint) : undefined
            }
          >
            {t("apply")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
