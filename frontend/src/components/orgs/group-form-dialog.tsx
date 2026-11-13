"use client";

import { Check } from "lucide-react";
import { useState } from "react";
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
  FormField,
  Input,
  Textarea,
  MoreOptions,
} from "@/components/ui";
import { useGroups } from "@/hooks";
import { submitFailure } from "@/lib/api-error";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_CONFIRM } from "@/lib/dialog-sizes";
import { GroupIcon, GROUP_ICON_COMPONENTS } from "@/components/groups/group-icon";
import { cn } from "@/lib/utils";
import { GROUP_ICONS, type Group, type GroupIcon as GroupIconName } from "@/types/groups";

/** What the backend accepts, so an over-long value is refused before it is sent. */
const MAX_NAME = 128;
const MAX_DESCRIPTION = 500;

/** The stored cap as the input shows it - `50`, not the API's `50.000000`. Empty is none. */
function asBudgetInput(cap: string | null | undefined): string {
  return cap == null ? "" : String(Number(cap));
}

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
  const [icon, setIcon] = useState<GroupIconName | null>(group?.icon ?? null);
  const [budget, setBudget] = useState(asBudgetInput(group?.monthly_budget_usd));
  const [problems, setProblems] = useState<Readonly<Record<string, string>>>({});
  const [optionsOpen, setOptionsOpen] = useState(group?.monthly_budget_usd != null);
  const pending = create.isPending || update.isPending;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (pending) return;
    // An emptied description is cleared, not saved as an empty string; an
    // emptied budget lifts the cap.
    const input = {
      name: name.trim(),
      description: description.trim() || null,
      icon,
      monthly_budget_usd: budget.trim() === "" ? null : Number(budget),
    };
    try {
      if (group) await update.mutateAsync({ groupId: group.id, input });
      else await create.mutateAsync(input);
      onClose();
    } catch (error) {
      // A taken name is a fact about the name, so it goes under that field.
      const failure = submitFailure(
        error,
        { fields: ["name", "description", "monthly_budget_usd"], identifiedBy: "name" },
        tErrors,
      );
      setProblems(failure.fields);
      if (failure.fields.monthly_budget_usd) setOptionsOpen(true);
      if (failure.toast) toast.error(failure.toast);
    }
  };

  return (
    // Mounted only while open, so the one change of openness it can report is closing.
    <Dialog
      open
      onOpenChange={() => {
        if (!pending) onClose();
      }}
    >
      <DialogContent className={cn(DIALOG_CONFIRM, DIALOG_COLUMN)} dismissible={!pending}>
        <DialogHeader>
          <DialogTitle>{group ? t("editGroup") : t("newGroup")}</DialogTitle>
          <DialogDescription>{t("formDescription")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex min-h-0 flex-col gap-5">
          <div className={DIALOG_BODY}>
            <fieldset disabled={pending} className="min-w-0 space-y-5">
              <legend className="sr-only">{group ? t("editGroup") : t("newGroup")}</legend>
              <div className="flex items-end gap-3">
                <GroupIcon icon={icon} className="mb-0.5 size-11 rounded-xl [&_svg]:size-5" />
                <FormField
                  className="min-w-0 flex-1"
                  label={t("name")}
                  htmlFor="group-name"
                  error={problems.name}
                >
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
              </div>
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
              <div className="space-y-1.5">
                <p className="text-sm font-medium">{t("icon")}</p>
                <div
                  role="group"
                  aria-label={t("icon")}
                  className="grid grid-cols-4 gap-2 sm:grid-cols-6"
                >
                  {GROUP_ICONS.map((key) => {
                    const Mark = GROUP_ICON_COMPONENTS[key];
                    return (
                      <button
                        key={key}
                        type="button"
                        aria-pressed={icon === key}
                        aria-label={t(`icons.${key}`)}
                        title={t(`icons.${key}`)}
                        onClick={() => setIcon(icon === key ? null : key)}
                        className={cn(
                          "relative flex h-11 min-h-11 w-full items-center justify-center rounded-xl border transition-colors",
                          icon === key ? "border-foreground/40 bg-accent" : "hover:bg-accent/50",
                        )}
                      >
                        <Mark className="size-5" aria-hidden />
                        {icon === key && (
                          <Check className="absolute top-1 right-1 size-3" aria-hidden />
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
              <MoreOptions
                label={t("budgetOptions")}
                open={optionsOpen}
                onOpenChange={setOptionsOpen}
              >
                <FormField
                  label={t("monthlyBudget")}
                  htmlFor="group-budget"
                  error={problems.monthly_budget_usd}
                  description={t("monthlyBudgetHint")}
                >
                  <Input
                    id="group-budget"
                    type="number"
                    min="0"
                    step="1"
                    value={budget}
                    onChange={(e) => setBudget(e.target.value)}
                    placeholder={t("noBudget")}
                  />
                </FormField>
              </MoreOptions>
            </fieldset>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" disabled={pending} onClick={onClose}>
              {t("cancel")}
            </Button>
            <Button type="submit" loading={pending} disabled={!name.trim()}>
              {group ? t("save") : t("create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
