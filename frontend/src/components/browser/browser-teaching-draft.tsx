"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Input, Label } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import type { useBrowserTeaching } from "@/hooks/use-browser-teaching";
import { useHydrated } from "@/hooks/use-hydrated";
import {
  clearTeachingAttempt,
  readTeachingAttempt,
  retainTeachingAttempt,
  teachingAttemptKey,
  type TeachingDraftAttempt,
} from "@/lib/browser-teaching-attempts";
import { isTeachingAudienceCurrent } from "@/lib/browser-teaching-api";
import { teachingBudgetValid } from "@/lib/browser-teaching-review";
import type { BrowserTeaching } from "@/types/browser-teaching";
import { TeachingError } from "./browser-teaching-status";

type DraftProps = {
  session: BrowserTeaching;
  state: ReturnType<typeof useBrowserTeaching>;
};
export function BrowserTeachingDraft(props: DraftProps) {
  const hydrated = useHydrated();
  return hydrated ? (
    <TeachingDraftForm
      key={teachingAttemptKey(props.state.audience, "propose", [props.session.id])}
      {...props}
    />
  ) : null;
}
function TeachingDraftForm({ session, state }: DraftProps) {
  const t = useTranslations("browserTeaching");
  const key = teachingAttemptKey(state.audience, "propose", [session.id]);
  const [initial] = useState(() => readTeachingAttempt<TeachingDraftAttempt>(key, "propose"));
  const [mode, setMode] = useState<"reviewed" | "assistant">("reviewed");
  const [budget, setBudget] = useState("");
  const [saved, setSaved] = useState(initial.attempt);
  const [blocked, setBlocked] = useState(initial.blocked);
  const [error, setError] = useState<unknown>(null);
  const busy = useRef(false);
  async function propose() {
    if (busy.current || blocked || (!saved && mode === "assistant" && !teachingBudgetValid(budget)))
      return;
    busy.current = true;
    setError(null);
    const attempt: TeachingDraftAttempt = saved ?? {
      kind: "propose",
      revision: session.revision,
      body: mode === "reviewed" ? { mode } : { mode, max_cost_usd: budget },
    };
    if (!saved && !retainTeachingAttempt(key, attempt)) {
      setBlocked(true);
      busy.current = false;
      return;
    }
    setSaved(attempt);
    try {
      await state.command.mutateAsync({
        action: "propose",
        session,
        revision: attempt.revision,
        body: attempt.body,
      });
      if (isTeachingAudienceCurrent(state.audience)) clearTeachingAttempt(key);
    } catch (failure) {
      if (isTeachingAudienceCurrent(state.audience)) {
        setError(failure);
        if (
          !saved &&
          failure instanceof ApiError &&
          [400, 401, 403, 404, 409, 422].includes(failure.status)
        ) {
          if (clearTeachingAttempt(key)) setSaved(null);
          else setBlocked(true);
        }
      }
    } finally {
      busy.current = false;
    }
  }
  return (
    <section
      data-tour="teaching-draft"
      className="space-y-3 rounded-lg border p-4"
      aria-label={t("draftTitle")}
    >
      <h2 className="font-medium">{t("draftTitle")}</h2>
      <p className="text-muted-foreground text-sm">{t("draftDescription")}</p>
      {blocked ? (
        <p role="alert" className="text-sm">
          {t("storageUnavailable")}
        </p>
      ) : saved ? (
        <div className="space-y-3">
          <p className="text-sm">{t("draftUncertain")}</p>
          <p className="text-muted-foreground text-sm">
            {saved.body.mode === "reviewed"
              ? t("reviewedNoModel")
              : t("savedAssistantBudget", { budget: saved.body.max_cost_usd })}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              disabled={state.query.isFetching || state.command.isPending}
              onClick={() => void state.refresh()}
            >
              {t("checkAgain")}
            </Button>
            <Button
              variant="outline"
              disabled={state.command.isPending}
              onClick={() => void propose()}
            >
              {t("retrySameDraft")}
            </Button>
          </div>
        </div>
      ) : (
        <>
          <fieldset className="space-y-2" role="radiogroup" aria-label={t("draftMode")}>
            <label className="flex items-start gap-2 text-sm">
              <input
                className="accent-primary mt-0.5 size-4"
                type="radio"
                name="teaching-draft-mode"
                value="reviewed"
                checked={mode === "reviewed"}
                onChange={() => setMode("reviewed")}
              />
              {t("reviewedNoModel")}
            </label>
            <label className="flex items-start gap-2 text-sm">
              <input
                className="accent-primary mt-0.5 size-4"
                type="radio"
                name="teaching-draft-mode"
                value="assistant"
                checked={mode === "assistant"}
                onChange={() => setMode("assistant")}
              />
              {t("assistantOptional")}
            </label>
          </fieldset>
          {mode === "assistant" && (
            <div className="space-y-1">
              <Label htmlFor="teaching-draft-budget">{t("assistantBudget")}</Label>
              <Input
                id="teaching-draft-budget"
                inputMode="decimal"
                value={budget}
                onChange={(event) => setBudget(event.target.value)}
              />
              <p className="text-muted-foreground text-xs">{t("assistantBudgetHelp")}</p>
              {budget && !teachingBudgetValid(budget) && (
                <p role="alert" className="text-destructive text-sm">
                  {t("invalidBudget")}
                </p>
              )}
            </div>
          )}
          <Button
            disabled={
              state.command.isPending || (mode === "assistant" && !teachingBudgetValid(budget))
            }
            onClick={() => void propose()}
          >
            {mode === "reviewed" ? t("createReviewedDraft") : t("createAssistantDraft")}
          </Button>
        </>
      )}
      {error != null && <TeachingError error={error} />}
    </section>
  );
}
