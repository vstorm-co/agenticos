"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ExternalLink, FileSearch, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { SourceViewer, type CitedFile } from "@/components/kb/source-viewer";
import { useKnowledgeBaseFor } from "@/hooks/use-knowledge-bases";
import { useSourcesPanelStore } from "@/stores/sources-panel-store";
import {
  sourceDocuments,
  sourceKey,
  type SourceDocument,
  type SourceItem,
} from "@/lib/chat-sources";
import { cn } from "@/lib/utils";

import { MarkdownContent } from "./markdown-content";
import { SourceMark } from "./source-mark";

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

/** Scrolls itself into view when it is the citation that was clicked. */
function useScrolledTo(highlighted: boolean) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (highlighted) ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [highlighted]);
  return ref;
}

/**
 * One passage of a file: its citation number, where in the file, and the words.
 *
 * Drawn as the markdown it was indexed from - a handbook's headings and lists,
 * not a run of `##` - and folded to a few lines until it is the one that was
 * cited, or somebody opens it.
 */
function Passage({ item, highlighted }: { item: SourceItem; highlighted: boolean }) {
  const t = useTranslations("chat");
  const ref = useScrolledTo(highlighted);
  const [unfolded, setUnfolded] = useState(false);
  const open = highlighted || unfolded;
  return (
    <div
      ref={ref}
      data-highlighted={highlighted || undefined}
      className={cn(
        "flex items-start gap-2.5 px-3 py-2.5 transition-colors",
        highlighted && "bg-foreground/[0.05]",
      )}
    >
      <span
        className={cn(
          "mt-0.5 inline-flex h-5 min-w-[1.5rem] shrink-0 items-center justify-center rounded px-1 font-mono text-xs tabular-nums",
          highlighted ? "bg-foreground text-background" : "bg-foreground/8 text-foreground/65",
        )}
      >
        {item.index}
      </span>
      <div className="min-w-0 flex-1">
        {(item.subtitle || item.score !== undefined) && (
          <div className="text-muted-foreground flex items-center gap-2 font-mono text-[11px] tracking-wide uppercase">
            {item.subtitle && <span>{item.subtitle}</span>}
            {item.score !== undefined && <ScoreDot score={item.score} />}
          </div>
        )}
        {item.content && (
          <>
            <div
              className={cn(
                "text-foreground/75 mt-1 text-xs leading-relaxed",
                "[&_h1]:mt-1 [&_h1]:mb-1 [&_h1]:text-[13px] [&_h2]:mt-1 [&_h2]:mb-1 [&_h2]:text-xs [&_h3]:mb-1 [&_h3]:text-xs [&_li]:text-xs [&_p]:mb-1.5 [&_p]:text-xs",
                !open &&
                  "max-h-28 overflow-hidden [mask-image:linear-gradient(to_bottom,black_60%,transparent)]",
              )}
            >
              <MarkdownContent content={item.content} bareCode inertImages />
            </div>
            {!highlighted && (
              <button
                type="button"
                onClick={() => setUnfolded(!unfolded)}
                className="text-muted-foreground hover:text-foreground mt-1 text-xs font-medium"
              >
                {unfolded ? t("showLess") : t("showMore")}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/**
 * A knowledge base file and the passages of it the answer cited, as one card.
 *
 * Five chunks of a handbook used to be five unrelated rows, each repeating the
 * file's name. The file is the thing a reader recognises - and the thing they
 * want to open, to check the passage in its place.
 */
function DocumentCard({
  doc,
  passages,
  base,
  highlightedIndex,
  onOpenFile,
}: {
  doc: SourceDocument;
  passages: SourceItem[];
  base?: string;
  highlightedIndex: number | null;
  onOpenFile?: () => void;
}) {
  const t = useTranslations("chat");
  return (
    <section className="border-foreground/10 overflow-hidden rounded-xl border">
      <div className="bg-foreground/[0.025] flex items-center gap-2.5 px-3 py-2.5">
        <SourceMark type="rag" title={doc.title} />
        <div className="min-w-0 flex-1">
          <p className="text-foreground truncate text-[13px] font-medium" title={doc.title}>
            {doc.title}
          </p>
          {base && <p className="text-muted-foreground truncate text-xs">{base}</p>}
        </div>
        {onOpenFile && (
          <button
            type="button"
            onClick={onOpenFile}
            className="border-foreground/12 text-foreground/80 hover:bg-foreground/[0.05] inline-flex shrink-0 items-center gap-1.5 rounded-lg border px-2 py-1 text-xs font-medium"
          >
            <FileSearch className="h-3.5 w-3.5" aria-hidden />
            {t("openOriginal")}
          </button>
        )}
      </div>
      <div className="divide-foreground/8 divide-y">
        {passages.map((item, position) => (
          // By position: two searches number their passages from 1 each, so an
          // index is not unique within one answer's sources.
          <Passage key={position} item={item} highlighted={item.index === highlightedIndex} />
        ))}
      </div>
    </section>
  );
}

/** A page from the web: its service's mark, its title and site, and what it said. */
function WebSourceRow({ item, highlighted }: { item: SourceItem; highlighted: boolean }) {
  const ref = useScrolledTo(highlighted);
  const body = (
    <div
      ref={ref}
      data-highlighted={highlighted || undefined}
      className={cn(
        "border-foreground/10 flex items-start gap-2.5 rounded-xl border p-3 transition-colors",
        highlighted && "border-foreground/30 bg-foreground/[0.04]",
        item.url && "hover:border-foreground/25",
      )}
    >
      <SourceMark type="web" title={item.title} url={item.url} />
      <div className="min-w-0 flex-1">
        <p className="text-foreground truncate text-[13px] font-medium" title={item.title}>
          {item.title}
        </p>
        {item.subtitle && (
          <p className="text-muted-foreground flex items-center gap-1 truncate text-xs">
            {item.subtitle}
            {item.url && <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />}
          </p>
        )}
        {item.content && (
          <p className="text-foreground/70 mt-1.5 line-clamp-3 text-xs leading-relaxed">
            {item.content}
          </p>
        )}
      </div>
    </div>
  );

  if (item.url) {
    return (
      <a href={item.url} target="_blank" rel="noopener noreferrer" className="block">
        {body}
      </a>
    );
  }
  return body;
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
  const baseFor = useKnowledgeBaseFor();
  const [opened, setOpened] = useState<CitedFile | null>(null);

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
  const files = sourceDocuments(ragSources);

  return (
    <div
      className={cn(
        "bg-background border-border flex flex-col",
        contained
          ? "absolute inset-0 z-40"
          : "fixed top-0 right-0 z-50 h-full w-full border-l shadow-xl sm:w-[420px]",
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

      <div className="flex-1 scrollbar-thin space-y-5 overflow-y-auto px-4 py-4">
        {files.length > 0 && (
          <section className="space-y-2.5">
            {webSources.length > 0 && (
              <h3 className="text-muted-foreground font-mono text-xs tracking-wider uppercase">
                {t("knowledgeBase")}
              </h3>
            )}
            {files.map((doc) => {
              const base = baseFor(doc.collection);
              return (
                <DocumentCard
                  key={doc.key}
                  doc={doc}
                  passages={ragSources.filter((s) => sourceKey(s) === doc.key)}
                  base={base?.name}
                  highlightedIndex={highlightedIndex}
                  onOpenFile={
                    base ? () => setOpened({ kbId: base.id, filename: doc.title }) : undefined
                  }
                />
              );
            })}
          </section>
        )}

        {webSources.length > 0 && (
          <section className="space-y-2">
            {files.length > 0 && (
              <h3 className="text-muted-foreground font-mono text-xs tracking-wider uppercase">
                {t("web")}
              </h3>
            )}
            {webSources.map((s, position) => (
              <WebSourceRow key={position} item={s} highlighted={s.index === highlightedIndex} />
            ))}
          </section>
        )}
      </div>
      {opened && <SourceViewer cited={opened} onClose={() => setOpened(null)} />}
    </div>
  );
}
