"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { ChipsInput } from "@/components/agents/chips-input";
import { Label } from "@/components/ui";
import { useAgent } from "@/hooks";

/** The write caps the server enforces, shown here as add affordances. */
const MAX_CATEGORIES = 10;
const MAX_TAGS = 20;
const MAX_LABEL_LENGTH = 32;

const sameLabels = (a: string[], b: string[]) =>
  a.length === b.length && a.every((value, i) => value === b[i]);

/**
 * The categories/tags editor for an agent's detail page.
 *
 * Discovery metadata, not the spec: every edit autosaves at once like the
 * avatar, rather than waiting for a publish. The raw typed values are sent and
 * the draft is re-seeded from the normalized `AgentRead` the save returns, so
 * the server's fold, de-duplication and clamp are what the reader ends up
 * seeing. A failed save is toasted by the hook and the local draft is kept, so
 * the work is there to correct and retry.
 *
 * `categories`/`tags` can also change from outside this editor - a refetch
 * picking up another client's edit - and a draft that never adopts that would
 * send a save built on stale values and overwrite the newer row. So each
 * render compares the incoming props against the last props this editor saw:
 * a facet is only adopted from a changed prop when its draft is still exactly
 * that last-seen value, i.e. idle rather than mid-save or holding a failed
 * attempt the caller has not retried or cleared themselves.
 */
export function MetadataEditor({
  agentId,
  categories,
  tags,
}: {
  agentId: string;
  categories: string[];
  tags: string[];
}) {
  const t = useTranslations("pages.agents");
  const { setMetadata } = useAgent(agentId);
  const [draftCategories, setDraftCategories] = useState(categories);
  const [draftTags, setDraftTags] = useState(tags);
  const [seenCategories, setSeenCategories] = useState(categories);
  const [seenTags, setSeenTags] = useState(tags);

  if (!setMetadata.isPending && !sameLabels(categories, seenCategories)) {
    if (sameLabels(draftCategories, seenCategories)) setDraftCategories(categories);
    setSeenCategories(categories);
  }
  if (!setMetadata.isPending && !sameLabels(tags, seenTags)) {
    if (sameLabels(draftTags, seenTags)) setDraftTags(tags);
    setSeenTags(tags);
  }

  const save = (nextCategories: string[], nextTags: string[]) => {
    setDraftCategories(nextCategories);
    setDraftTags(nextTags);
    setMetadata.mutate(
      { categories: nextCategories, tags: nextTags },
      {
        onSuccess: (agent) => {
          setDraftCategories(agent.categories ?? []);
          setDraftTags(agent.tags ?? []);
        },
      },
    );
  };

  return (
    // Side by side above `sm`, because they are two halves of one question and
    // stacked full-width they read as two unrelated empty boxes taking up a
    // card. Each says what it is for and how much room is left, so the cap is
    // visible before somebody runs into it.
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="space-y-2">
        <div className="flex items-baseline justify-between gap-2">
          <Label>{t("categories")}</Label>
          <span className="text-muted-foreground/70 font-mono text-[11px]">
            {t("labelCount", { used: draftCategories.length, max: MAX_CATEGORIES })}
          </span>
        </div>
        <ChipsInput
          values={draftCategories}
          onChange={(next) => save(next, draftTags)}
          inputLabel={t("addCategory")}
          removeLabel={(value) => t("removeCategory", { value })}
          placeholder={t("addCategoryPlaceholder")}
          maxItems={MAX_CATEGORIES}
          maxLength={MAX_LABEL_LENGTH}
          disabled={setMetadata.isPending}
        />
        <p className="text-muted-foreground text-xs">{t("categoriesHint")}</p>
      </div>
      <div className="space-y-2">
        <div className="flex items-baseline justify-between gap-2">
          <Label>{t("tags")}</Label>
          <span className="text-muted-foreground/70 font-mono text-[11px]">
            {t("labelCount", { used: draftTags.length, max: MAX_TAGS })}
          </span>
        </div>
        <ChipsInput
          values={draftTags}
          onChange={(next) => save(draftCategories, next)}
          inputLabel={t("addTag")}
          removeLabel={(value) => t("removeTag", { value })}
          placeholder={t("addTagPlaceholder")}
          maxItems={MAX_TAGS}
          maxLength={MAX_LABEL_LENGTH}
          disabled={setMetadata.isPending}
        />
        <p className="text-muted-foreground text-xs">{t("tagsHint")}</p>
      </div>
    </div>
  );
}
