"use client";

import { useState } from "react";
import { FileText } from "lucide-react";
import { useTranslations } from "next-intl";
import { ErrorState, LoadingState } from "@/components/states";
import { Badge, ListCard, ListCardEmpty, SearchInput } from "@/components/ui";
import { PAGE_SIZE, useMyMemory } from "@/hooks/use-my-memory";
import { NoteDetail } from "./note-detail";
import { MemoryPager, MemoryRow } from "./memory-list";

export function MyNotes() {
  const t = useTranslations("pages.memory");
  const view = useTranslations("pages.memory.browser");
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const { page, isLoading, error, skip, showPage, setActive, remove } = useMyMemory(q.trim());
  const note = page?.items.find((item) => item.id === selected);
  return (
    <ListCard
      title={view("notes")}
      namedByPage
      fill
      counted={isLoading || !page ? null : view("noteCount", { count: page.total })}
      contentClassName="p-0"
      headerTour="my-memory"
      onClickCapture={(event) => {
        if (!note || !(event.target instanceof Element)) return;
        const href = event.target.closest("a")?.getAttribute("href");
        if (!href || /^(?:[a-z][a-z0-9+.-]*:|[\/#?])/i.test(href)) return;
        let name: string;
        try {
          name = decodeURIComponent(href.split(/[?#]/)[0] ?? "").replace(/^\.\//, "");
        } catch {
          return;
        }
        if (!name) return;
        // A note's relative link stays in this person's memory, not on an app route.
        event.preventDefault();
        const linked = page?.items.find(
          (item) => item.agent_id === note.agent_id && item.name === name,
        );
        if (linked) setSelected(linked.id);
        else {
          setQ(name);
          setSelected(null);
        }
      }}
      controls={
        <SearchInput value={q} onChange={setQ} maxLength={200} placeholder={view("searchNotes")} />
      }
    >
      <p className="text-muted-foreground border-b px-4 py-3 text-xs leading-5 sm:px-5">
        {view("notesHint")}
      </p>
      {isLoading ? (
        <LoadingState variant="skeleton-list" rows={3} />
      ) : error || !page ? (
        <ErrorState />
      ) : page.items.length === 0 ? (
        <ListCardEmpty
          icon={FileText}
          title={view(q ? "noMatches" : "emptyNotes")}
          description={view(q ? "tryFilters" : "emptyNotesHint")}
          {...(q ? { cta: { label: view("clearFilters"), onClick: () => setQ("") } } : {})}
        />
      ) : (
        <ul className="divide-foreground/5 divide-y px-2">
          {page.items.map((item) => (
            <MemoryRow
              key={item.id}
              title={item.name}
              icon={FileText}
              muted={Boolean(item.deactivated_at)}
              onOpen={() => setSelected(item.id)}
            >
              <span>{item.agent_name ?? t("anAgent")}</span>
              {item.description && (
                <span className="line-clamp-1 max-w-xl">{item.description}</span>
              )}
              {item.deactivated_at && <Badge variant="outline">{t("suppressed")}</Badge>}
            </MemoryRow>
          ))}
        </ul>
      )}
      {page && !error && (
        <MemoryPager
          skip={skip}
          count={page.items.length}
          total={page.total}
          size={PAGE_SIZE}
          onPage={showPage}
        />
      )}
      {note && (
        <NoteDetail
          key={note.id}
          note={note}
          onClose={() => setSelected(null)}
          setActive={setActive}
          remove={remove}
        />
      )}
    </ListCard>
  );
}
