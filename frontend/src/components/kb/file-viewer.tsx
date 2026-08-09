"use client";

import { useEffect, useState } from "react";
import { Loader2, ScanText } from "lucide-react";
import { useTranslations } from "next-intl";

import { MarkdownContent } from "@/components/chat/markdown-content";
import { FileViewer as SharedFileViewer, type ViewerTab } from "@/components/files";
import { getParsedKBDocument, kbDocumentAccess } from "@/lib/rag-api";
import type { KBParsedContent } from "@/types";

interface FileViewerDoc {
  id: string;
  filename: string;
  filetype: string | null;
  filesize?: number | null;
  created_at?: string;
}

interface FileViewerProps {
  kbId: string;
  doc: FileViewerDoc | null;
  open: boolean;
  onClose: () => void;
}

/**
 * One knowledge base document, opened.
 *
 * 545 lines of this were a fourth file viewer - its own kind resolver, its own eight
 * render branches, its own blob-URL lifecycle. All of that is now `FileViewer`, which
 * every surface opens, and what is left here is the one thing that is genuinely about
 * a knowledge base: the *parsed* tab.
 *
 * That tab is the comparison this dialog exists for. What a person sees and what the
 * ingestion pipeline extracted are two different documents often enough - a scanned
 * PDF looks fine and parses to nothing - and only this surface knows there is a
 * parser at all. So it arrives as an extra tab rather than as something the shared
 * component was taught about.
 */
export function FileViewer({ kbId, doc, open, onClose }: FileViewerProps) {
  const t = useTranslations("kb");
  if (!open || doc === null) return null;

  return (
    <SharedFileViewer
      // Keyed on the document, so opening a second one starts with its own state
      // rather than inheriting the first one's tab and its fetched parse.
      key={doc.id}
      file={{
        name: doc.filename,
        mimeType: doc.filetype,
        size: doc.filesize ?? null,
        modifiedAt: doc.created_at ?? null,
      }}
      access={kbDocumentAccess(kbId, doc)}
      extraTabs={[
        {
          value: "parsed",
          label: t("parsed"),
          content: <ParsedTab kbId={kbId} docId={doc.id} />,
        } satisfies ViewerTab,
      ]}
      onClose={onClose}
    />
  );
}

/**
 * What the parser made of this document, fetched on the first look at the tab.
 *
 * Lazily and then kept: a stored parse does not change, and most people opening a
 * document never ask this question. Mounted only while the tab is selected, which is
 * what makes "on the first look" the same thing as "on mount".
 */
function ParsedTab({ kbId, docId }: { kbId: string; docId: string }) {
  const t = useTranslations("kb");
  const [parsed, setParsed] = useState<KBParsedContent | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getParsedKBDocument(kbId, docId)
      .then((data) => {
        if (!cancelled) setParsed(data);
      })
      .catch((failure: unknown) => {
        if (!cancelled)
          setError(failure instanceof Error ? failure.message : t("failedLoadParsedContent"));
      });
    return () => {
      cancelled = true;
    };
  }, [kbId, docId, t]);

  if (error !== null)
    // Most often "No parsed content for this document": still processing, or
    // ingestion failed. A refusal to show a parse is not a broken screen.
    return (
      <div className="flex flex-col items-center gap-2 px-8 py-10 text-center">
        <p className="text-foreground text-sm font-medium">{t("noParsedContentShow")}</p>
        <p className="text-muted-foreground max-w-md text-xs">{error}</p>
      </div>
    );

  if (parsed === null)
    return (
      <div className="flex items-center justify-center py-10">
        <Loader2 className="text-muted-foreground h-6 w-6 animate-spin" />
      </div>
    );

  if (!parsed.has_text) return <NothingReadable parsed={parsed} />;

  return <ParsedPages parsed={parsed} />;
}

/**
 * A document that indexed nothing readable.
 *
 * `has_text` comes from the server, which knows that an unreadable scan comes back as
 * an empty fenced block rather than as whitespace - so this is not something a
 * `.trim()` here could reproduce, and it must not be shown as a document that parsed
 * fine.
 */
function NothingReadable({ parsed }: { parsed: KBParsedContent }) {
  const t = useTranslations("kb");

  return (
    <div className="flex flex-col items-center gap-4 px-8 py-10 text-center">
      <span className="bg-muted text-muted-foreground inline-flex h-12 w-12 items-center justify-center rounded-xl">
        <ScanText className="h-5 w-5" />
      </span>
      <div>
        <p className="text-foreground text-sm font-medium">{t("nothingReadableCameOut")}</p>
        <p className="text-muted-foreground mx-auto mt-1 max-w-md text-xs">
          {parsed.chunk_count > 0 ? t("everyPageCameBack") : t("nothingIndexedDocumentIts")}
        </p>
        {parsed.parser && (
          <p className="text-muted-foreground mt-2 font-mono text-xs">
            {t("parsedWith", { parser: parsed.parser })}
          </p>
        )}
      </div>
    </div>
  );
}

/**
 * The reconstructed markdown a document parsed into, page by page.
 *
 * Chunks render separately with hairline dividers rather than joined, because that is
 * what was actually indexed: adjacent chunks repeat their configured overlap, and a
 * silent join would present the duplication as a parse bug.
 */
function ParsedPages({ parsed }: { parsed: KBParsedContent }) {
  const t = useTranslations("kb");
  const multiPage = parsed.pages.length > 1 || (parsed.pages[0]?.page_num ?? 1) !== 1;
  // Joined rather than written as one sentence with two optional tails: each part is
  // a whole clause in its own right, which is what lets a locale reorder them - and a
  // message that opens on a separator is half a sentence with the other half still in
  // the JSX.
  const summary = [t("whatWasIndexed", { count: parsed.chunk_count })];
  if (parsed.parser !== null) summary.push(t("parsedWith", { parser: parsed.parser }));
  if (parsed.chunk_count > 1) summary.push(t("overlapRepeats"));

  return (
    <div>
      <div className="text-muted-foreground border-border bg-card sticky top-0 z-10 border-b py-2 text-xs">
        {summary.join(" · ")}
      </div>
      <div className="space-y-6 py-4">
        {parsed.pages.map((page) => (
          <section key={page.page_num}>
            {multiPage && (
              <p className="text-muted-foreground mb-2 text-xs font-medium tracking-wide uppercase">
                {t("pageNumber", { number: page.page_num })}
              </p>
            )}
            {!page.has_text && (
              <p className="text-muted-foreground border-border mb-2 rounded-lg border border-dashed px-3 py-2 text-xs">
                {t("pageParsedNothingReadable")}
              </p>
            )}
            <div className="divide-border divide-y">
              {page.chunks.map((chunk, index) => (
                <div key={index} className="py-4 first:pt-0 last:pb-0">
                  <div className="prose prose-sm dark:prose-invert max-w-none">
                    <MarkdownContent content={chunk} />
                  </div>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
