"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Button, Textarea } from "@/components/ui";
import type { NoteTarget } from "@/hooks/use-scoring";
import { cn } from "@/lib/utils";

/** A review decision as the card hands it back: pass, fail, or `null` to withdraw one. */
export type Verdict = { passed: boolean | null; note: string | null };

interface ScoreDecisionProps {
  /** The decision on record, if somebody made one. */
  decided: boolean | null;
  caseTags?: string[];
  note: string | null;
  onVerdict?: (verdict: Verdict) => void;
  /** Shown while the score is not in the queue and may be sent there. */
  onReview?: () => void;
  /** Makes the note on record a judge criterion, for this case or every case. */
  onNoteToCriterion?: (target: NoteTarget) => void;
  busy: boolean;
}

/** A person's review decision on a score, with the note that says why. */
export function ScoreDecision({
  decided,
  caseTags = [],
  note,
  onVerdict,
  onReview,
  onNoteToCriterion,
  busy,
}: ScoreDecisionProps) {
  const t = useTranslations("datasets.scoring");
  const [written, setWritten] = useState(note ?? "");
  const decide = (passed: boolean | null) =>
    onVerdict?.({ passed, note: passed === null || written.trim() === "" ? null : written });

  return (
    <footer className={cn("space-y-2 border-t pt-3", busy && "opacity-60")}>
      <p className="text-xs font-medium">{t("decision")}</p>
      {!onVerdict && note && <p className="text-sm">{note}</p>}
      {onVerdict && (
        <>
          <Textarea
            value={written}
            onChange={(event) => setWritten(event.target.value)}
            placeholder={t("verdictNotePlaceholder")}
            aria-label={t("verdictNote")}
            rows={2}
          />
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" disabled={busy} onClick={() => decide(true)}>
              {t("markPassed")}
            </Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => decide(false)}>
              {t("markFailed")}
            </Button>
            {decided !== null && (
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => decide(null)}>
                {t("withdrawVerdict")}
              </Button>
            )}
          </div>
        </>
      )}
      {onNoteToCriterion && note && (
        <div className="text-muted-foreground flex flex-wrap items-center gap-1 text-xs">
          <span>{t("noteToCriterion")}</span>
          <Button
            variant="link"
            size="sm"
            className="h-auto px-1"
            disabled={busy}
            onClick={() => onNoteToCriterion("case")}
          >
            {t("noteForCase")}
          </Button>
          {caseTags.map((tag) => (
            <Button
              key={tag}
              variant="link"
              size="sm"
              className="h-auto px-1"
              disabled={busy}
              onClick={() => onNoteToCriterion({ tags: [tag] })}
            >
              {t("noteForTag", { tag })}
            </Button>
          ))}
          <Button
            variant="link"
            size="sm"
            className="h-auto px-1"
            disabled={busy}
            onClick={() => onNoteToCriterion("dataset")}
          >
            {t("noteForEveryCase")}
          </Button>
        </div>
      )}
      {onReview && (
        <Button size="sm" variant="ghost" disabled={busy} onClick={onReview}>
          {t("sendToReview")}
        </Button>
      )}
    </footer>
  );
}
