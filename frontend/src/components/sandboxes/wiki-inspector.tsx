"use client";
import type { ReactNode } from "react";
import { ArrowUpRight, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { FileIcon } from "@/components/files";
import { Button } from "@/components/ui";
import type { WikiGraph, WikiPage } from "@/lib/wiki-graph";
import { Connections } from "./wiki-connections";

export function WikiInspector({
  page,
  colour,
  graph,
  onSelect,
  onOpen,
  onClose,
  renderEditor,
}: {
  page: WikiPage;
  colour: string;
  graph: WikiGraph;
  onSelect: (path: string) => void;
  onOpen: (path: string) => void;
  onClose: () => void;
  renderEditor?: (path: string) => ReactNode;
}) {
  const t = useTranslations("wikiGraph");
  return (
    <aside
      className="bg-card/95 w-full overflow-hidden rounded-2xl border shadow-xl backdrop-blur-xl"
      aria-label={t("details")}
    >
      <div className="flex items-start gap-3 border-b p-4">
        <span
          className="rounded-xl p-2.5"
          // i18n-exempt: CSS colour and shadow expressions, never user-facing text.
          style={{ color: colour, background: `color-mix(in srgb, ${colour} 12%, transparent)` }}
        >
          <FileIcon name={page.path} className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-muted-foreground text-[10px] font-medium tracking-wider uppercase">
            {t("details")}
          </p>
          <h3 className="mt-1 text-sm font-semibold break-words">{page.title}</h3>
        </div>
        <Button
          size="icon"
          variant="ghost"
          className="size-7 rounded-full"
          aria-label={t("closeDetails")}
          onClick={onClose}
        >
          <X className="size-4" />
        </Button>
      </div>
      <div className="max-h-[35dvh] space-y-4 overflow-auto p-4 sm:max-h-[calc(100dvh-18rem)]">
        <p className="text-muted-foreground font-mono text-[11px] break-all">{page.path}</p>
        {page.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {page.tags.map((tag) => (
              <span key={tag} className="bg-muted rounded-full px-2 py-1 text-[10px]">
                #{tag}
              </span>
            ))}
          </div>
        )}
        <div className="flex flex-wrap gap-1">
          <Button size="sm" onClick={() => onOpen(page.path)}>
            <ArrowUpRight className="size-3.5" aria-hidden />
            {t("open")}
          </Button>
          {renderEditor?.(page.path)}
        </div>
        <Connections graph={graph} path={page.path} onSelect={onSelect} />
      </div>
    </aside>
  );
}
