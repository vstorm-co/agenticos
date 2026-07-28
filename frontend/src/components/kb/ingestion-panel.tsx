"use client";

import type { ReactNode } from "react";
import { Lock, SlidersHorizontal } from "lucide-react";

import { Button } from "@/components/ui";
import {
  CHUNKING_STRATEGIES,
  LLAMAPARSE_TIERS,
  PDF_PARSERS,
  labelOf,
} from "@/lib/ingestion-config";
import type { KnowledgeBase } from "@/types";

interface IngestionPanelProps {
  kb: KnowledgeBase;
  onEdit: () => void;
}

/**
 * What produced this collection.
 *
 * Stated rather than shown as controls, and read from the collection rather than
 * from any default: somebody looking at a set of answers needs to know what read
 * the documents behind them, and that question is asked far more often than the
 * settings are changed. The one control is the way to the form.
 *
 * The embedding model is the exception that proves the rule — it is here as a
 * fact and nowhere as a control, because it cannot be changed at all.
 */
export function IngestionPanel({ kb, onEdit }: IngestionPanelProps) {
  const config = kb.ingestion_config;

  return (
    // Named, so the facts inside are read as belonging to it rather than to the
    // page — and so a spec can ask this panel what it says.
    <section
      aria-labelledby="kb-ingestion-heading"
      className="border-border bg-card rounded-xl border"
    >
      <div className="flex items-center justify-between gap-2 border-b px-4 py-3">
        <h2 id="kb-ingestion-heading" className="text-foreground text-sm font-semibold">
          How documents are read
        </h2>
        <Button variant="outline" size="sm" onClick={onEdit}>
          <SlidersHorizontal className="h-4 w-4" />
          Edit
        </Button>
      </div>

      <dl className="divide-border divide-y">
        <Fact term="PDF parser">
          {labelOf(PDF_PARSERS, config.pdf_parser)}
          {config.pdf_parser === "llamaparse" &&
            ` · ${labelOf(LLAMAPARSE_TIERS, config.llamaparse_tier)}`}
          {config.pdf_parser === "liteparse" && ` · ${config.ocr_language.trim()}`}
        </Fact>

        <Fact term="Scanned pages">{config.ocr ? "Read as images" : "Not read"}</Fact>

        <Fact term="Chunking">
          {config.chunk_size.toLocaleString()} characters, {config.chunk_overlap.toLocaleString()}{" "}
          overlapping · {labelOf(CHUNKING_STRATEGIES, config.chunking_strategy)}
        </Fact>

        <Fact term="Images">
          {config.describe_images
            ? "Described by a model and indexed"
            : "Not described — a picture of a table is not searchable"}
        </Fact>

        {/*
          Last, and marked, because it is the only line here that no form can
          change. `PgVectorStore` writes `embedding vector(N)` once when the
          collection is made; two models of the same width write into different
          spaces that search would go on comparing and go on answering from.
        */}
        <Fact
          term="Embeddings"
          note="What this collection was indexed with, recorded when it was created. It cannot be changed — vectors written by two different models are not comparable, so a collection that needs another one is a new collection."
        >
          <span className="inline-flex items-center gap-1.5">
            <Lock className="text-muted-foreground h-3 w-3 shrink-0" aria-hidden />
            <span className="font-mono text-xs">{kb.embedding_model}</span>
            <span className="text-muted-foreground">
              · {kb.embedding_dim.toLocaleString()} dimensions
            </span>
          </span>
        </Fact>
      </dl>
    </section>
  );
}

function Fact({ term, note, children }: { term: string; note?: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 px-4 py-3 sm:grid-cols-[10rem_1fr] sm:gap-4">
      <dt className="text-muted-foreground text-xs">{term}</dt>
      <dd className="text-foreground min-w-0 text-sm">
        {children}
        {note && <p className="text-muted-foreground mt-1 text-xs leading-relaxed">{note}</p>}
      </dd>
    </div>
  );
}
