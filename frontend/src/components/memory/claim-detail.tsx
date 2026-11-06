"use client";

import { useState } from "react";
import { Brain, CalendarDays, Fingerprint, Pencil, Undo2, UsersRound } from "lucide-react";
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
      <SheetContent side="right" className="w-full overflow-hidden sm:w-[32rem]">
        <SheetHeader className="shrink-0 px-5 py-4 sm:px-7">
          <SheetTitle className="flex min-w-0 items-center gap-2.5">
            <Brain className="text-muted-foreground size-4 shrink-0" aria-hidden />
            {view(
              `type.${claim.kind === "fact" || claim.kind === "preference" || claim.kind === "decision" ? claim.kind : "other"}`,
            )}
          </SheetTitle>
          <div className="flex shrink-0 items-center gap-2">
            <Badge variant="secondary" className="font-normal">
              {t(`status.${claim.status}`)}
            </Badge>
            <SheetClose onClick={onClose} />
          </div>
        </SheetHeader>
        <div className="min-h-0 flex-1 space-y-8 overflow-y-auto overscroll-contain px-5 py-6 sm:px-7">
          {editing ? (
            <ClaimEditor
              claim={claim}
              onCancel={() => setEditing(false)}
              onSave={async (statement, from, episode) => {
                if (await correct(claim.id, statement, from, episode)) onClose();
              }}
            />
          ) : (
            <p className="text-lg leading-relaxed font-normal break-words whitespace-pre-wrap">
              {claim.statement}
            </p>
          )}
          <section className="space-y-4">
            <h3 className="text-muted-foreground text-xs font-medium">{view("noteDetails")}</h3>
            <dl className="bg-muted/40 grid grid-cols-1 gap-5 rounded-xl p-4 text-sm min-[380px]:grid-cols-2">
              <div>
                <dt className="text-muted-foreground mb-1.5 flex items-center gap-1.5 text-xs">
                  <UsersRound className="size-3.5" aria-hidden />
                  {view("scopeLabel")}
                </dt>
                <dd>
                  {claim.scope === "profile"
                    ? t("scopeProfile")
                    : t("scopeAgent", { agent: claim.agent_name ?? t("anAgent") })}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground mb-1.5 flex items-center gap-1.5 text-xs">
                  <Fingerprint className="size-3.5" aria-hidden />
                  {view("sourceLabel")}
                </dt>
                <dd>{t(`origin.${claim.origin}`)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground mb-1.5 flex items-center gap-1.5 text-xs">
                  <CalendarDays className="size-3.5" aria-hidden />
                  {view("recorded")}
                </dt>
                <dd>{format.dateTime(new Date(claim.observed_at), { dateStyle: "medium" })}</dd>
              </div>
              {claim.effective_from && (
                <div>
                  <dt className="text-muted-foreground mb-1.5 flex items-center gap-1.5 text-xs">
                    {t("effectiveFrom")}
                  </dt>
                  <dd>
                    {format.dateTime(new Date(claim.effective_from), { dateStyle: "medium" })}
                  </dd>
                </div>
              )}
              {claim.origin === "consolidation" && (
                <div className="sm:col-span-2">
                  {t("drawnFrom", { count: claim.derived_from_count })}
                </div>
              )}
            </dl>
          </section>
          {claim.episode && !editing && <DecisionEvidence claim={claim} />}
        </div>
        {live && !editing && (
          <div className="border-foreground/8 bg-background/50 flex shrink-0 flex-wrap gap-2 border-t px-5 py-4 sm:px-7">
            <Button variant="secondary" onClick={() => setEditing(true)}>
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
