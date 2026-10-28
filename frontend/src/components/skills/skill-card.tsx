"use client";

import { Tag, Trash2 } from "lucide-react";

import { Badge, BlankPeek, Button, Card, DocPeek, TextPeek } from "@/components/ui";
import { categoryLabel } from "@/components/skills/category-input";
import type { SkillSummary } from "@/types/providers";
import { AddToAgent } from "@/components/agents/add-to-agent";
import { UsedBy } from "@/components/agents/used-by";
import { AudienceChip } from "@/components/sharing/audience-chip";
import { useTranslations } from "next-intl";

interface SkillCardProps {
  skill: SkillSummary;
  /** A viewer opens skills to read them; only an editor gets the delete. */
  canEdit: boolean;
  onOpen: () => void;
  onDelete: () => void;
}

/**
 * One skill in the list.
 *
 * Two badges, both exceptions: `built-in` marks a skill that shipped with the
 * deployment rather than being written here, and `disabled` marks one agents
 * are currently skipping. The ordinary case - a custom, enabled skill - stays
 * unbadged, so the exceptions can be found at a glance.
 */
export function SkillCard({ skill, canEdit, onOpen, onDelete }: SkillCardProps) {
  const t = useTranslations("skills");
  const tc = useTranslations("common");
  return (
    <Card className="peek-card group hover:border-foreground/20 relative flex h-full flex-col overflow-hidden">
      <button
        type="button"
        onClick={onOpen}
        className="flex w-full flex-1 flex-col rounded-[inherit] text-left focus-visible:outline-offset-[-2px]"
      >
        <span className="flex flex-1 flex-col gap-1.5 p-4">
          <span className="flex min-w-0 flex-wrap items-center gap-2 sm:pr-8">
            <span className="text-foreground max-w-full truncate font-mono text-sm font-medium">
              {skill.name}
            </span>
            {skill.built_in && <Badge variant="secondary">built-in</Badge>}
            {!skill.enabled && <Badge variant="outline">{t("disabled")}</Badge>}
          </span>
          <span className="text-muted-foreground line-clamp-2 min-h-10 text-sm">
            {skill.description}
          </span>
          <span className="text-muted-foreground mt-auto flex items-center gap-3 pt-1 text-xs">
            {skill.category !== null && (
              <span className="flex min-w-0 items-center gap-1">
                <Tag className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">{categoryLabel(skill.category)}</span>
              </span>
            )}
          </span>
        </span>
      </button>
      <details className="group/details border-t">
        <summary className="text-muted-foreground hover:text-foreground touch:min-h-11 cursor-pointer px-4 py-2 text-xs focus-visible:outline-offset-[-2px]">
          {tc("details")}
        </summary>
        <div className="space-y-3 px-4 pb-4">
          <DocPeek
            sheets={skill.file_count}
            badge={skill.file_count > 0 ? t("moreFiles", { count: skill.file_count }) : undefined}
            className="h-28"
          >
            {skill.excerpt ? <TextPeek source={skill.excerpt} /> : <BlankPeek />}
          </DocPeek>
          <AudienceChip visibility={skill.visibility} groups={skill.shared_groups} />
          <UsedBy agents={skill.used_by} />
        </div>
        <div className="flex items-center justify-end gap-1 border-t px-3 py-2">
          {canEdit && (
            // Outside the open button - a button cannot hold another - and quiet until
            // the card is pointed at, so a grid of cards is not a column of bins.
            <Button
              variant="ghost"
              size="icon"
              aria-label={tc("deleteNamed", { name: skill.name })}
              onClick={onDelete}
              className="hover-reveal h-8 w-8"
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          )}
          <AddToAgent
            resource={{ kind: "skill", id: skill.id }}
            name={skill.name}
            className="h-8 text-xs"
          />
        </div>
      </details>
    </Card>
  );
}
