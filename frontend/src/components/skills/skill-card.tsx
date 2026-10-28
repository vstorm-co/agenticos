"use client";

import { Tag, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { Badge, BlankPeek, Button, Card, DocPeek, TextPeek } from "@/components/ui";
import { AddToAgent } from "@/components/agents/add-to-agent";
import { UsedBy } from "@/components/agents/used-by";
import { AudienceChip } from "@/components/sharing/audience-chip";
import type { SkillSummary } from "@/types/providers";
import { categoryLabel } from "@/components/skills/category-input";

interface SkillCardProps {
  skill: SkillSummary;
  canEdit: boolean;
  onOpen: () => void;
  onDelete: () => void;
}

/** Preview, agent usage and next action stay visible; taxonomy opens on demand. */
export function SkillCard({ skill, canEdit, onOpen, onDelete }: SkillCardProps) {
  const t = useTranslations("skills");
  const tc = useTranslations("common");
  return (
    <Card className="peek-card group hover:border-foreground/20 flex h-full flex-col overflow-hidden">
      <button
        type="button"
        onClick={onOpen}
        className="flex w-full flex-1 flex-col rounded-[inherit] text-left focus-visible:outline-offset-[-2px]"
      >
        <DocPeek
          sheets={skill.file_count}
          badge={skill.file_count > 0 ? t("moreFiles", { count: skill.file_count }) : undefined}
          className="h-32 max-sm:hidden"
        >
          {skill.excerpt ? <TextPeek source={skill.excerpt} /> : <BlankPeek />}
        </DocPeek>
        <span className="flex w-full flex-1 flex-col gap-1.5 p-4">
          <span className="flex min-w-0 flex-wrap items-center gap-2">
            <span
              className="text-foreground max-w-full truncate text-base font-semibold"
              title={skill.name}
            >
              {skill.name}
            </span>
            {skill.built_in && <Badge variant="secondary">built-in</Badge>}
          </span>
          <span className="text-foreground/85 line-clamp-2 min-h-10 text-sm leading-relaxed">
            {skill.description}
          </span>
        </span>
      </button>
      <UsedBy agents={skill.used_by} className="text-foreground/85 mx-4 mb-3 gap-2" />
      <div className="flex items-start justify-between gap-2 border-t px-3 py-2">
        <details className="text-muted-foreground min-w-0 flex-1 text-xs">
          <summary className="hover:text-foreground touch:min-h-11 cursor-pointer py-2 focus-visible:outline-offset-[-2px]">
            {tc("details")}
          </summary>
          <div className="space-y-2 pt-2 pb-1">
            {skill.category !== null && (
              <span className="flex items-center gap-1">
                <Tag className="size-3.5" aria-hidden />
                {categoryLabel(skill.category)}
              </span>
            )}
            <AudienceChip visibility={skill.visibility} groups={skill.shared_groups} />
            {canEdit && (
              <Button
                variant="ghost"
                size="icon"
                aria-label={tc("deleteNamed", { name: skill.name })}
                onClick={onDelete}
                className="h-8 w-8"
              >
                <Trash2 className="size-4" aria-hidden />
              </Button>
            )}
          </div>
        </details>
        <AddToAgent
          resource={{ kind: "skill", id: skill.id }}
          name={skill.name}
          className="h-8 shrink-0"
        />
      </div>
    </Card>
  );
}
