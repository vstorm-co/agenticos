"use client";

import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { sourceDocuments, type SourceDocument, type SourceItem } from "@/lib/chat-sources";
import { brandForUrl, hostOf } from "@/lib/link-brands";
import { cn } from "@/lib/utils";

import { SourceMark } from "./source-mark";

/** Beyond this the stack is a smudge; the rest are counted instead. */
const MAX_SHOWN = 4;

/** What a document's mark looks like: any file, or a page's service. */
function markOf(doc: SourceDocument): string {
  return doc.type === "rag"
    ? "file"
    : ((doc.url && (brandForUrl(doc.url) ?? hostOf(doc.url))) ?? "web");
}

/**
 * The documents the stack shows: one of each kind of mark first, then the rest
 * in the order they were cited. Four marks of one handbook's files say less than
 * a file, GitHub and Notion side by side.
 */
function variedFirst(documents: SourceDocument[]): SourceDocument[] {
  const seen = new Set<string>();
  const distinct: SourceDocument[] = [];
  const repeats: SourceDocument[] = [];
  for (const doc of documents) {
    const mark = markOf(doc);
    (seen.has(mark) ? repeats : distinct).push(doc);
    seen.add(mark);
  }
  return [...distinct, ...repeats].slice(0, MAX_SHOWN);
}

/** One compact entry point to an answer's sources in the chat's side panel. */
export function MessageSources({
  sources,
  onOpen,
}: {
  sources: SourceItem[];
  onOpen: (index: number | null) => void;
}) {
  const t = useTranslations("chat");
  const documents = sourceDocuments(sources);
  const shown = variedFirst(documents);

  return (
    <button
      type="button"
      onClick={() => onOpen(null)}
      className="group/stack border-foreground/12 bg-background hover:border-foreground/25 hover:bg-foreground/[0.03] inline-flex items-center gap-2 rounded-full border py-1 pr-2.5 pl-1 transition-colors"
    >
      <span className="flex">
        {shown.map((doc, i) => (
          <SourceMark
            key={doc.key}
            type={doc.type}
            title={doc.title}
            url={doc.url}
            className={cn(
              "transition-[margin] duration-200 ease-out motion-reduce:transition-none",
              i > 0 && ["-ml-1.5", "group-hover/stack:ml-0.5"],
            )}
          />
        ))}
      </span>
      <span className="text-foreground/70 text-xs font-medium">
        {t("sourceCount", { count: documents.length })}
      </span>
      <ChevronRight aria-hidden className="text-muted-foreground h-3.5 w-3.5" />
    </button>
  );
}
