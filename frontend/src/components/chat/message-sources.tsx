"use client";

import { ChevronDown, ExternalLink, FileSearch } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { SourceViewer, type CitedFile } from "@/components/kb/source-viewer";
import { useKnowledgeBaseFor } from "@/hooks/use-knowledge-bases";
import { sourceDocuments, type SourceDocument, type SourceItem } from "@/lib/chat-sources";
import { brandForUrl, hostOf } from "@/lib/link-brands";
import { cn } from "@/lib/utils";

import { SourceMark } from "./source-mark";

/** Beyond this the stack is a smudge; the rest are counted instead. */
const MAX_SHOWN = 4;

/** What a document's mark looks like: any file, or a page's service. */
function markOf(doc: SourceDocument): string {
  return doc.type === "rag" ? "file" : ((doc.url && brandForUrl(doc.url)) ?? "web");
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

/**
 * What an answer drew on, under it: the documents as a stack of marks, opening
 * into a list of them.
 *
 * One mark per document, not per passage - five chunks of a handbook are one
 * source to the reader. The stack tucks its marks under each other and spreads
 * them on hover, as the faces in the conversation list do. A row opens the
 * panel on that source's passages; a knowledge base file can also be opened
 * whole, which is the question a citation raises.
 */
export function MessageSources({
  sources,
  onOpen,
}: {
  sources: SourceItem[];
  onOpen: (index: number | null) => void;
}) {
  const t = useTranslations("chat");
  const [expanded, setExpanded] = useState(false);
  const [opened, setOpened] = useState<CitedFile | null>(null);
  const baseFor = useKnowledgeBaseFor();
  const documents = sourceDocuments(sources);
  const shown = variedFirst(documents);

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
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
        <ChevronDown
          aria-hidden
          className={cn(
            "text-muted-foreground h-3.5 w-3.5 transition-transform",
            expanded && "rotate-180",
          )}
        />
      </button>

      {expanded && (
        <ul className="border-foreground/10 divide-foreground/8 max-w-xl divide-y overflow-hidden rounded-xl border">
          {documents.map((doc) => (
            <SourceRow
              key={doc.key}
              doc={doc}
              base={baseFor(doc.collection)?.name}
              onShow={() => onOpen(doc.index)}
              onOpenFile={
                doc.type === "rag" && baseFor(doc.collection)
                  ? () => setOpened({ kbId: baseFor(doc.collection)!.id, filename: doc.title })
                  : undefined
              }
            />
          ))}
        </ul>
      )}
      {opened && <SourceViewer cited={opened} onClose={() => setOpened(null)} />}
    </div>
  );
}

function SourceRow({
  doc,
  base,
  onShow,
  onOpenFile,
}: {
  doc: SourceDocument;
  /** The knowledge base a file is in, by the name people know it. */
  base?: string;
  onShow: () => void;
  onOpenFile?: () => void;
}) {
  const t = useTranslations("chat");
  const where = doc.type === "web" ? (doc.url ? hostOf(doc.url) : null) : (base ?? null);

  return (
    <li className="hover:bg-foreground/[0.03] flex items-center gap-2.5 px-3 py-2 transition-colors">
      <SourceMark type={doc.type} title={doc.title} url={doc.url} />
      <button type="button" onClick={onShow} className="min-w-0 flex-1 text-left">
        <p className="text-foreground truncate text-[13px] font-medium" title={doc.title}>
          {doc.title}
        </p>
        <p className="text-muted-foreground truncate text-xs">
          {[where, doc.passages > 1 ? t("passageCount", { count: doc.passages }) : null]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </button>
      {onOpenFile && (
        <button
          type="button"
          onClick={onOpenFile}
          title={t("openOriginal")}
          aria-label={t("openOriginalNamed", { name: doc.title })}
          className="text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] rounded-md p-1.5"
        >
          <FileSearch className="h-4 w-4" />
        </button>
      )}
      {doc.type === "web" && doc.url && (
        <a
          href={doc.url}
          target="_blank"
          rel="noopener noreferrer"
          title={t("openPage")}
          aria-label={t("openPageNamed", { name: doc.title })}
          className="text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] rounded-md p-1.5"
        >
          <ExternalLink className="h-4 w-4" />
        </a>
      )}
    </li>
  );
}
