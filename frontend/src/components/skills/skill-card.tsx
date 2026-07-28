"use client";

import { Trash2 } from "lucide-react";

import { Badge, Button, Card, CardContent } from "@/components/ui";
import type { SkillSummary } from "@/types/providers";

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
 * Only a disabled skill is badged. Badging the enabled ones too would mark the
 * ordinary case on every card and leave the exception to be found by reading.
 */
export function SkillCard({ skill, canEdit, onOpen, onDelete }: SkillCardProps) {
  return (
    <Card className="hover:border-foreground/20 h-full transition-colors">
      <CardContent className="flex items-start justify-between gap-3 p-5">
        <button type="button" onClick={onOpen} className="min-w-0 flex-1 space-y-1.5 text-left">
          <span className="flex items-center gap-2">
            <span className="truncate font-mono text-sm font-medium">{skill.name}</span>
            {!skill.enabled && <Badge variant="outline">disabled</Badge>}
          </span>
          <span className="text-muted-foreground line-clamp-2 block text-sm">
            {skill.description}
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
