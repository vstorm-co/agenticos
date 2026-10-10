"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { GroupIcon } from "@/components/groups/group-icon";
import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { useAddDepartments } from "@/hooks";
import { DIALOG_COLUMN } from "@/lib/dialog-sizes";
import type { Group, GroupIcon as GroupIconName } from "@/types/groups";

/** The departments most companies start from, each with its mark (#2072). */
const DEPARTMENTS: readonly { key: string; icon: GroupIconName }[] = [
  { key: "sales", icon: "briefcase" },
  { key: "finance", icon: "banknote" },
  { key: "hr", icon: "heart-handshake" },
  { key: "support", icon: "headphones" },
  { key: "engineering", icon: "code" },
  { key: "marketing", icon: "megaphone" },
  { key: "legal", icon: "scale" },
  { key: "operations", icon: "truck" },
];

/**
 * Add a company's departments as groups in one step.
 *
 * Names are the reader's language, because a department is called what the
 * company calls it; one already in the organization is shown and not offered.
 */
export function DepartmentTemplates({
  orgId,
  existing,
  onClose,
}: {
  orgId: string;
  existing: Group[];
  onClose: () => void;
}) {
  const t = useTranslations("groups");
  const add = useAddDepartments(orgId);
  const taken = new Set(existing.map((group) => group.name.toLowerCase()));
  const offered = DEPARTMENTS.filter(
    (department) => !taken.has(t(`departments.${department.key}.name`).toLowerCase()),
  );
  const [picked, setPicked] = useState<Set<string>>(
    () => new Set(offered.slice(0, 5).map((department) => department.key)),
  );

  const toggle = (key: string) =>
    setPicked((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const submit = async () => {
    const chosen = offered.filter((department) => picked.has(department.key));
    await add
      .mutateAsync(
        chosen.map((department) => ({
          name: t(`departments.${department.key}.name`),
          description: t(`departments.${department.key}.description`),
          icon: department.icon,
        })),
      )
      .then(onClose)
      .catch(() => undefined);
  };

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className={DIALOG_COLUMN}>
        <DialogHeader>
          <DialogTitle>{t("addDepartments")}</DialogTitle>
          <DialogDescription>{t("addDepartmentsWhy")}</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
          {offered.length === 0 && (
            <p className="text-muted-foreground py-6 text-center text-sm">
              {t("allDepartmentsAdded")}
            </p>
          )}
          {offered.map((department) => (
            <label
              key={department.key}
              className="hover:bg-accent/50 flex cursor-pointer items-center gap-3 rounded-lg p-2"
            >
              <Checkbox
                checked={picked.has(department.key)}
                onCheckedChange={() => toggle(department.key)}
              />
              <GroupIcon icon={department.icon} />
              <span className="min-w-0">
                <span className="block text-sm font-medium">
                  {t(`departments.${department.key}.name`)}
                </span>
                <span className="text-muted-foreground block text-xs">
                  {t(`departments.${department.key}.description`)}
                </span>
              </span>
            </label>
          ))}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button onClick={submit} disabled={picked.size === 0 || add.isPending}>
            {t("addPickedDepartments", { count: picked.size })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
