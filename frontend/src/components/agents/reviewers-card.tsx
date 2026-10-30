"use client";

import { Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { ModelProfilePicker } from "@/components/agents/model-profile-picker";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Textarea,
} from "@/components/ui";
import { useModelProviders } from "@/hooks";
import { usableForAgents } from "@/lib/model-profiles";
import type { RunReviewerSpec } from "@/types/agents";

/** The spec's ceiling, so the button goes before the publish refusal would. */
const MAX_REVIEWERS = 5;

interface ReviewersCardProps {
  value: RunReviewerSpec[] | undefined;
  onChange: (next: RunReviewerSpec[]) => void;
  disabled?: boolean;
}

/**
 * Second models that review a run while it goes, and steer it (#2106).
 *
 * Beside the limits, because both decide what a run may cost and how it ends:
 * a reviewer's calls are budgeted like the run's own. One per concern - "claims
 * without a source", "work nobody asked for" - each with its own name, which is
 * what its corrections are attributed to.
 */
export function ReviewersCard({ value, onChange, disabled }: ReviewersCardProps) {
  const t = useTranslations("agents");
  const reviewers = value ?? [];
  const { profiles, profilesStatus } = useModelProviders();
  const update = (index: number, patch: Partial<RunReviewerSpec>) =>
    onChange(
      reviewers.map((reviewer, at) => (at === index ? { ...reviewer, ...patch } : reviewer)),
    );
  // Saved as a draft straight away - the spec takes a reviewer with no model
  // or focus yet, and publishing says what is missing - under a name no other
  // reviewer has, since corrections are attributed by it.
  const add = () =>
    onChange([
      ...reviewers,
      {
        name: unusedName(reviewers),
        model_profile_id: profiles.find(usableForAgents)?.id ?? null,
        instructions: "",
        every: 10,
        window: 20_000,
      },
    ]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("reviewersTitle")}</CardTitle>
        <CardDescription>{t("reviewersDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {reviewers.map((reviewer, index) => (
          <div key={index} className="bg-muted/40 space-y-3 rounded-xl p-3">
            <div className="flex items-end gap-2">
              <div className="flex-1 space-y-1.5">
                <Label htmlFor={`reviewer-name-${index}`}>{t("reviewerName")}</Label>
                <Input
                  id={`reviewer-name-${index}`}
                  value={reviewer.name}
                  disabled={disabled}
                  onChange={(event) => update(index, { name: event.target.value })}
                />
              </div>
              <Button
                variant="ghost"
                size="icon"
                disabled={disabled}
                aria-label={t("removeReviewer", { name: reviewer.name })}
                onClick={() => onChange(reviewers.filter((_, at) => at !== index))}
              >
                <Trash2 className="size-4" aria-hidden />
              </Button>
            </div>
            <div className="space-y-1.5">
              <Label>{t("reviewerModel")}</Label>
              <ModelProfilePicker
                profiles={profiles}
                profilesStatus={profilesStatus}
                value={reviewer.model_profile_id}
                disabled={disabled}
                onChange={(id) => update(index, { model_profile_id: id })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={`reviewer-instructions-${index}`}>{t("reviewerInstructions")}</Label>
              <Textarea
                id={`reviewer-instructions-${index}`}
                value={reviewer.instructions}
                placeholder={t("reviewerInstructionsPlaceholder")}
                disabled={disabled}
                onChange={(event) => update(index, { instructions: event.target.value })}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <NumberField
                id={`reviewer-every-${index}`}
                label={t("reviewerEvery")}
                value={reviewer.every}
                min={1}
                max={100}
                disabled={disabled}
                onChange={(every) => update(index, { every })}
              />
              <NumberField
                id={`reviewer-window-${index}`}
                label={t("reviewerWindow")}
                value={reviewer.window}
                min={1000}
                max={200000}
                disabled={disabled}
                onChange={(window) => update(index, { window })}
              />
            </div>
          </div>
        ))}
        {reviewers.length < MAX_REVIEWERS && (
          <Button variant="outline" size="sm" disabled={disabled} onClick={add}>
            <Plus className="size-4" aria-hidden />
            {t("addReviewer")}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

/** `reviewer-N` for the smallest N no reviewer is already called. */
function unusedName(reviewers: RunReviewerSpec[]): string {
  const taken = new Set(reviewers.map((reviewer) => reviewer.name));
  let n = 1;
  while (taken.has(`reviewer-${n}`)) n += 1;
  return `reviewer-${n}`;
}

function NumberField(props: {
  id: string;
  label: string;
  value: number;
  min: number;
  max: number;
  disabled?: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={props.id}>{props.label}</Label>
      <Input
        id={props.id}
        type="number"
        min={props.min}
        max={props.max}
        value={props.value}
        disabled={props.disabled}
        onChange={(event) => props.onChange(Number(event.target.value) || props.min)}
      />
    </div>
  );
}
