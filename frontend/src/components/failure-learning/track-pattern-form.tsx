"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Textarea,
} from "@/components/ui";
import type { FailurePattern } from "@/lib/failure-learning-api";

/** Curate a pattern: a human accepts it as real and writes why, in one paragraph. */
export function TrackPatternForm({
  pattern,
  onSubmit,
  onCancel,
}: {
  pattern: FailurePattern;
  onSubmit: (input: { title: string; summary: string }) => void;
  onCancel: () => void;
}) {
  const t = useTranslations("failureLearning");
  const defaultTitle = t("trackTitleDefault", {
    errorClass: pattern.error_class,
    name: pattern.agent_name ?? pattern.model ?? pattern.pattern_key,
  }).trim();
  const [title, setTitle] = useState(defaultTitle);
  const [summary, setSummary] = useState("");

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("trackTitle")}</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit({ title: title.trim(), summary: summary.trim() });
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="track-title">{t("trackTitleLabel")}</Label>
            <Input
              id="track-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder={t("trackTitlePlaceholder")}
              maxLength={120}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="track-summary">{t("trackSummaryLabel")}</Label>
            <Textarea
              id="track-summary"
              value={summary}
              onChange={(event) => setSummary(event.target.value)}
              placeholder={t("trackSummaryPlaceholder")}
              required
            />
          </div>
          <div className="flex gap-2">
            <Button type="submit" disabled={title.trim() === "" || summary.trim() === ""}>
              {t("create")}
            </Button>
            <Button type="button" variant="outline" onClick={onCancel}>
              {t("cancel")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
