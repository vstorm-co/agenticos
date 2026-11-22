"use client";

import { useTranslations } from "next-intl";

/** A stable hint while empty, including when the editor receives focus. */
export function ComposerHints() {
  const t = useTranslations("chat.hints");
  return (
    <span
      aria-hidden
      data-testid="composer-hints"
      className="text-muted-foreground pointer-events-none absolute inset-x-0 top-0 py-(--composer-padding) text-base"
    >
      {t.rich("shortcuts", { key: (chunks) => <span className="font-mono">{chunks}</span> })}
    </span>
  );
}
