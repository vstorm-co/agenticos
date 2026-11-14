"use client";

import { useState } from "react";
import { BookPlus, Save } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge, Button, Input, Label, MarkdownEditor } from "@/components/ui";
import {
  isIdentifyingContent,
  useAddKnowledgeGapContent,
  useSaveKnowledgeGapContent,
} from "@/hooks/use-knowledge-gaps";
import type { KnowledgeGapFlag, KnowledgeGapTopicDetail } from "@/types/knowledge-gaps";
import { KnowledgeGapDraftMeta } from "./knowledge-gap-draft-meta";
import { KnowledgeGapFlags } from "./knowledge-gap-flags";

/** A detail still to fill in, as the drafter is told to write it and the server finds it. */
const BLANK = /\{\{([^{}]{1,200})\}\}/g;

export function blanksIn(text: string): string[] {
  const found = [...text.matchAll(BLANK)].map((match) => String(match[1]).trim()).filter(Boolean);
  return [...new Set(found)];
}

/**
 * A topic's content to write, or to finish from its draft, and add to its knowledge
 * base as a document. Adding waits while a detail is still to fill in, and while
 * something that may identify somebody is unconfirmed - what the saved draft holds,
 * or what the server found when adding was tried.
 */
export function KnowledgeGapEditor({ topic }: { topic: KnowledgeGapTopicDetail }) {
  const t = useTranslations("knowledgeGaps");
  const [title, setTitle] = useState(topic.draft?.title ?? "");
  const [content, setContent] = useState(topic.draft?.content ?? "");
  const [confirmed, setConfirmed] = useState(false);
  const save = useSaveKnowledgeGapContent();
  const add = useAddKnowledgeGapContent();

  const blanks = blanksIn(`${title}\n${content}`);
  const saved =
    topic.draft !== null && title === topic.draft.title && content === topic.draft.content;
  const refused = isIdentifyingContent(add.error)
    ? ((add.error.details?.flags ?? []) as KnowledgeGapFlag[])
    : null;
  const flags = refused ?? (saved && topic.draft ? topic.draft.flags : []);
  const written = title.trim() !== "" && content.trim() !== "";
  const busy = save.isPending || add.isPending;
  const edit = (apply: () => void) => {
    apply();
    add.reset();
    setConfirmed(false);
  };

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <Label htmlFor="knowledge-gap-title">{t("contentTitle")}</Label>
        <Input
          id="knowledge-gap-title"
          value={title}
          maxLength={200}
          onChange={(event) => edit(() => setTitle(event.target.value))}
        />
      </div>
      <MarkdownEditor
        label={t("contentBody")}
        placeholder={t("contentPlaceholder")}
        value={content}
        rows={10}
        maxLength={20_000}
        inertImages
        onChange={(next) => edit(() => setContent(next))}
      />
      {blanks.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs">{t("blanksToFill", { count: blanks.length })}</p>
          <ul className="flex flex-wrap gap-1.5" aria-label={t("blanks")}>
            {blanks.map((blank) => (
              <li key={blank}>
                <Badge variant="warning">{blank}</Badge>
              </li>
            ))}
          </ul>
        </div>
      )}
      {flags.length > 0 && (
        <KnowledgeGapFlags flags={flags} confirmed={confirmed} onConfirmed={setConfirmed} />
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          disabled={busy || !written || blanks.length > 0 || (flags.length > 0 && !confirmed)}
          onClick={() =>
            add.mutate({ topicId: topic.id, title, content, confirmed: confirmed ? flags : [] })
          }
        >
          <BookPlus className="h-3.5 w-3.5" aria-hidden />
          {t("addToKnowledgeBase", { knowledgeBase: topic.knowledge_base_name })}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={busy || !written || saved}
          onClick={() => save.mutate({ topicId: topic.id, title, content })}
        >
          <Save className="h-3.5 w-3.5" aria-hidden />
          {t("saveContent")}
        </Button>
      </div>
      {topic.draft && <KnowledgeGapDraftMeta draft={topic.draft} />}
    </div>
  );
}
