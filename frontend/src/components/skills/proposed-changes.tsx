"use client";

import { useState } from "react";
import { Check, ChevronDown, GitPullRequest, X } from "lucide-react";

import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui";
import { useSkillChanges } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import type { SkillChangeRecord } from "@/lib/skill-changes-api";
import { useTranslations } from "next-intl";

interface ProposedChangesProps {
  /**
   * Whether the reader may decide. The backend gates every route here on
   * `skills:edit`, so somebody without it sees nothing at all rather than a
   * panel of buttons that answer 403.
   */
  canEdit: boolean;
}

/**
 * Skill changes an agent wrote, waiting for somebody to accept them.
 *
 * The panel is absent when nothing is pending, which is the normal state - a
 * permanent empty box above the skills list would be a permanent reminder of a
 * feature most organizations use rarely.
 *
 * The body is shown, not summarised. Accepting one of these rewrites
 * instructions every agent bound to that skill follows on its next run, and that
 * decision cannot be made from a title.
 */
export function ProposedChanges({ canEdit }: ProposedChangesProps) {
  const t = useTranslations("skills");
  const { changes, error, apply, discard, isDeciding } = useSkillChanges("pending");

  if (!canEdit) return null;
  // An empty list and a failed request are the same pixels, so a failure is said
  // out loud even though nothing is rendered for an empty one.
  if (error !== null) return <p className="text-destructive text-sm">{error}</p>;
  if (changes.length === 0) return null;

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between space-y-0 border-b px-5 py-4">
        <div className="space-y-1">
          <CardTitle className="flex items-center gap-2 text-sm">
            <GitPullRequest className="h-4 w-4" aria-hidden />
            {t("changesAgentProposed")}
          </CardTitle>
          <CardDescription className="text-xs">
            {t("waitingCount", { count: changes.length })}. Accepting one rewrites the skill, which
            reaches every agent bound to it on its next run.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="divide-border divide-y p-0">
        {changes.map((change) => (
          <ChangeRow
            key={change.id}
            change={change}
            disabled={isDeciding}
            onApply={() => void apply(change.id)}
            onDiscard={() => void discard(change.id)}
          />
        ))}
      </CardContent>
    </Card>
  );
}

interface ChangeRowProps {
  change: SkillChangeRecord;
  disabled: boolean;
  onApply: () => void;
  onDiscard: () => void;
}

/**
 * One proposal, collapsed to its claim and expandable to its body.
 *
 * Collapsed by default because a reviewer with six waiting needs to see six
 * rows, and expanded on demand because the body is what the decision is about.
 */
function ChangeRow({ change, disabled, onApply, onDiscard }: ChangeRowProps) {
  const t = useTranslations("skills");
  const [open, setOpen] = useState(false);
  const resources = Object.keys(change.resources);

  return (
    <div className="space-y-3 px-5 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm">{change.name}</span>
            {change.skill_id === null ? (
              <Badge variant="secondary">{t("newSkill2")}</Badge>
            ) : (
              <Badge variant="outline">{t("edit")}</Badge>
            )}
          </div>
          <p className="text-muted-foreground text-xs">
            {change.description || t("noDescriptionWorthAdding")}
          </p>
          {change.conversation_id !== null && (
            <a
              className="text-muted-foreground text-xs underline"
              href={`${ROUTES.CHAT}?c=${change.conversation_id}`}
            >
              {t("readConversationCameFrom")}
            </a>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setOpen(!open)}
            aria-expanded={open}
            aria-label={t("showWhatChangedIn", { name: change.name })}
          >
            <ChevronDown className="h-4 w-4" aria-hidden />
            {open ? t("hide") : t("review")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={disabled}
            onClick={onDiscard}
            aria-label={t("discardChangeTo", { name: change.name })}
          >
            <X className="h-4 w-4" aria-hidden />
            {t("discard")}
          </Button>
          <Button
            size="sm"
            disabled={disabled}
            onClick={onApply}
            aria-label={t("applyChangeTo", { name: change.name })}
          >
            <Check className="h-4 w-4" aria-hidden />
            {t("apply")}
          </Button>
        </div>
      </div>

      {open && (
        <div className="space-y-3">
          <pre className="bg-muted max-h-80 overflow-auto rounded-md p-3 text-xs whitespace-pre-wrap">
            {change.content}
          </pre>
          {resources.length > 0 && (
            <div className="space-y-1">
              <p className="text-xs font-medium">{t("files2")}</p>
              <ul className="text-muted-foreground space-y-0.5 text-xs">
                {resources.map((name) => (
                  <li key={name} className="font-mono">
                    {name}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
