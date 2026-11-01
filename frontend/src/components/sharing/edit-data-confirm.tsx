"use client";

import { useTranslations } from "next-intl";

import { ConfirmDialog } from "@/components/ui";
import type { GrantSubject } from "@/types/sharing";

interface EditDataConfirmProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Who would get the level, as people know them. */
  name: string;
  kind: GrantSubject["kind"];
  onConfirm: () => void;
}

/**
 * What "Can edit, including data" lets someone do, said before it is given.
 *
 * The text is what the server records as agreed to - its id travels with the
 * share (`shareInput`) - so it names the person, or for a group everyone in it, now
 * and later. Shown to whoever may give the level, never to anyone else.
 */
export function EditDataConfirm({
  open,
  onOpenChange,
  name,
  kind,
  onConfirm,
}: EditDataConfirmProps) {
  const t = useTranslations("sharing");
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("editDataConfirmTitle")}
      description={
        kind === "group"
          ? t("editDataConfirmGroup", { name })
          : t("editDataConfirmPerson", { name })
      }
      confirmLabel={t("editDataConfirmAction")}
      onConfirm={onConfirm}
    />
  );
}
