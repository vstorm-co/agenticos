"use client";

import { FileText, Tag, Trash2 } from "lucide-react";

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
    <Card className="peek-card group hover:border-foreground/20 relative h-full overflow-hidden">
      <button type="button" onClick={onOpen} className="flex h-full w-full flex-col text-left">
        {/* The body's opening on the front page, and one page behind it per file
            the skill carries - a skill with scripts and references looks like
            more than a single instruction before anyone opens it. */}
        <DocPeek
          sheets={skill.file_count}
          badge={skill.file_count > 0 ? t("moreFiles", { count: skill.file_count }) : undefined}
          className="h-32"
        >
          {skill.excerpt ? <TextPeek source={skill.excerpt} /> : <BlankPeek />}
        </DocPeek>
        <span className="flex flex-1 flex-col gap-1.5 p-4 pt-3.5 pb-12">
          <span className="flex items-center gap-2 pr-8">
            <span className="text-foreground truncate font-mono text-sm font-medium">
              {skill.name}
            </span>
            {skill.built_in && <Badge variant="secondary">built-in</Badge>}
            {!skill.enabled && <Badge variant="outline">{t("disabled")}</Badge>}
          </span>
          <span className="text-muted-foreground line-clamp-2 block text-sm">
            {skill.description}
          </span>
          <span className="text-muted-foreground mt-auto flex items-center gap-3 pt-1 text-xs">
            <span className="flex items-center gap-1">
              <FileText className="h-3.5 w-3.5 shrink-0" />
              {t("fileCount", { count: skill.file_count })}
            </span>
            {skill.category !== null && (
              <span className="flex min-w-0 items-center gap-1">
                <Tag className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">{categoryLabel(skill.category)}</span>
              </span>
            )}
          </span>
          <AudienceChip visibility={skill.visibility} groups={skill.shared_groups} />
          <UsedBy agents={skill.used_by} />
        </span>
      </button>
      {/* Beside the card's own controls rather than inside the button that opens
          it: giving it to an agent is the next step after writing one (#2075). It
          keeps the card's edge, and the bin that appears on hover sits beside it
          rather than holding a gap open when it does not. */}
      <div className="absolute right-4 bottom-3 flex items-center gap-1">
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
    </Card>
  );
}
