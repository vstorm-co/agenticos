"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
  Textarea,
} from "@/components/ui";
import { useGroups } from "@/hooks";
import { submitFailure } from "@/lib/api-error";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";
import type { Group } from "@/types/groups";

/** What the backend accepts, so an over-long value is refused before it is sent. */
const MAX_NAME = 128;
const MAX_DESCRIPTION = 500;

interface GroupFormDialogProps {
  orgId: string;
  /** The group being edited, or null to create one. */
  group: Group | null;
  onClose: () => void;
}

/**
 * Creating a group, or renaming one and changing what it says it is for.
 *
 * Mounted only while open, so each opening starts from the group as it stands
 * rather than from whatever the last one left typed.
 */
export function GroupFormDialog({ orgId, group, onClose }: GroupFormDialogProps) {
  const t = useTranslations("groups");
  const tErrors = useTranslations("errors");
  const { create, update } = useGroups(orgId);
  const [name, setName] = useState(group?.name ?? "");
  const [description, setDescription] = useState(group?.description ?? "");
  const [problems, setProblems] = useState<Readonly<Record<string, string>>>({});
  const pending = create.isPending || update.isPending;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    // An emptied description is cleared, not saved as an empty string.
    const input = { name: name.trim(), description: description.trim() || null };
    try {
      if (group) await update.mutateAsync({ groupId: group.id, input });
      else await create.mutateAsync(input);
      onClose();
    } catch (error) {
      // A taken name is a fact about the name, so it goes under that field.
      const failure = submitFailure(
        error,
        { fields: ["name", "description"], identifiedBy: "name" },
        tErrors,
      );
      setProblems(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    }
  };

  return (
    // Mounted only while open, so the one change of openness it can report is closing.
    <Dialog open onOpenChange={onClose}>
      <DialogContent className={DIALOG_CONFIRM}>
        <DialogHeader>
          <DialogTitle>{group ? t("editGroup") : t("newGroup")}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <FormField label={t("name")} htmlFor="group-name" error={problems.name}>
            <Input
              id="group-name"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setProblems({});
              }}
              placeholder={t("namePlaceholder")}
              maxLength={MAX_NAME}
            />
          </FormField>
          <FormField
            label={t("descriptionLabel")}
            htmlFor="group-description"
            error={problems.description}
          >
            <Textarea
              id="group-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t("descriptionPlaceholder")}
              maxLength={MAX_DESCRIPTION}
              rows={3}
            />
          </FormField>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={!name.trim() || pending}>
              {group ? t("save") : t("create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
