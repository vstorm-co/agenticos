"use client";

import { useQuery } from "@tanstack/react-query";
import type { ComponentType, ReactNode } from "react";
import { AlignLeft, Layers, Loader2, ScanText } from "lucide-react";
import { useTranslations } from "next-intl";

import { CopyButton } from "@/components/chat/copy-button";
import { MarkdownContent } from "@/components/chat/markdown-content";
import { FileViewer as SharedFileViewer, type ViewerTab } from "@/components/files";
import { JsonView } from "@/components/ui/json-view";
import { qk } from "@/lib/query-keys";
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
        {
          value: "json",
          label: t("json"),
          content: <StoredJsonTab kbId={kbId} docId={doc.id} />,
        } satisfies ViewerTab,
      ]}
      onClose={onClose}
    />
  );
}

/**
 * What the parser made of this document, fetched on the first look at either tab.
 *
 * Lazily and then kept: a stored parse does not change, and most people opening a
 * document never ask this question. Through the query layer rather than an effect
 * because two tabs read the same payload now - the parse as pages, and the same
 * records as the JSON that went into the store - and the second one must not fetch it
 * again.
 */
function useParsedDocument(kbId: string, docId: string) {
  return useQuery({
    queryKey: qk.kb.documentParsed(kbId, docId),
    queryFn: () => getParsedKBDocument(kbId, docId),
    staleTime: Infinity,
    // One attempt. The usual answer here is "No parsed content for this document" -
    // still processing, or ingestion failed - which is a fact about the document
    // rather than a flaky request, and retrying it three times only delays saying so.
    retry: false,
  });
}

/** The loading and refused states both tabs share, or null once there is a parse. */
function ParseState({ error, parsed }: { error: unknown; parsed: KBParsedContent | undefined }) {
  const t = useTranslations("kb");

  if (error !== null)
    // Most often "No parsed content for this document": still processing, or
    // ingestion failed. A refusal to show a parse is not a broken screen.
    return (
      <div className="flex flex-col items-center gap-2 px-8 py-10 text-center">
        <p className="text-foreground text-sm font-medium">{t("noParsedContentShow")}</p>
        <p className="text-muted-foreground max-w-md text-xs">
          {error instanceof Error ? error.message : t("failedLoadParsedContent")}
        </p>
      </div>
    );

  if (parsed === undefined)
    return (
      <div className="flex items-center justify-center py-10">
        <Loader2 className="text-muted-foreground h-6 w-6 animate-spin" />
      </div>
    );

  return null;
}

function ParsedTab({ kbId, docId }: { kbId: string; docId: string }) {
  const { data: parsed, error } = useParsedDocument(kbId, docId);

  if (parsed === undefined || error !== null) return <ParseState error={error} parsed={parsed} />;
  if (!parsed.has_text) return <NothingReadable parsed={parsed} />;

  return <ParsedPages parsed={parsed} />;
}

/**
 * The records this document became, as JSON.
 *
 * The same payload the parsed tab renders, unrendered: one object per chunk the
 * store holds, in the order it holds them. That is the thing somebody debugging
 * retrieval is actually asking about - a chunk that came back for a query it should
 * not have, a boundary that split a table in half - and reading it out of prose with
 * markdown applied means guessing where one record ends.
 *
 * Derived here rather than fetched separately: the parsed endpoint *is* the store's
 * chunks, grouped into pages, so flattening the grouping is the whole difference.
 * `chunks` is the flat list because that is what was stored; the page each came from
 * stays on the record rather than becoming nesting a reader has to unpick.
 */
function StoredJsonTab({ kbId, docId }: { kbId: string; docId: string }) {
  const { data: parsed, error } = useParsedDocument(kbId, docId);

  if (parsed === undefined || error !== null) return <ParseState error={error} parsed={parsed} />;

  const records = {
    id: parsed.id,
    filename: parsed.filename,
    parser: parsed.parser,
    chunk_count: parsed.chunk_count,
    has_text: parsed.has_text,
    chunks: parsed.pages.flatMap((page) =>
      page.chunks.map((content) => ({
        page_num: page.page_num,
        characters: content.length,
        content,
      })),
    ),
  };
  const characters = records.chunks.reduce((total, chunk) => total + chunk.characters, 0);

  return (
    <div>
      <ParseFacts
        parsed={parsed}
        characters={characters}
        trailing={
          /* The raw text, still one click away: a reader that cannot be pasted
             into `jq` has taken something away. */
          <CopyButton text={JSON.stringify(records, null, 2)} />
        }
      />
      <div className="py-4">
        {/* Open to the fields of each record: a chunk's page and length are the
            two things being scanned for, and the long value they sit beside is
            clamped rather than folded. */}
        <JsonView value={records} initialDepth={3} />
      </div>
    </div>
  );
}

/**
 * What the parse amounts to, as facts rather than as a sentence.
 *
 * It was one line of prose joined by middots - "What was indexed: 4 chunks ·
 * parsed with liteparse · adjacent chunks repeat their overlap, so boundary text
 * appears twice" - which reads as a paragraph pretending to be a status bar and
 * put a caveat, a count and a tool name at the same weight. Three counted things
 * are three counted things; the caveat is a sentence and belongs under them, on
 * the tab that shows the repetition it is about.
 *
 * Both tabs draw this, because both are about the same parse: two differently
 * shaped headers over one document is what made the pair look unfinished.
 */
function ParseFacts({
  parsed,
  characters,
  trailing,
}: {
  parsed: KBParsedContent;
  /** Total length of what was stored. Omitted where the tab does not count it. */
  characters?: number;
  trailing?: ReactNode;
}) {
  const t = useTranslations("kb");

  return (
    <div className="border-border bg-card sticky top-0 z-10 flex items-center gap-4 border-b py-2">
      <Fact icon={Layers} label={t("chunks")}>
        {t("chunkCount", { count: parsed.chunk_count })}
      </Fact>
      {parsed.parser !== null && (
        <Fact icon={ScanText} label={t("parser")}>
          {parsed.parser}
        </Fact>
      )}
      {characters !== undefined && (
        <Fact icon={AlignLeft} label={t("characters")}>
          {t("characterCount", { count: characters })}
        </Fact>
      )}
      {trailing !== undefined && <span className="ml-auto">{trailing}</span>}
    </div>
  );
}

/** One counted thing: its mark, its value, and what the mark means read aloud. */
function Fact({
  icon: Icon,
  label,
  children,
}: {
  icon: ComponentType<{ className?: string }>;
  label: string;
  children: ReactNode;
}) {
  return (
    <span className="text-muted-foreground flex items-center gap-1.5 text-xs">
      <Icon className="h-3.5 w-3.5 shrink-0 opacity-70" aria-label={label} />
      <span className="text-foreground/80 font-mono">{children}</span>
    </span>
  );
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

  return (
    <div>
      <ParseFacts parsed={parsed} />
      {/* Under the facts rather than joined to them: it is the one thing here that
          is a caveat rather than a number, and it explains something visible a few
          lines down - the same words repeated across a chunk boundary. */}
      {parsed.chunk_count > 1 && (
        <p className="text-muted-foreground/80 pt-2 text-xs">{t("overlapRepeats")}</p>
      )}
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
