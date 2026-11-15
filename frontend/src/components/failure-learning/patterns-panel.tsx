"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Alert, AlertDescription, Badge, Button, Card, CardContent } from "@/components/ui";
import type { FailurePattern } from "@/lib/failure-learning-api";

import { TrackPatternForm } from "./track-pattern-form";

function patternLabel(pattern: FailurePattern): string {
  return pattern.agent_name ?? pattern.model ?? pattern.pattern_key;
}

/**
 * Mined patterns, with the caveats labelled, not hidden: per-model counts
 * are approximate, hangs with a fresh heartbeat are invisible, and a
 * down-rated answer's attribution is approximate. The mining's own notes
 * say the same in the API's English; the console translates them here.
 */
export function PatternsPanel({
  patterns,
  isLoading,
  error,
  canTrack,
  onTrack,
}: {
  patterns: FailurePattern[];
  isLoading: boolean;
  error: Error | null;
  canTrack: boolean;
  onTrack: (pattern: FailurePattern, input: { title: string; summary: string }) => void;
}) {
  const t = useTranslations("failureLearning");
  const [tracking, setTracking] = useState<FailurePattern | null>(null);

  if (isLoading) return <LoadingState variant="skeleton-list" />;
  if (error) return <ErrorState />;
  if (patterns.length === 0) {
    return <EmptyState title={t("noPatterns")} description={t("noPatternsHint")} />;
  }
  return (
    <div className="space-y-4">
      <Alert>
        <AlertDescription>
          {t("caveatModel")} {t("caveatHang")} {t("caveatDownrated")}
        </AlertDescription>
      </Alert>
      <p className="text-muted-foreground text-sm">
        {t("patternCount", { count: patterns.length })}
      </p>
      <div className="space-y-3">
        {patterns.map((pattern) => (
          <Card key={`${pattern.agent_id ?? "model"}-${pattern.pattern_key}`}>
            <CardContent className="flex flex-wrap items-center gap-3 p-4">
              <div className="min-w-0 flex-1">
                <p className="font-medium break-words">{patternLabel(pattern)}</p>
                <p className="text-muted-foreground text-sm">
                  {pattern.status} · {pattern.error_class} ·{" "}
                  {t("occurrences", { count: pattern.count })}
                  {pattern.first_seen ? ` · ${pattern.first_seen.slice(0, 10)}` : ""}
                </p>
              </div>
              {pattern.already_tracked && <Badge variant="secondary">{t("alreadyTracked")}</Badge>}
              {canTrack && !pattern.already_tracked && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setTracking(pattern)}
                >
                  {t("track")}
                </Button>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
      {tracking && (
        <TrackPatternForm
          pattern={tracking}
          onSubmit={(input) => {
            onTrack(tracking, input);
            setTracking(null);
          }}
          onCancel={() => setTracking(null)}
        />
      )}
    </div>
  );
}
