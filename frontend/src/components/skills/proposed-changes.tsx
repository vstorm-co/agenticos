"use client";

import { useMemo, useState } from "react";
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
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui";
import { EvidenceList, RationaleText } from "@/components/authoring/evidence-list";
import { useSkillChanges } from "@/hooks";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import { ROUTES } from "@/lib/constants";
import type { SkillChangeRecord } from "@/lib/skill-changes-api";
import { DIALOG_CANVAS, DIALOG_FILL } from "@/lib/dialog-sizes";
import {
  useSkillProposalBaseline,
  useSkillProposalFile,
} from "@/hooks/use-skill-proposal-baseline";
import { FileTree } from "./skill-files";
import { buildTree } from "@/lib/file-tree";
import { UsedBy } from "@/components/agents/used-by";
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
            onApply={() => apply(change)}
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
  onApply: () => Promise<void>;
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
  const current = useSkillProposalBaseline(open ? change.skill_id : null, change.fork_id);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const oldFile = current.data?.resources.find((file) => file.name === selectedFile);
  const originalFile = useSkillProposalFile(
    open ? change.skill_id : null,
    current.data?.id ?? null,
    oldFile?.name ?? null,
  );
  const fileNames = useMemo(
    () =>
      [
        ...new Set([
          ...Object.keys(change.resources),
          ...(current.data?.resources.map((file) => file.name) ?? []),
        ]),
      ].sort(),
    [change.resources, current.data],
  );
  const files = useMemo(
    () => buildTree(fileNames.map((name) => ({ id: name, name, size_bytes: 0 }))),
    [fileNames],
  );
  const after =
    selectedFile === null
      ? change.content
      : (change.resources[selectedFile] ??
        (change.source === "library" ? "" : (originalFile.data?.content ?? "")));
  const before =
    selectedFile === null ? (current.data?.content ?? "") : (originalFile.data?.content ?? "");
  const comparing = selectedFile === null ? current : originalFile;
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
        {skillId !== null && checking && (
          <SkillCheckDialog
            skillId={skillId}
            change={{ proposalId: change.id }}
            forkId={change.fork_id}
            onOpenChange={setChecking}
          />
        )}
      </div>

      {open && (
        <Dialog open onOpenChange={setOpen}>
          <DialogContent className={`${DIALOG_CANVAS} ${DIALOG_FILL}`}>
            <DialogHeader>
              <DialogTitle>{change.name}</DialogTitle>
              <DialogDescription className="line-clamp-2 md:line-clamp-none">
                {change.description || t("noDescriptionWorthAdding")}
              </DialogDescription>
            </DialogHeader>
            <div className="bg-muted/30 rounded-lg border px-3 py-2 text-xs">
              {!(change.reaches.length === 0 && change.reaches_hidden > 0) && (
                <UsedBy
                  agents={change.reaches.map((agent) => ({
                    ...agent,
                    slug: agent.slug ?? undefined,
                  }))}
                  className="text-foreground gap-2"
                />
              )}
              {change.reaches_hidden > 0 && (
                <p className="text-muted-foreground mt-1">
                  {t("reviewUpdates.hiddenAgents", { count: change.reaches_hidden })}
                </p>
              )}
              {(change.rationale || change.expected_effect || change.authoring_request_id) && (
                <details className="mt-2">
                  <summary className="cursor-pointer">{t("reviewUpdates.impact")}</summary>
                  {change.rationale && (
                    <RationaleText text={change.rationale} evidence={change.evidence ?? []} />
                  )}
                  {change.expected_effect && <p className="mt-2">{change.expected_effect}</p>}
                  {change.authoring_request_id != null && (
                    <EvidenceList
                      items={change.evidence ?? []}
                      dropped={change.evidence_dropped ?? 0}
                    />
                  )}
                </details>
              )}
            </div>
            <div className="flex min-h-0 flex-1 flex-col gap-3 md:grid md:grid-cols-[minmax(0,15rem)_minmax(0,1fr)] md:grid-rows-1">
              <div className="shrink-0 md:hidden">
                <Select
                  value={selectedFile === null ? "instructions" : `file:${selectedFile}`}
                  onValueChange={(value) =>
                    setSelectedFile(value === "instructions" ? null : value.slice(5))
                  }
                >
                  <SelectTrigger aria-label={t("fileTree")} className="w-full min-w-0">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="instructions">{t("reviewUpdates.instructions")}</SelectItem>
                    {fileNames.map((name) => (
                      <SelectItem key={name} value={`file:${name}`}>
                        {name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <nav
                className="hidden overflow-auto rounded-lg border p-2 md:block"
                aria-label={t("fileTree")}
              >
                <Button
                  className="mb-1 w-full justify-start"
                  variant={selectedFile === null ? "secondary" : "ghost"}
                  onClick={() => setSelectedFile(null)}
                >
                  <BookOpen className="size-4" aria-hidden />
                  {t("reviewUpdates.instructions")}
                </Button>
                <FileTree nodes={files} openId={selectedFile} onOpen={setSelectedFile} />
              </nav>
              <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-lg border">
                <div className="bg-muted/30 truncate border-b px-3 py-2 text-xs font-medium md:px-4 md:py-3 md:text-sm">
                  {selectedFile ?? t("reviewUpdates.instructions")}
                </div>
                <Tabs defaultValue="changes" className="flex min-h-0 flex-1 flex-col p-3">
                  <TabsList className="shrink-0">
                    <TabsTrigger value="changes" aria-label={t("reviewUpdates.compare")}>
                      <span className="max-sm:hidden">{t("reviewUpdates.compare")}</span>
                      <span className="sm:hidden">{t("reviewUpdates.compareShort")}</span>
                    </TabsTrigger>
                    <TabsTrigger value="preview">{t("reviewUpdates.preview")}</TabsTrigger>
                  </TabsList>
                  <TabsContent value="changes" className="min-h-0 flex-1 overflow-auto">
                    {comparing.error ? (
                      <p role="alert" className="text-destructive text-sm">
                        {t("reviewUpdates.compareFailed")}
                      </p>
                    ) : current.isLoading || comparing.isLoading ? (
                      <Skeleton className="h-40 w-full" />
                    ) : (
                      <>
                        {selectedFile === null &&
                          current.data?.description !== change.description && (
                            <div className="mb-3">
                              <DiffView
                                before={current.data?.description ?? ""}
                                after={change.description}
                                fill
                                modes={false}
                              />
                            </div>
                          )}
                        <DiffView
                          key={selectedFile ?? "instructions"}
                          before={before}
                          after={after}
                          fill
                          modes={false}
                        />
                      </>
                    )}
                  </TabsContent>
                  <TabsContent value="preview" className="min-h-0 flex-1 overflow-auto px-1">
                    {originalFile.isLoading &&
                    selectedFile !== null &&
                    !(selectedFile in change.resources) ? (
                      <Skeleton className="h-40 w-full" />
                    ) : selectedFile === null || /\.mdx?$/i.test(selectedFile) ? (
                      <MarkdownContent content={after} inertImages highlightVariables />
                    ) : (
                      <pre className="font-mono text-xs break-words whitespace-pre-wrap">
                        {after}
                      </pre>
                    )}
                  </TabsContent>
                </Tabs>
              </div>
            </div>
            <DialogFooter className="border-t pt-4 max-sm:flex-row max-sm:items-center">
              {skillId !== null && (
                <Button
                  variant="outline"
                  className="max-sm:min-w-0 max-sm:flex-1 max-sm:px-2 max-sm:text-xs"
                  aria-label={t("reviewUpdates.testOptional")}
                  disabled={disabled}
                  onClick={() => {
                    setOpen(false);
                    setChecking(true);
                  }}
                >
                  <span className="max-sm:hidden">{t("reviewUpdates.testOptional")}</span>
                  <span className="sm:hidden">{t("reviewUpdates.testOptionalShort")}</span>
                </Button>
              )}
              <Button
                className="max-sm:min-w-0 max-sm:flex-1 max-sm:px-2 max-sm:text-xs"
                disabled={disabled}
                onClick={async () => {
                  try {
                    await onApply();
                    setOpen(false);
                  } catch {
                    // The mutation reports the refusal; keep the review available.
                  }
                }}
              >
                <Check className="size-4" aria-hidden />
                {t("reviewUpdates.apply")}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
