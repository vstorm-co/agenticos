"use client";

import { useEffect, useRef } from "react";
import { ArrowLeft, FileText, Globe, Link, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useSourcesPanelStore } from "@/stores/sources-panel-store";
import type { SourceItem } from "@/lib/chat-sources";
import { cn } from "@/lib/utils";

function ScoreDot({ score }: { score: number }) {
  const t = useTranslations("chat");
  const tone =
    score >= 0.7 ? "bg-foreground" : score >= 0.4 ? "bg-foreground/55" : "bg-foreground/25";
  return (
    <span
      className={cn("h-1.5 w-1.5 shrink-0 rounded-full", tone)}
      title={t("relevanceScore", { score: score.toFixed(2) })}
    />
  );
}

function RAGSourceRow({ item, highlighted }: { item: SourceItem; highlighted: boolean }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (highlighted) {
      ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [highlighted]);

  return (
    <div
      ref={ref}
      className={cn(
        "border-foreground/8 rounded-xl border p-3 transition-colors",
        highlighted && "border-foreground/30 bg-foreground/[0.04]",
      )}
    >
      <div className="flex items-start gap-2.5">
        <span className="bg-foreground/8 text-foreground/65 mt-0.5 inline-flex h-5 min-w-[1.5rem] shrink-0 items-center justify-center rounded px-1 font-mono text-xs tabular-nums">
          {item.index}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <FileText className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
            <p className="text-foreground truncate text-xs font-medium" title={item.title}>
              {item.title}
            </p>
            {item.score !== undefined && <ScoreDot score={item.score} />}
          </div>
          {item.subtitle && (
            <p className="text-muted-foreground mt-0.5 pl-5 font-mono text-xs tracking-wider uppercase">
              {item.subtitle}
            </p>
          )}
          {item.content && (
            <p className="text-foreground/60 mt-2 pl-5 text-xs leading-relaxed">{item.content}</p>
          )}
        </div>
      </div>
    </div>
  );
}

function WebSourceRow({ item, highlighted }: { item: SourceItem; highlighted: boolean }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (highlighted) {
      ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [highlighted]);

  const inner = (
    <div
      ref={ref}
      className={cn(
        "border-foreground/8 rounded-xl border p-3 transition-colors",
        highlighted && "border-foreground/30 bg-foreground/[0.04]",
        item.url && "hover:border-foreground/25 cursor-pointer",
      )}
    >
      <div className="flex items-start gap-2.5">
        <Globe className="text-muted-foreground mt-0.5 h-3.5 w-3.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="text-foreground truncate text-xs font-medium" title={item.title}>
            {item.title}
          </p>
          {item.subtitle && (
            <div className="text-muted-foreground mt-0.5 flex items-center gap-1 text-xs">
              <Link className="h-2.5 w-2.5 shrink-0" />
              {item.subtitle}
            </div>
          )}
          {item.content && (
            <p className="text-foreground/60 mt-2 line-clamp-3 text-xs leading-relaxed">
              {item.content}
            </p>
          )}
        </div>
      </div>
    </div>
  );

  if (item.url) {
    return (
      <a href={item.url} target="_blank" rel="noopener noreferrer">
        {inner}
      </a>
    );
  }
  return inner;
}

/**
 * The sources of an answer, over the side of the conversation they belong to.
 *
 * `contained` keeps it inside the conversation's own box - the Architect's
 * widget - instead of the page's right edge, where it opened beside a widget in
 * the corner, over whatever page that was.
 */
export function SourcesPanel({ contained = false }: { contained?: boolean }) {
  const t = useTranslations("chat");
  const { isOpen, sources, highlightedIndex, close } = useSourcesPanelStore();

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen, close]);

  if (!isOpen) return null;

  const ragSources = sources.filter((s) => s.type === "rag");
  const webSources = sources.filter((s) => s.type === "web");

  return (
    <div
      className={cn(
        "bg-background border-border flex flex-col",
        contained
          ? "absolute inset-0 z-40"
          : "fixed top-0 right-0 z-50 h-full w-[360px] border-l shadow-xl",
      )}
    >
      {/* Header. Inside a widget it is the widget's own back-arrow header, the
          one its conversation list wears; at the page's edge, a title and a
          close button. */}
      <div
        className={cn(
          "border-foreground/8 flex items-center gap-1.5 border-b",
          contained ? "px-2 py-2" : "justify-between px-4 py-3",
        )}
      >
        {contained && (
          <button
            type="button"
            onClick={close}
            aria-label={t("closeSourcesPanel")}
            title={t("closeSourcesPanel")}
            className="text-muted-foreground hover:text-foreground hover:bg-foreground/[0.05] rounded-md p-1.5"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
        )}
        <h2 className="text-foreground flex-1 text-sm font-semibold">
          {t("sourcesHeading")}
          <span className="text-muted-foreground ml-2 font-normal">({sources.length})</span>
        </h2>
        {!contained && (
          <button
            type="button"
            onClick={close}
            aria-label={t("closeSourcesPanel")}
            className="text-muted-foreground hover:text-foreground hover:bg-foreground/8 rounded-md p-1 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 scrollbar-thin space-y-5 overflow-y-auto px-4 py-4">
        {ragSources.length > 0 && (
          <section className="space-y-2">
            {ragSources.length > 0 && webSources.length > 0 && (
              <h3 className="text-muted-foreground font-mono text-xs tracking-wider uppercase">
                {t("knowledgeBase")}
              </h3>
            )}
            {ragSources.map((s) => (
              <RAGSourceRow
                key={`rag-${s.index}`}
                item={s}
                highlighted={s.index === highlightedIndex}
              />
            ))}
          </section>
        )}

        {webSources.length > 0 && (
          <section className="space-y-2">
            {ragSources.length > 0 && (
              <h3 className="text-muted-foreground font-mono text-xs tracking-wider uppercase">
                {t("web")}
              </h3>
            )}
            {webSources.map((s) => (
              <WebSourceRow
                key={`web-${s.index}`}
                item={s}
                highlighted={s.index === highlightedIndex}
              />
            ))}
          </section>
        )}
      </div>
    </div>
  );
}
