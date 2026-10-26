"use client";

import { useState } from "react";
import { FilePen, ListChecks, Target } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { Button, Checkbox } from "@/components/ui";
import { ChangePreview } from "@/components/authoring/result-dialog";
import { usd } from "@/components/evals/format";
import { useImprovement, useImprovementEvidence } from "@/hooks/use-improvements";
import { getErrorMessage } from "@/lib/api-error";
import type { Hunk } from "@/types/authoring";
import type { Improvement, ImprovementIteration, SelectionEstimate } from "@/types/improvement";
import { RoundTitle } from "./round-results";
import { Tiles } from "./widgets";

export function ChangeSelection({
  session,
  round,
  hunks,
  included,
  onChange,
  onStarted,
}: {
  session: Improvement;
  round: ImprovementIteration;
  hunks: Hunk[];
  included: string[];
  onChange: (ids: string[]) => void;
  onStarted: () => void;
}) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const actions = useImprovement(session.agent_id, session.id);
  const { evidence } = useImprovementEvidence(session.agent_id, { sessionId: session.id });
  const conversations = Object.fromEntries(
    (evidence?.items ?? []).map((item) => [item.run_id, item.conversation_id]),
  );
  const [quoted, setQuoted] = useState<{ key: string; quote: SelectionEstimate } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = JSON.stringify({
    ids: [...included].sort(),
    source: hunks.map((h) => [h.id, h.status, h.new_text, h.new_value]),
    round: round.candidate_spec_hash,
  });
  const quote = quoted?.key === key ? quoted.quote : null;
  const canSelect =
    session.can_restart !== false && (session.status === "ready" || session.status === "stopped");
  async function act(action: () => Promise<void>) {
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(getErrorMessage(e, tErrors));
    }
  }
  return (
    <section className="space-y-4">
      <h2 className="font-medium">
        <RoundTitle session={session} round={round} />
      </h2>
      <Tiles
        tiles={[
          { label: t("widgets.proposed"), value: hunks.length, tone: "indigo", icon: FilePen },
          {
            label: t("widgets.included"),
            value: hunks.filter((hunk) => included.includes(hunk.id)).length,
            tone: "teal",
            icon: ListChecks,
          },
        ]}
      />
      {hunks.map((hunk, index) => (
        <div key={hunk.id} className="space-y-3">
          {hunk.status === "pending" && (
            <label className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={included.includes(hunk.id)}
                disabled={!canSelect || actions.checkSelection.isPending}
                aria-label={t("includeChange", { number: index + 1 })}
                onCheckedChange={(checked) =>
                  onChange(
                    checked === true
                      ? [...included, hunk.id]
                      : included.filter((id) => id !== hunk.id),
                  )
                }
              />
              {t("includeInTest")}
            </label>
          )}
          <ChangePreview hunk={hunk} conversations={conversations} />
          {hunk.expected_effect && (
            <div className="bg-success/5 border-success/30 flex items-start gap-2 rounded-lg border p-3 text-sm">
              <Target className="text-success mt-0.5 size-4 shrink-0" aria-hidden />
              <div className="min-w-0">
                <h4 className="text-xs font-medium">{t("shouldFix")}</h4>
                <p className="break-words">{hunk.expected_effect}</p>
              </div>
            </div>
          )}
        </div>
      ))}
      {session.can_restart === false && (
        <p className="text-muted-foreground text-sm">{t("paidRestartOwner")}</p>
      )}
      {canSelect && (
        <div className="space-y-3 rounded-xl border p-4">
          <p className="text-muted-foreground text-sm">{t("selectionBody")}</p>
          {included.length === 0 && <p className="text-sm">{t("selectSomeChanges")}</p>}
          <Button
            className="h-auto min-h-9 text-left whitespace-normal"
            variant="outline"
            disabled={
              !included.length ||
              actions.estimateSelection.isPending ||
              actions.checkSelection.isPending
            }
            onClick={() =>
              void act(async () =>
                setQuoted({
                  key,
                  quote: await actions.estimateSelection.mutateAsync({
                    number: round.number,
                    hunkIds: included,
                  }),
                }),
              )
            }
          >
            {t("estimateSelection")}
          </Button>
          {quote && (
            <>
              <p className="text-sm">
                {t("selectionQuote", {
                  count: quote.suggestions,
                  cost: usd(quote.total_usd, locale),
                })}
              </p>
              <Button
                className="h-auto min-h-9 text-left whitespace-normal"
                disabled={!quote.affordable || actions.checkSelection.isPending}
                onClick={() =>
                  void act(async () => {
                    await actions.checkSelection.mutateAsync({
                      number: round.number,
                      hunkIds: included,
                      quote,
                    });
                    setQuoted(null);
                    onStarted();
                  })
                }
              >
                {t("confirmSelection")}
              </Button>
            </>
          )}
        </div>
      )}
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
    </section>
  );
}
