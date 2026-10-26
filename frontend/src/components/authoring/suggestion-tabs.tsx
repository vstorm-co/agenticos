"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Tabs, TabsContent, TabsList, TabsTrigger, badgeVariants } from "@/components/ui";
import { ideaState } from "@/lib/authoring-groups";
import type { AuthoringRequest, SuggestionBatch } from "@/types/authoring";
import { ChangeGroups, type Entry, type EntryActions } from "./change-groups";

type Tab = "review" | "decided";

/**
 * What the assistant suggested for the draft, in two tabs: what still needs a
 * decision, shown whole, and what was decided, folded. Both are grouped by kind
 * of change. It opens on To review, or on Decided once nothing is left.
 *
 * A new skill the assistant wrote but did not add waits here too, until a person
 * creates or dismisses it.
 */
export function SuggestionTabs({
  batch,
  request,
  actions,
}: {
  batch: SuggestionBatch | null;
  /** The latest finished request, whose report holds the new-skill ideas. */
  request: AuthoringRequest | null;
  actions: Omit<EntryActions, "open">;
}) {
  const t = useTranslations("authoring.tabs");
  const [chosen, setChosen] = useState<Tab | null>(null);
  const open = batch?.status === "open";
  const hunks = batch?.hunks ?? [];
  const ideas = request
    ? (request.report?.rejected ?? []).flatMap((idea, index) => {
        const state = ideaState(idea);
        return state === null ? [] : [{ idea, index, state, requestId: request.id }];
      })
    : [];
  const review: Entry[] = [
    ...hunks.filter((hunk) => open && hunk.status === "pending").map((hunk) => ({ hunk })),
    ...ideas.filter((idea) => idea.state === "waiting"),
  ];
  const decided: Entry[] = [
    ...hunks.filter((hunk) => !open || hunk.status !== "pending").map((hunk) => ({ hunk })),
    ...ideas.filter((idea) => idea.state !== "waiting"),
  ];
  if (review.length === 0 && decided.length === 0) return null;
  const tab = chosen ?? (review.length > 0 ? "review" : "decided");
  const entryActions = { ...actions, open };
  return (
    <Tabs value={tab} onValueChange={(value) => setChosen(value as Tab)}>
      <TabsList aria-label={t("label")}>
        <TabsTrigger value="review">
          {t("toReview")}{" "}
          <span className={badgeVariants({ variant: "secondary" })}>{review.length}</span>
        </TabsTrigger>
        <TabsTrigger value="decided">
          {t("decided")}{" "}
          <span className={badgeVariants({ variant: "secondary" })}>{decided.length}</span>
        </TabsTrigger>
      </TabsList>
      <TabsContent value="review" className="pt-3">
        {review.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("nothingLeft")}</p>
        ) : (
          <ChangeGroups entries={review} decided={false} actions={entryActions} />
        )}
      </TabsContent>
      <TabsContent value="decided" className="space-y-3 pt-3">
        {review.length === 0 && <p className="text-muted-foreground text-sm">{t("nothingLeft")}</p>}
        {decided.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("nothingDecided")}</p>
        ) : (
          <ChangeGroups entries={decided} decided actions={entryActions} />
        )}
      </TabsContent>
    </Tabs>
  );
}
