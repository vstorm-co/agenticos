"use client";

import { useState } from "react";
import { Check, ArrowRight, BookOpen, GitPullRequest, Users, X } from "lucide-react";

import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
  Skeleton,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { EvidenceList, RationaleText } from "@/components/authoring/evidence-list";
import { GoesLive } from "@/components/authoring/goes-live";
import { useSkillChanges } from "@/hooks";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import { ROUTES } from "@/lib/constants";
import type { SkillChangeRecord } from "@/lib/skill-changes-api";
import { DIALOG_BROAD, DIALOG_COLUMN, DIALOG_BODY } from "@/lib/dialog-sizes";
import { useSkill } from "@/hooks/use-skills";
import { DiffView } from "@/components/authoring/diff-view";
import { MarkdownContent } from "@/components/chat/markdown-content";
import { SkillCheckDialog } from "./skill-check-dialog";
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
  const canReadRuns = usePermissions().can(Perm.runsView);
  const t = useTranslations("skills");
  const { changes, error, apply, discard, isDeciding } = useSkillChanges("pending");

  if (!canEdit || !canReadRuns) return null;
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
            {t("reviewUpdates.title")}
          </CardTitle>
          <CardDescription className="text-xs">
            {t("reviewUpdates.summary", { count: changes.length })}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="divide-border @container divide-y p-0">
        {changes.map((change) => (
          <ChangeRow
            key={change.id}
            change={change}
            disabled={isDeciding}
            onApply={() => void apply(change)}
            onDiscard={() => void discard(change)}
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
  const [checking, setChecking] = useState(false);
  const resources = Object.keys(change.resources);
  const current = useSkill(open ? change.skill_id : null);
  // A change to a skill agents already use goes live only through a check on them.
  const skillId = change.skill_id;

  return (
    <div className="grid gap-3 px-5 py-4 @3xl:grid-cols-[minmax(0,1fr)_auto] @3xl:items-center">
      <div className="min-w-0 space-y-2">
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm">{change.name}</span>
            {change.skill_id === null ? (
              <Badge variant="secondary">{t("newSkill2")}</Badge>
            ) : (
              <Badge variant="outline">{t("edit")}</Badge>
            )}
          </div>
          <p className="text-muted-foreground line-clamp-2 text-xs leading-relaxed">
            {change.description || t("noDescriptionWorthAdding")}
          </p>
          <div className="text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
            <span className="inline-flex items-center gap-1.5">
              <Users className="size-3.5" aria-hidden />
              {t("reviewUpdates.agents", { count: change.reaches.length + change.reaches_hidden })}
            </span>
            {resources.length > 0 && (
              <span>{t("reviewUpdates.files", { count: resources.length })}</span>
            )}
            {change.source === "library" && (
              <span className="inline-flex items-center gap-1.5">
                <BookOpen className="size-3.5" aria-hidden />
                {t("reviewUpdates.library")}
              </span>
            )}
          </div>
          {change.conversation_id !== null && (
            <a
              className="text-muted-foreground text-xs underline"
              href={`${ROUTES.CHAT}?c=${change.conversation_id}`}
            >
              {t("readConversationCameFrom")}
            </a>
          )}
        </div>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-1 @3xl:justify-end">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-label={t("showWhatChangedIn", { name: change.name })}
        >
          <ArrowRight className="h-4 w-4" aria-hidden />
          {t("review")}
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
        {skillId === null ? (
          <Button
            variant="outline"
            size="sm"
            disabled={disabled}
            onClick={onApply}
            aria-label={t("applyChangeTo", { name: change.name })}
          >
            <Check className="h-4 w-4" aria-hidden />
            {t("apply")}
          </Button>
        ) : (
          <>
            <Button
              variant="outline"
              size="sm"
              disabled={disabled}
              onClick={() => setChecking(true)}
              aria-label={t("checkChangeTo", { name: change.name })}
            >
              <Check className="h-4 w-4" aria-hidden />
              {t("checkOnAgents")}
            </Button>
            {checking && (
              <SkillCheckDialog
                skillId={skillId}
                change={{ proposalId: change.id }}
                forkId={change.fork_id}
                onOpenChange={setChecking}
              />
            )}
          </>
        )}
      </div>

      {open && (
        <Dialog open onOpenChange={setOpen}>
          <DialogContent className={`${DIALOG_BROAD} ${DIALOG_COLUMN}`}>
            <DialogHeader>
              <DialogTitle>{change.name}</DialogTitle>
              <DialogDescription>
                {change.description || t("noDescriptionWorthAdding")}
              </DialogDescription>
            </DialogHeader>
            <div className={`${DIALOG_BODY} space-y-4`}>
              <div className="bg-muted/40 rounded-lg border p-3">
                <p className="mb-2 text-xs font-medium">{t("reviewUpdates.impact")}</p>
                <GoesLive
                  reaches={change.reaches}
                  hidden={change.reaches_hidden}
                  afterCheck={skillId !== null}
                />
              </div>
              {change.rationale && (
                <RationaleText text={change.rationale} evidence={change.evidence ?? []} />
              )}
              {change.expected_effect && (
                <p className="text-sm">
                  <span className="font-medium">{t("expectedEffect")}</span>{" "}
                  {change.expected_effect}
                </p>
              )}
              {change.authoring_request_id != null && (
                <EvidenceList
                  items={change.evidence ?? []}
                  dropped={change.evidence_dropped ?? 0}
                />
              )}
              <div className="min-w-0 rounded-lg border p-4 text-sm">
                <p className="text-muted-foreground mb-3 text-xs font-medium">
                  {t("reviewUpdates.instructions")}
                </p>
                <Tabs defaultValue="preview">
                  <TabsList>
                    <TabsTrigger value="preview">{t("reviewUpdates.preview")}</TabsTrigger>
                    {skillId !== null && (
                      <TabsTrigger value="changes">{t("reviewUpdates.compare")}</TabsTrigger>
                    )}
                  </TabsList>
                  <TabsContent value="preview">
                    <MarkdownContent content={change.content} inertImages highlightVariables />
                  </TabsContent>
                  {skillId !== null && (
                    <TabsContent value="changes">
                      {current.error ? (
                        <p role="alert" className="text-destructive text-sm">
                          {t("reviewUpdates.compareFailed")}
                        </p>
                      ) : current.isLoading || !current.skill ? (
                        <Skeleton className="h-40 w-full" />
                      ) : (
                        <DiffView before={current.skill.content} after={change.content} />
                      )}
                    </TabsContent>
                  )}
                </Tabs>
              </div>
              {resources.length > 0 && (
                <div className="space-y-1">
                  <p className="text-xs font-medium">{t("files2")}</p>
                  <ul className="text-muted-foreground space-y-0.5 text-xs">
                    {resources.map((name) => (
                      <li key={name}>
                        <details className="rounded-md border">
                          <summary className="cursor-pointer px-3 py-2 font-mono">{name}</summary>
                          <pre className="bg-muted/30 max-h-64 overflow-auto border-t p-3 font-mono text-xs break-words whitespace-pre-wrap">
                            {change.resources[name]}
                          </pre>
                        </details>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
            <DialogFooter className="border-t pt-4">
              <Button variant="outline" onClick={() => setOpen(false)}>
                {t("reviewUpdates.close")}
              </Button>
              <Button
                disabled={disabled}
                onClick={() => {
                  setOpen(false);
                  if (skillId === null) onApply();
                  else setChecking(true);
                }}
              >
                {skillId === null ? t("apply") : t("checkOnAgents")}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
