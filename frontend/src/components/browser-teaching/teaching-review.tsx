"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { Badge, Button, Card, CardContent, FormField, Input } from "@/components/ui";
import type { BrowserTeaching, ReviewedStep } from "@/lib/browser-teaching-api";
import { ROUTES } from "@/lib/constants";
import { TeachingStepRow } from "./teaching-step-row";

interface TeachingReviewProps {
  teaching: BrowserTeaching;
  isSaving: boolean;
  isProposing: boolean;
  saveReview: (steps: ReviewedStep[]) => Promise<BrowserTeaching | undefined>;
  propose: (name: string, base?: BrowserTeaching) => Promise<void>;
}

const NAME_ID = "teaching-skill-name";

/**
 * Review a stopped recording: label each step, name case-specific inputs as
 * parameters, then ask for one skill proposal built from that review alone.
 *
 * The draft lives only in this component, so the page keys it on the reader's
 * identity and a switch of person or organization starts from nothing.
 */
export function TeachingReview({
  teaching,
  isSaving,
  isProposing,
  saveReview,
  propose,
}: TeachingReviewProps) {
  const t = useTranslations("browserTeaching");
  const [draft, setDraft] = useState(() => initialDraft(teaching));
  const [name, setName] = useState(() => toSkillName(teaching.title));
  const editable = teaching.status === "review";
  const busy = isSaving || isProposing || !editable;
  const steps = Object.values(draft).filter(
    (step) => step.label !== null || step.parameter !== null,
  );

  const submit = async () => {
    const saved = await saveReview(steps);
    if (saved !== undefined) await propose(toSkillName(name), saved);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={editable ? "secondary" : "outline"}>{t(`status.${teaching.status}`)}</Badge>
        {teaching.allowed_origins.map((origin) => (
          <Badge key={origin} variant="outline" className="font-mono">
            {origin}
          </Badge>
        ))}
      </div>
      {teaching.reason_code !== null && (
        <p className="text-destructive text-sm" role="alert">
          {t.has(`reasons.${teaching.reason_code}`)
            ? t(`reasons.${teaching.reason_code}`)
            : t("reasons.other")}
        </p>
      )}
      {teaching.status === "proposed" ? (
        <div className="space-y-2">
          <p className="text-sm">{t("proposed", { name: teaching.proposal_name ?? "" })}</p>
          <Button asChild variant="outline" size="sm">
            <Link href={ROUTES.SKILLS}>{t("openProposals")}</Link>
          </Button>
        </div>
      ) : (
        <Card>
          <CardContent className="p-0">
            <ol className="divide-border divide-y">
              {teaching.events.map((step) => (
                <TeachingStepRow
                  key={step.sequence}
                  step={step}
                  draft={draft[step.sequence] ?? blank(step.sequence)}
                  disabled={busy}
                  onChange={(next) => setDraft({ ...draft, [step.sequence]: next })}
                />
              ))}
            </ol>
          </CardContent>
        </Card>
      )}
      {editable && (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <FormField htmlFor={NAME_ID} label={t("skillName")} className="sm:max-w-xs sm:flex-1">
            <Input
              value={name}
              maxLength={64}
              className="font-mono"
              onChange={(event) => setName(toSkillName(event.target.value, true))}
            />
          </FormField>
          <div className="flex gap-2">
            <Button variant="outline" disabled={busy} onClick={() => void saveReview(steps)}>
              {t("saveReview")}
            </Button>
            <Button disabled={busy || name === ""} onClick={() => void submit()}>
              {t("propose")}
            </Button>
          </div>
        </div>
      )}
      {teaching.status === "proposing" && (
        <p className="text-muted-foreground text-sm" role="status">
          {t("proposing")}
        </p>
      )}
    </div>
  );
}

function blank(sequence: number): ReviewedStep {
  return { sequence, label: null, parameter: null };
}

function initialDraft(teaching: BrowserTeaching): Record<number, ReviewedStep> {
  return Object.fromEntries(teaching.review.map((step) => [step.sequence, step]));
}

/** The skill name the server takes: lower case words joined by hyphens. */
export function toSkillName(value: string, typing = false): string {
  const name = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+/, "");
  return (typing ? name : name.replace(/-+$/, "")).slice(0, 64);
}
