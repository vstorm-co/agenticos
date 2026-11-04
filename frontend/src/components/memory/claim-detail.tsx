"use client";

import { useState } from "react";
import { Pencil, Undo2 } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import {
  Badge,
  Button,
  ConfirmDialog,
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetClose,
} from "@/components/ui";
import type { MemoryClaim, DecisionEpisode } from "@/lib/memory-api";
import { DecisionEvidence } from "./decision-evidence";
import { ClaimEditor } from "./claim-editor";

export function ClaimDetail({
  claim,
  onClose,
  correct,
  retract,
}: {
  claim: MemoryClaim;
  onClose: () => void;
  correct: (
    id: string,
    statement: string,
    from: string | null,
    episode?: DecisionEpisode,
  ) => Promise<boolean>;
  retract: (id: string) => Promise<boolean>;
}) {
  const t = useTranslations("pages.memory.claims");
  const view = useTranslations("pages.memory.browser");
  const format = useFormatter();
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const live = claim.status === "current" || claim.status === "disputed";
  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <SheetContent side="right" className="w-full sm:w-[38rem]">
        <SheetHeader className="shrink-0 px-5 py-4 sm:px-7">
          <SheetTitle>
            {view(
              `type.${claim.kind === "fact" || claim.kind === "preference" || claim.kind === "decision" ? claim.kind : "other"}`,
            )}
          </SheetTitle>
          <SheetClose onClick={onClose} />
        </SheetHeader>
        <div className="flex-1 space-y-7 overflow-y-auto px-5 py-6 sm:px-7">
          <Badge variant="outline">{t(`status.${claim.status}`)}</Badge>
          {editing ? (
            <ClaimEditor
              claim={claim}
              onCancel={() => setEditing(false)}
              onSave={async (statement, from, episode) => {
                if (await correct(claim.id, statement, from, episode)) onClose();
              }}
            />
          ) : (
            <p className="text-lg leading-8 font-medium break-words">{claim.statement}</p>
          )}
          <dl className="grid grid-cols-1 gap-5 rounded-xl border p-4 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-muted-foreground mb-1 text-xs">{view("scopeLabel")}</dt>
              <dd>
                {claim.scope === "profile"
                  ? t("scopeProfile")
                  : t("scopeAgent", { agent: claim.agent_name ?? t("anAgent") })}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground mb-1 text-xs">{view("sourceLabel")}</dt>
              <dd>{t(`origin.${claim.origin}`)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground mb-1 text-xs">{view("recorded")}</dt>
              <dd>{format.dateTime(new Date(claim.observed_at), { dateStyle: "medium" })}</dd>
            </div>
            {claim.effective_from && (
              <div>
                <dt className="text-muted-foreground mb-1 text-xs">{t("effectiveFrom")}</dt>
                <dd>{format.dateTime(new Date(claim.effective_from), { dateStyle: "medium" })}</dd>
              </div>
            )}
            {claim.origin === "consolidation" && (
              <div className="sm:col-span-2">
                {t("drawnFrom", { count: claim.derived_from_count })}
              </div>
            )}
          </dl>
          {claim.episode && !editing && <DecisionEvidence claim={claim} />}
        </div>
        {live && !editing && (
          <div className="flex shrink-0 flex-wrap gap-2 border-t px-5 py-4 sm:px-7">
            <Button variant="outline" onClick={() => setEditing(true)}>
              <Pencil className="size-4" aria-hidden />
              {t("correct")}
            </Button>
            <Button variant="ghost" onClick={() => setConfirming(true)}>
              <Undo2 className="size-4" aria-hidden />
              {t("retract")}
            </Button>
          </div>
        )}
        <ConfirmDialog
          open={confirming}
          onOpenChange={setConfirming}
          title={t("retract")}
          description={view("retractHint")}
          confirmLabel={t("retract")}
          loading={pending}
          onConfirm={async () => {
            setPending(true);
            try {
              if (await retract(claim.id)) {
                setConfirming(false);
                onClose();
              }
            } finally {
              setPending(false);
            }
          }}
        />
      </SheetContent>
    </Sheet>
  );
}
