"use client";

import { Code2, Eye } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "./button";

export type MarkdownMode = "source" | "preview";

/** One action names the view it opens, leaving room for the document's title. */
export function MarkdownModeToggle({
  mode,
  onChange,
}: {
  mode: MarkdownMode;
  onChange: (mode: MarkdownMode) => void;
}) {
  const t = useTranslations("ui");
  const next = mode === "source" ? "preview" : "source";
  const Icon = next === "preview" ? Eye : Code2;
  return (
    <Button type="button" variant="outline" size="sm" onClick={() => onChange(next)}>
      <Icon aria-hidden />
      {t(next)}
    </Button>
  );
}
