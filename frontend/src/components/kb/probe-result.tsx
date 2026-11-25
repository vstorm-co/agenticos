"use client";

import { useTranslations } from "next-intl";

import type { EmbeddingProbeResult } from "@/lib/embedding-probe-api";
import { cn } from "@/lib/utils";

/**
 * What a test found, in words: the width it measured, how many collections keep
 * their vectors, or which collection failed and why.
 *
 * A failure names each collection and its own cause rather than one verdict,
 * because a connection shared by several can fail on only one of them.
 */
export function ProbeResult({ result }: { result: EmbeddingProbeResult }) {
  const t = useTranslations("kb");
  const failed = result.knowledge_bases.filter(
    (entry) => entry.outcome !== "passed" && entry.outcome !== "no_chunks",
  );

  return (
    <div
      role="status"
      className={cn(
        "space-y-1 rounded-lg border p-3 text-sm",
        result.passed ? "border-border" : "border-destructive/50",
      )}
    >
      {result.passed ? (
        <>
          {result.dim !== null && <p>{t("measuredWidth", { dim: result.dim })}</p>}
          {(result.knowledge_bases.length > 0 || result.dim === null) && (
            <p>{t("probePassed", { count: result.knowledge_bases.length })}</p>
          )}
        </>
      ) : (
        <>
          <p className="text-destructive">{t(`probeOutcome.${result.outcome}`)}</p>
          {failed.length > 0 && (
            <ul className="text-muted-foreground list-disc space-y-0.5 pl-5 text-xs">
              {failed.map((entry) => (
                <li key={entry.knowledge_base_id}>
                  {entry.name}: {t(`probeOutcome.${entry.outcome}`)}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
