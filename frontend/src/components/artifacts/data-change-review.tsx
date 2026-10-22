"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertTriangle } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import {
  QueryInWords,
  condition,
  fieldInWords,
  order,
} from "@/components/artifacts/consent-disclosure";
import { ErrorState, LoadingState } from "@/components/states";
import { Alert, AlertDescription, Badge, Button, Label, Switch } from "@/components/ui";
import { useVersionReview } from "@/hooks/use-artifact-requests";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type {
  BindingChange,
  BindingParts,
  BindingReview,
  ChangeEffect,
  ChangeValue,
} from "@/types/artifact";

type Translate = ReturnType<typeof useTranslations>;
type Field = BindingParts["fields"][number];
type Filter = BindingParts["filters"][number];

/** A change's side in words: the condition, order or field it names, or the label itself. */
function valueInWords(
  t: Translate,
  types: Translate,
  aspect: BindingChange["aspect"],
  value: ChangeValue | null,
) {
  if (value === null) return "";
  switch (aspect) {
    case "field":
      return fieldInWords(t, types, value as Field);
    case "filter":
      return condition(t, value as Filter);
    case "sort":
      return order(t, value as BindingParts["sort"]);
    default:
      return String(value);
  }
}

const EFFECT_STYLE: Record<ChangeEffect, string> = {
  widens: "border-warning/50 bg-warning/10",
  narrows: "border-brand-line bg-brand-subtle",
  neutral: "",
};

function ChangeLine({ change }: { change: BindingChange }) {
  const t = useTranslations("artifacts.consent");
  const tReview = useTranslations("artifacts.review");
  const types = useTranslations("tables.schema.types");
  return (
    <li
      className={cn(
        "flex flex-wrap items-center gap-2 rounded border px-2 py-1",
        EFFECT_STYLE[change.effect],
      )}
    >
      <Badge variant={change.effect === "widens" ? "warning" : "outline"}>
        {tReview("effect", { effect: change.effect })}
      </Badge>
      <span>
        {tReview("change", {
          aspect: change.aspect,
          change: change.change,
          before: valueInWords(t, types, change.aspect, change.before),
          after: valueInWords(t, types, change.aspect, change.after),
        })}
      </span>
    </li>
  );
}

function BindingBlock({ binding }: { binding: BindingReview }) {
  const tReview = useTranslations("artifacts.review");
  return (
    <li className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 font-medium">
        {tReview("binding", { name: binding.name, change: binding.change })}
        <Badge variant={binding.effect === "widens" ? "warning" : "outline"}>
          {tReview("effect", { effect: binding.effect })}
        </Badge>
      </div>
      {binding.change === "added" && binding.parts !== null && (
        <ul>
          <QueryInWords name={binding.name} query={binding.parts} />
        </ul>
      )}
      {binding.change === "removed" && binding.parts !== null && (
        <p className="text-muted-foreground">
          {tReview("removedReads", { table: binding.parts.table })}
        </p>
      )}
      {binding.changes.length > 0 && (
        <ul className="space-y-1">
          {binding.changes.map((change, index) => (
            <ChangeLine key={`${change.aspect}-${index}`} change={change} />
          ))}
        </ul>
      )}
    </li>
  );
}

interface DataChangeReviewProps {
  artifactId: string;
  /** The version the request is about. */
  versionId: string;
  /** What approving confirms: the page queries the request was made against. */
  fingerprint: string | null;
  /** The audience's version is shown in the page's frame instead of this one. */
  audienceShown: boolean;
  /** `number` is the audience's version, which the page's frame is switched to. */
  onAudienceShown: (shown: boolean, number: number | null) => void;
  /** Whether the audience's version is among the versions the frame can show. */
  audienceAvailable: (number: number) => boolean;
  /** Confirms the version's data; rejects with the server's refusal. */
  onApprove: (fingerprint: string) => Promise<unknown>;
  onDecline: () => void;
  onClose: () => void;
  pending: boolean;
}

