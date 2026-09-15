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

/**
 * The categories/tags editor for an agent's detail page.
 *
 * Discovery metadata, not the spec: every edit autosaves at once like the
 * avatar, rather than waiting for a publish. The raw typed values are sent and
 * the draft is re-seeded from the normalized `AgentRead` the save returns, so
 * the server's fold, de-duplication and clamp are what the reader ends up
 * seeing. A failed save is toasted by the hook and the local draft is kept, so
 * the work is there to correct and retry.
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
    <div className="space-y-4">
      <div className="space-y-2">
        <Label>{t("categories")}</Label>
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
      </div>
      <div className="space-y-2">
        <Label>{t("tags")}</Label>
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
      </div>
    </div>
  );
}
