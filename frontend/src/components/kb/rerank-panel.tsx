"use client";

import { SlidersHorizontal } from "lucide-react";

import { Button } from "@/components/ui";
import { useSecrets } from "@/hooks";
import type { KnowledgeBase } from "@/types";
import { useTranslations } from "next-intl";

interface RerankPanelProps {
  kb: KnowledgeBase;
  /** Absent when the caller may not write - the panel is then facts only. */
  onEdit?: () => void;
}

/**
 * Whether this collection reranks its search results, and with what.
 *
 * A retrieval-time setting, so it is its own section rather than a line in "how
 * documents are read": that panel describes what was baked into the collection
 * at ingestion, this describes what happens to a query against it now, and the
 * two change on different days for different reasons.
 *
 * Reranking is configured (both a model and a key) or it is off; there is no
 * half state, because the backend resolves anything but a usable key to no
 * reranker. The key's name is resolved from the vault, and falls back to a
 * neutral label when the reader cannot list secrets (a `collections:edit`
 * holder need not hold `connections:manage`).
 */
export function RerankPanel({ kb, onEdit }: RerankPanelProps) {
  const t = useTranslations("kb");
  const { secrets } = useSecrets();
  const configured = Boolean(kb.rerank_model && kb.rerank_secret_id);
  const keyName = secrets.find((secret) => secret.id === kb.rerank_secret_id)?.name;

  return (
    <section
      aria-labelledby="kb-rerank-heading"
      className="border-border bg-card rounded-xl border"
    >
      <div className="flex items-center justify-between gap-2 border-b px-4 py-3">
        <h2 id="kb-rerank-heading" className="text-foreground text-sm font-semibold">
          {t("rerank")}
        </h2>
        {onEdit && (
          <Button variant="outline" size="sm" onClick={onEdit}>
            <SlidersHorizontal className="h-4 w-4" />
            {t("edit")}
          </Button>
        )}
      </div>

      <div className="px-4 py-3 text-sm">
        {configured ? (
          <div className="space-y-1">
            <span className="text-foreground inline-flex flex-wrap items-center gap-1.5">
              <span className="font-mono text-xs">{kb.rerank_model}</span>
              <span className="text-muted-foreground">
                {t("rerankBilledTo", { key: keyName ?? t("rerankKeyConfigured") })}
              </span>
            </span>
            <p className="text-muted-foreground text-xs leading-relaxed">
              {t("rerankOnExplained")}
            </p>
          </div>
        ) : (
          <p className="text-muted-foreground">{t("rerankOffExplained")}</p>
        )}
      </div>
    </section>
  );
}
