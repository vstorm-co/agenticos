"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Button, ConfirmDialog } from "@/components/ui";
import { useClearAgentMemory } from "@/hooks/use-memory";

interface ClearAgentMemoryProps {
  agentId: string;
  /** Whether this agent also keeps memories in mem0, which this cannot reach. */
  usesMem0: boolean;
  disabled?: boolean;
}

/**
 * Empty one agent's notes, from inside the capability that keeps them.
 *
 * Beside the capability rather than on a tab of its own, because that is the
 * only thing anybody does to memory from the console: there is no browsing. What
 * an agent wrote down about a named colleague is not a screen an operator should
 * be able to page through, and standing knowledge a person *wants* an agent to
 * have belongs in context files.
 *
 * A store nobody can clear is a liability, though — which is why this exists at
 * all (#788). Typed confirmation, because it removes every person's and every
 * room's notes at once and nothing brings them back.
 *
 * `usesMem0` changes the sentence rather than the button. mem0 keeps its
 * memories in its own service, addressed per person, so there is nothing here
 * that can empty an agent's namespace wholesale — and a dialog that implied
 * otherwise would leave somebody believing a wipe happened that did not.
 */
export function ClearAgentMemory({ agentId, usesMem0, disabled }: ClearAgentMemoryProps) {
  const t = useTranslations("memory");
  const [open, setOpen] = useState(false);
  const clear = useClearAgentMemory(agentId);

  return (
    <div className="border-destructive/30 bg-destructive/[0.03] space-y-3 rounded-lg border p-4">
      <div>
        <p className="text-destructive text-sm font-medium">{t("clearTitle")}</p>
        <p className="text-muted-foreground mt-1 text-xs">
          {usesMem0 ? t("clearBodyWithMem0") : t("clearBody")}
        </p>
      </div>
      <Button
        type="button"
        variant="destructive"
        size="sm"
        disabled={disabled || clear.isPending}
        onClick={() => setOpen(true)}
      >
        {t("clearAction")}
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={t("clearTitle")}
        description={t("clearConfirm")}
        confirmLabel={t("clearAction")}
        confirmText="CLEAR"
        destructive
        loading={clear.isPending}
        onConfirm={async () => {
          await clear.mutateAsync();
          setOpen(false);
        }}
      />
    </div>
  );
}
