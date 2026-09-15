"use client";

import { Brain, EyeOff, RotateCcw, Trash2 } from "lucide-react";

import { EmptyState, LoadingState } from "@/components/states";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { useMyMemory } from "@/hooks";
import type { MemoryNote } from "@/lib/memory-api";
import { useFormatter, useTranslations } from "next-intl";

/**
 * What the agents here have written down about you, and what you may do about it.
 *
 * The product used to offer erasure and nothing else, on the reasoning that a
 * listing is a surveillance affordance. It is - of somebody *else's* store. Of
 * your own it is the opposite, and the thing erasure could not give you: a way
 * to find the one note that is wrong without destroying everything an agent has
 * learned (#1594).
 *
 * Three verbs, and the middle one is the point. Suppressing stops a note
 * reaching the model without destroying it, for the common case of somebody who
 * has found something they dislike and is not yet sure they want it gone.
 */
export function MyMemory() {
  const t = useTranslations("pages.memory");
  const format = useFormatter();
  const { page, isLoading, setActive, remove } = useMyMemory();

  if (isLoading || !page) return <LoadingState variant="skeleton-list" rows={3} />;

  if (page.items.length === 0 && page.external_stores.length === 0) {
    return <EmptyState icon={Brain} title={t("nothingYet")} description={t("nothingYetWhy")} />;
  }

  return (
    <div className="space-y-4">
      {page.external_stores.length > 0 ? (
        <p className="text-muted-foreground text-xs">
          {t("externalStores", { agents: page.external_stores.join(", ") })}
        </p>
      ) : null}

      {page.items.map((note) => (
        <Card key={note.id} data-tour={note === page.items[0] ? "my-memory" : undefined}>
          <CardHeader className="flex flex-row items-start justify-between gap-3 border-b px-5 py-4">
            <div className="min-w-0 space-y-1">
              <CardTitle className="text-sm break-words">{note.name}</CardTitle>
              <p className="text-muted-foreground text-xs">
                {t("writtenBy", {
                  agent: note.agent_name ?? t("anAgent"),
                  when: when(note, format),
                })}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {note.deactivated_at ? <Badge variant="outline">{t("suppressed")}</Badge> : null}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setActive(note.id, Boolean(note.deactivated_at))}
                aria-label={note.deactivated_at ? t("restore") : t("suppress")}
              >
                {note.deactivated_at ? (
                  <RotateCcw className="h-4 w-4" />
                ) : (
                  <EyeOff className="h-4 w-4" />
                )}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => remove(note.id)}
                aria-label={t("delete")}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="p-5">
            {note.description ? (
              <p className="text-muted-foreground mb-2 text-xs">{note.description}</p>
            ) : null}
            <p className="text-sm whitespace-pre-wrap">{note.content}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

/** When the note was last written - the provenance that makes it actionable. */
function when(note: MemoryNote, format: ReturnType<typeof useFormatter>): string {
  const stamp = note.updated_at ?? note.created_at;
  return stamp ? format.dateTime(new Date(stamp), { dateStyle: "medium" }) : "";
}
