"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Button, ConfirmDialog } from "@/components/ui";
import { SettingsSection } from "@/components/settings/settings-section";
import { useForgetPersonMemory } from "@/hooks/use-memory";

interface ForgetMeProps {
  userId: string;
}

/**
 * "Forget everything you know about me", from the person's own settings.
 *
 * Theirs to press rather than an administrator's to grant: what an agent
 * remembers about somebody is about them, and a deletion they have to ask for is
 * a deletion that depends on somebody else's afternoon. An administrator holding
 * `members:manage` can do it for a colleague as well — that is the same route
 * with a different id, on the members page.
 *
 * It spans **every agent in the organization**, because "forget me" is a fact
 * about a person rather than about one agent they happened to talk to, and
 * answering it agent by agent is how a deletion request ends up half-done. It
 * reaches mem0 too where an agent keeps its memories there.
 */
export function ForgetMe({ userId }: ForgetMeProps) {
  const t = useTranslations("memory");
  const [open, setOpen] = useState(false);
  const forget = useForgetPersonMemory();

  return (
    <SettingsSection title={t("forgetTitle")} description={t("forgetBody")} danger>
      <Button
        type="button"
        variant="destructive"
        size="sm"
        disabled={forget.isPending}
        onClick={() => setOpen(true)}
      >
        {t("forgetAction")}
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={t("forgetTitle")}
        description={t("forgetConfirm")}
        confirmLabel={t("forgetAction")}
        confirmText="FORGET"
        destructive
        loading={forget.isPending}
        onConfirm={async () => {
          await forget.mutateAsync(userId);
          setOpen(false);
        }}
      />
    </SettingsSection>
  );
}
