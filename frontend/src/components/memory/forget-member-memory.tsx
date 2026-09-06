"use client";

import { useState } from "react";
import { Eraser } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, ConfirmDialog } from "@/components/ui";
import { useForgetPersonMemory } from "@/hooks/use-memory";

interface ForgetMemberMemoryProps {
  userId: string;
  /** Who is being forgotten, for the dialog and the button's label. */
  name: string;
}

/**
 * Erase everything the organization's agents remember about one member.
 *
 * The administrator's half of the same act a person can do for themselves in
 * their own settings, and it exists because the person cannot always ask: an
 * account is closed, somebody leaves, a request arrives through legal. Gated on
 * `members:manage`, the permission that already governs acting on another member
 * — deliberately not an agent permission, because somebody who may edit one agent
 * should not thereby be able to reach into what every other agent learned about a
 * colleague.
 *
 * Offered for every member, the owner and the caller included: this removes what
 * agents wrote about somebody, which is not a change to their standing in the
 * organization the way removing them is.
 */
export function ForgetMemberMemory({ userId, name }: ForgetMemberMemoryProps) {
  const t = useTranslations("memory");
  const [open, setOpen] = useState(false);
  const forget = useForgetPersonMemory();

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className="text-muted-foreground hover:text-destructive"
        disabled={forget.isPending}
        onClick={() => setOpen(true)}
        aria-label={t("forgetNamed", { name })}
      >
        <Eraser className="h-4 w-4" />
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={t("forgetNamed", { name })}
        description={t("forgetMemberConfirm", { name })}
        confirmLabel={t("forgetAction")}
        confirmText="FORGET"
        destructive
        loading={forget.isPending}
        onConfirm={async () => {
          await forget.mutateAsync(userId);
          setOpen(false);
        }}
      />
    </>
  );
}
