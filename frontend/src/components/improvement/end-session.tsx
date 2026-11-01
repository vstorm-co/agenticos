"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, ConfirmDialog } from "@/components/ui";
import { useImprovement } from "@/hooks/use-improvements";
import { getErrorMessage } from "@/lib/api-error";
import type { Improvement } from "@/types/improvement";

/**
 * Ends a session that waits for a person, from inside the wizard. It stays in the
 * agent's history and nothing in the agent changes; only whoever may stop it is offered it.
 */
export function EndSession({ session }: { session: Improvement }) {
  const t = useTranslations("improvement.endSession");
  const tErrors = useTranslations("errors");
  const actions = useImprovement(session.agent_id, session.id);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (session.can_discard === false) return null;
  return (
    <>
      <Button variant="outline" onClick={() => setConfirming(true)}>
        {t("action")}
      </Button>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("title")}
        description={
          <>
            {t("body")}
            {error && (
              <span role="alert" className="text-destructive mt-2 block">
                {error}
              </span>
            )}
          </>
        }
        confirmLabel={t("confirm")}
        loading={actions.cancel.isPending}
        onConfirm={async () => {
          setError(null);
          try {
            await actions.cancel.mutateAsync();
            setConfirming(false);
          } catch (failure) {
            setError(getErrorMessage(failure, tErrors));
          }
        }}
      />
    </>
  );
}
