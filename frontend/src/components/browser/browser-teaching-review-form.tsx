"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Checkbox, Input, Label, Textarea } from "@/components/ui";
import type { useBrowserTeaching } from "@/hooks/use-browser-teaching";
import { isTeachingAudienceCurrent } from "@/lib/browser-teaching-api";
import {
  clearTeachingAttempt,
  readTeachingAttempt,
  teachingAttemptKey,
  type TeachingDraftAttempt,
} from "@/lib/browser-teaching-attempts";
import {
  initialTeachingReview,
  teachingReviewIssue,
  type TeachingReviewIssue,
} from "@/lib/browser-teaching-review";
import type { BrowserTeaching, TeachingReview } from "@/types/browser-teaching";
import { TeachingError } from "./browser-teaching-status";
import { BrowserTeachingDraft } from "./browser-teaching-draft";

type TeachingState = ReturnType<typeof useBrowserTeaching>;
export function BrowserTeachingReviewForm({
  session,
  state,
}: {
  session: BrowserTeaching;
  state: TeachingState;
}) {
  const t = useTranslations("browserTeaching");
  const [review, setReview] = useState(() => initialTeachingReview(session));
  const [events, setEvents] = useState(session.events);
  const [baseRevision, setBaseRevision] = useState(session.revision);
  const [issue, setIssue] = useState<TeachingReviewIssue | null>(null);
  const [dirty, setDirty] = useState(false);
  const [settlementBlocked, setSettlementBlocked] = useState(false);
  const stale = baseRevision !== session.revision;
  const busy = state.command.isPending;
  function edit(next: TeachingReview) {
    setReview(next);
    setDirty(true);
    setIssue(null);
  }
  async function save() {
    const problem = teachingReviewIssue(session, review);
    setIssue(problem);
    if (problem || stale || busy) return;
    const attemptKey = teachingAttemptKey(state.audience, "propose", [session.id]);
    const saved = readTeachingAttempt<TeachingDraftAttempt>(attemptKey, "propose");
    try {
      const next = await state.command.mutateAsync({
        action: "change",
        session,
        body: { action: "review", review },
      });
      if (!isTeachingAudienceCurrent(state.audience)) return;
      let blocked = false;
      if (
        saved.attempt &&
        next.generation_state === "none" &&
        next.revision > session.revision &&
        next.revision > saved.attempt.revision
      ) {
        // Review and Draft share the server row lock. Only this acknowledged
        // newer review fences the captured tuple; an uncertain PATCH does not.
        const retained = readTeachingAttempt<TeachingDraftAttempt>(attemptKey, "propose");
        blocked = retained.blocked;
        if (JSON.stringify(retained.attempt) === JSON.stringify(saved.attempt))
          blocked = !clearTeachingAttempt(attemptKey);
      }
      setSettlementBlocked(blocked);
      setReview(initialTeachingReview(next));
      setEvents(next.events);
      setBaseRevision(next.revision);
      setDirty(false);
    } catch {
      /* Fixed refusal stays alongside the form. */
    }
  }
  return (
    <section className="space-y-5" aria-label={t("reviewSteps")} data-tour="teaching-review">
      <div>
        <h2 className="text-lg font-medium">{t("reviewSteps")}</h2>
        <p className="text-muted-foreground mt-1 text-sm">{t("reviewDescription")}</p>
      </div>
      {stale && (
        <div role="alert" className="space-y-2 rounded-lg border p-3">
          <p className="text-sm">{t("revisionChanged")}</p>
          <Button
            variant="outline"
            onClick={() => {
              setReview(initialTeachingReview(session));
              setEvents(session.events);
              setBaseRevision(session.revision);
              setDirty(false);
              setIssue(null);
            }}
          >
            {t("reloadReview")}
          </Button>
        </div>
      )}
      <fieldset disabled={busy || stale} className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1">
            <Label htmlFor="teaching-skill-name">{t("skillName")}</Label>
            <Input
              id="teaching-skill-name"
              value={review.name}
              maxLength={64}
              onChange={(event) => edit({ ...review, name: event.target.value })}
            />
            <p className="text-muted-foreground text-xs">{t("skillNameHelp")}</p>
          </div>
          <div className="space-y-1">
            <Label htmlFor="teaching-description">{t("skillDescription")}</Label>
            <Textarea
              id="teaching-description"
              value={review.description}
              maxLength={500}
              onChange={(event) => edit({ ...review, description: event.target.value })}
            />
          </div>
        </div>
        <div className="space-y-3">
          <h3 className="font-medium">{t("parametersTitle")}</h3>
          <p className="text-muted-foreground text-sm">{t("parametersHelp")}</p>
          {review.parameters.map((parameter, index) => (
            <div
              key={index}
              className="grid gap-2 rounded-lg border p-3 sm:grid-cols-[1fr_2fr_auto]"
            >
              <div className="space-y-1">
                <Label htmlFor={`teaching-parameter-${index}`}>
                  {t("parameterName", { number: index + 1 })}
                </Label>
                <Input
                  id={`teaching-parameter-${index}`}
                  value={parameter.name}
                  maxLength={32}
                  onChange={(event) =>
                    edit({
                      ...review,
                      parameters: review.parameters.map((item, at) =>
                        at === index ? { ...item, name: event.target.value } : item,
                      ),
                    })
                  }
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor={`teaching-parameter-description-${index}`}>
                  {t("parameterDescription", { number: index + 1 })}
                </Label>
                <Input
                  id={`teaching-parameter-description-${index}`}
                  value={parameter.description}
                  maxLength={240}
                  onChange={(event) =>
                    edit({
                      ...review,
                      parameters: review.parameters.map((item, at) =>
                        at === index ? { ...item, description: event.target.value } : item,
                      ),
                    })
                  }
                />
              </div>
              <Button
                variant="ghost"
                className="self-end"
                onClick={() =>
                  edit({ ...review, parameters: review.parameters.filter((_, at) => at !== index) })
                }
              >
                {t("removeParameter")}
              </Button>
            </div>
          ))}
          <Button
            variant="outline"
            disabled={review.parameters.length >= 50}
            onClick={() =>
              edit({ ...review, parameters: [...review.parameters, { name: "", description: "" }] })
            }
          >
            {t("addParameter")}
          </Button>
        </div>
        <ol className="space-y-4">
          {review.actions.map((action, index) => {
            // A saved review preserves every event in order; retain both snapshots together.
            const event = events[index]!;
            const change = (values: Partial<typeof action>) =>
              edit({
                ...review,
                actions: review.actions.map((item, at) =>
                  at === index ? { ...item, ...values } : item,
                ),
              });
            return (
              <li key={action.sequence} className="space-y-3 rounded-lg border p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="font-medium">
                      {t("stepNumber", { number: action.sequence })} · {t(`action.${event.action}`)}
                    </h3>
                    <p className="text-muted-foreground text-xs break-words">
                      {event.origin}
                      {event.target ? ` · ${t(`role.${event.target.role}`)}` : ""}
                    </p>
                    {event.human_step && (
                      <p className="text-muted-foreground mt-1 text-sm">{t("humanCheckpoint")}</p>
                    )}
                  </div>
                  <label className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={action.omit}
                      onCheckedChange={(checked) =>
                        change(
                          checked === true
                            ? { omit: true, parameter: null, path_template: null }
                            : { omit: false },
                        )
                      }
                    />
                    {t("omitStep", { number: action.sequence })}
                  </label>
                </div>
                <div className="space-y-1">
                  <Label htmlFor={`teaching-step-${action.sequence}`}>
                    {t("stepLabel", { number: action.sequence })}
                  </Label>
                  <Input
                    id={`teaching-step-${action.sequence}`}
                    value={action.label}
                    maxLength={160}
                    onChange={(event) => change({ label: event.target.value })}
                  />
                </div>
                {!action.omit &&
                  (event.action === "input_parameter" || event.action === "select") && (
                    <div className="space-y-1">
                      <Label htmlFor={`teaching-step-parameter-${action.sequence}`}>
                        {t("stepParameter", { number: action.sequence })}
                      </Label>
                      <Input
                        id={`teaching-step-parameter-${action.sequence}`}
                        value={action.parameter ?? ""}
                        maxLength={32}
                        onChange={(event) => change({ parameter: event.target.value || null })}
                      />
                    </div>
                  )}
                {!action.omit && event.action === "navigate" && (
                  <div className="space-y-1">
                    <Label htmlFor={`teaching-step-path-${action.sequence}`}>
                      {t("stepPath", { number: action.sequence })}
                    </Label>
                    <Input
                      id={`teaching-step-path-${action.sequence}`}
                      value={action.path_template ?? ""}
                      maxLength={512}
                      onChange={(event) => change({ path_template: event.target.value || null })}
                    />
                    <p className="text-muted-foreground text-xs">{t("pathHelp")}</p>
                  </div>
                )}
              </li>
            );
          })}
        </ol>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1">
            <Label htmlFor="teaching-prerequisites">{t("prerequisites")}</Label>
            <Textarea
              id="teaching-prerequisites"
              value={review.prerequisites.join("\n")}
              onChange={(event) =>
                edit({
                  ...review,
                  prerequisites: event.target.value ? event.target.value.split("\n") : [],
                })
              }
              rows={4}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="teaching-success">{t("successChecks")}</Label>
            <Textarea
              id="teaching-success"
              value={review.success_checks.join("\n")}
              onChange={(event) =>
                edit({ ...review, success_checks: event.target.value.split("\n") })
              }
              rows={4}
            />
          </div>
        </div>
        <p className="text-muted-foreground text-xs">{t("checksHelp")}</p>
        {issue && (
          <p role="alert" className="text-destructive text-sm">
            {t(`validation.${issue}`)}
          </p>
        )}
        <Button onClick={() => void save()}>{t("saveReview")}</Button>
      </fieldset>
      {state.command.error && <TeachingError error={state.command.error} />}
      {settlementBlocked && (
        <p role="alert" className="text-destructive text-sm">
          {t("storageUnavailable")}
        </p>
      )}
      {session.review &&
        session.generation_state === "none" &&
        !dirty &&
        !stale &&
        !settlementBlocked && (
          <BrowserTeachingDraft key={session.revision} session={session} state={state} />
        )}
    </section>
  );
}
