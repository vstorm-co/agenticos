"use client";
import { useState } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { Button, Input } from "@/components/ui";
import { FormField } from "@/components/ui/form-field";
import { DialogFooter } from "@/components/ui/dialog";
import { useOrganizations } from "@/hooks";
import { submitFailure } from "@/lib/api-error";

const MAX_NAME = 128;
export function CreateOrgForm({
  onCreated,
  onCancel,
  onNameChange,
}: {
  onCreated: (id: string) => void;
  onCancel?: () => void;
  onNameChange?: (name: string) => void;
}) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("teams");
  const [name, setName] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { createOrg } = useOrganizations();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setIsSubmitting(true);
    try {
      const org = await createOrg({ name: name.trim() });
      setName("");
      onNameChange?.("");
      setNameError(null);
      onCreated(org.id);
    } catch (error) {
      // The slug is derived server-side and made unique, so the only thing that
      // can be wrong here is the name - which is why it belongs under it.
      const failure = submitFailure(error, { fields: ["name"], identifiedBy: "name" }, tErrors);
      setNameError(failure.fields.name ?? null);
      if (failure.toast) toast.error(failure.toast);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <FormField label={t("organizationName")} htmlFor="org-name" error={nameError}>
        <Input
          id="org-name"
          data-guidance={!name.trim() || undefined}
          autoComplete="organization"
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            onNameChange?.(e.target.value);
            setNameError(null);
          }}
          placeholder={t("myTeam")}
          maxLength={MAX_NAME}
        />
      </FormField>
      <DialogFooter>
        {onCancel && (
          <Button type="button" variant="outline" onClick={onCancel}>
            {t("cancel")}
          </Button>
        )}
        <Button type="submit" disabled={!name.trim() || isSubmitting}>
          {isSubmitting ? t("creating2") : t("create2")}
        </Button>
      </DialogFooter>
    </form>
  );
}