/**
 * Review data change: what a version's page queries read that the audience's
 * version did not, binding by binding - a widening marked, a narrowing plain, a new
 * binding in full, the unchanged ones folded away - with who published it and when.
 *
 * It sits under the page's strip rather than over the page, so the toggle that
 * switches the frame to what the audience sees now shows the difference. Approve
 * is Confirm data with the request's fingerprint: a republish or a changed query
 * in between is refused (409) rather than confirmed unseen.
 */
export function DataChangeReview({
  artifactId,
  versionId,
  fingerprint,
  audienceShown,
  onAudienceShown,
  audienceAvailable,
  onApprove,
  onDecline,
  onClose,
  pending,
}: DataChangeReviewProps) {
  const t = useTranslations("artifacts.review");
  const tErrors = useTranslations("errors");
  const format = useFormatter();
  const review = useVersionReview(artifactId, versionId, true);
  const [refusal, setRefusal] = useState<string | null>(null);
  const shown = review.data;

  const approve = async (seen: string) => {
    try {
      await onApprove(seen);
      onClose();
    } catch (error) {
      // A newer version or moved queries: the mutation has told the person and read
      // the page again, so the panel closes to let them look at what is there now.
      if (error instanceof ApiError && error.status === 409) {
        onClose();
        return;
      }
      setRefusal(getErrorMessage(error, tErrors));
    }
  };

  return (
    <section
      aria-label={t("title")}
      className="max-h-[45vh] shrink-0 space-y-3 overflow-y-auto border-b px-3 py-3 text-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">
          {shown === undefined
            ? t("titleUnnumbered")
            : t("titleVersion", { version: shown.version.number })}
        </h2>
        <Button size="sm" variant="ghost" onClick={onClose}>
          {t("close")}
        </Button>
      </div>
      {review.isLoading ? (
        <LoadingState variant="skeleton-panel" rows={3} />
      ) : shown === undefined ? (
        <ErrorState title={t("failed")} />
      ) : (
        <>
          <p className="text-muted-foreground">
            {t("published", {
              name: shown.publisher_name ?? "",
              when: format.dateTime(new Date(shown.version.created_at), {
                dateStyle: "medium",
                timeStyle: "short",
              }),
            })}{" "}
            {shown.version.run_id !== null && (
              <Link className="underline" href={`${ROUTES.RUNS}?run=${shown.version.run_id}`}>
                {t("conversation")}
              </Link>
            )}
          </p>
          {shown.problem !== null && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{shown.problem}</AlertDescription>
            </Alert>
          )}
          <p>
            {shown.compared_to === null
              ? t("comparedToNothing")
              : t("comparedTo", { version: shown.compared_to })}
          </p>
          {shown.compared_to !== null && (
            <div className="flex flex-wrap items-center gap-2">
              <Switch
                id="artifact-review-audience"
                checked={audienceShown}
                disabled={!audienceAvailable(shown.compared_to)}
                onCheckedChange={(on) => onAudienceShown(on, shown.compared_to)}
              />
              <Label htmlFor="artifact-review-audience">{t("audienceSeesNow")}</Label>
              {!audienceAvailable(shown.compared_to) && (
                <span className="text-muted-foreground text-xs">{t("audienceUnavailable")}</span>
              )}
            </div>
          )}
          {shown.bindings.length === 0 ? (
            <p className="text-muted-foreground">{t("nothingChanged")}</p>
          ) : (
            <ul className="space-y-3">
              {shown.bindings.map((binding) => (
                <BindingBlock key={binding.name} binding={binding} />
              ))}
            </ul>
          )}
          {shown.unchanged.length > 0 && (
            <details>
              <summary className="text-muted-foreground cursor-pointer">
                {t("unchanged", { count: shown.unchanged.length })}
              </summary>
              <p className="pt-1">{shown.unchanged.join(", ")}</p>
            </details>
          )}
        </>
      )}
      {refusal !== null && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{refusal}</AlertDescription>
        </Alert>
      )}
      <div className="flex gap-2">
        <Button
          size="sm"
          disabled={pending || fingerprint === null || shown === undefined}
          onClick={fingerprint === null ? undefined : () => void approve(fingerprint)}
        >
          {t("approve")}
        </Button>
        <Button size="sm" variant="outline" disabled={pending} onClick={onDecline}>
          {t("decline")}
        </Button>
      </div>
    </section>
  );
}
