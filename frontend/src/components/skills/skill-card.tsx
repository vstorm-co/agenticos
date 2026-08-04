"use client";

import { FileText, Tag, Trash2 } from "lucide-react";

import { Badge, Button, Card, CardContent } from "@/components/ui";
import { categoryLabel } from "@/components/skills/category-input";
import type { SkillSummary } from "@/types/providers";
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
  return (
    <Card className="hover:border-foreground/20 h-full transition-colors">
      <CardContent className="flex items-start justify-between gap-3 p-5">
        <button type="button" onClick={onOpen} className="min-w-0 flex-1 space-y-1.5 text-left">
          <span className="flex items-center gap-2">
            <span className="text-foreground truncate font-mono text-sm font-medium">
              {skill.name}
            </span>
            {skill.built_in && <Badge variant="secondary">built-in</Badge>}
            {!skill.enabled && <Badge variant="outline">{t("disabled")}</Badge>}
          </span>
          <span className="text-muted-foreground line-clamp-2 block text-sm">
            {skill.description}
          </span>
          <span className="text-muted-foreground flex items-center gap-3 text-xs">
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
        </button>
        {canEdit && (
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Delete ${skill.name}`}
            onClick={onDelete}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
