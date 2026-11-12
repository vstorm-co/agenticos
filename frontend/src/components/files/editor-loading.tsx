"use client";

import { ExternalLink, MoreHorizontal, Sparkles, UserPlus } from "lucide-react";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import { useTranslations } from "next-intl";
import { Button, DialogFooter, Label, Skeleton } from "@/components/ui";

/** The unloaded editor keeps the same metadata, pane and action slots as its workbench. */
export function EditorLoading({
  kind,
  canEdit = true,
  files = true,
  fullView = false,
}: {
  kind: "skill" | "context";
  canEdit?: boolean;
  files?: boolean;
  fullView?: boolean;
}) {
  const { can } = usePermissions();
  const sharing = useTranslations("sharing");
  const authoring = useTranslations("authoring.context");
  const common = useTranslations("common");
  const skill = useTranslations("skills");
  const context = useTranslations("context");
  const isSkill = kind === "skill";
  return (
    <div
      role="status"
      aria-busy="true"
      aria-label={common("loading")}
      className="flex min-h-0 flex-1 flex-col gap-3"
    >
      <div inert aria-hidden="true" className="flex min-h-0 flex-1 flex-col gap-3">
        {isSkill && (
          <div className="flex shrink-0 gap-2 md:hidden">
            <Skeleton className="touch:min-h-11 h-8 w-28 rounded-lg" />
            <Skeleton className="touch:min-h-11 h-8 w-20 rounded-lg" />
          </div>
        )}
        <div
          className={
            isSkill
              ? "flex shrink-0 flex-wrap items-start gap-4 rounded-md border p-3 max-md:hidden"
              : "shrink-0 space-y-4 rounded-md border p-3 max-md:hidden"
          }
        >
          <div className={isSkill ? "min-w-0 flex-1 basis-72 space-y-1.5" : "space-y-1.5"}>
            <Label>{isSkill ? skill("description3") : context("description")}</Label>
            <Skeleton className="touch:min-h-11 h-10 w-full rounded-md" />
            <p className="text-muted-foreground text-xs">
              {isSkill ? skill("onlyPartModelReads2") : context("shownWhenLinked")}
            </p>
            <p className="text-muted-foreground text-xs">
              {isSkill ? skill("markdownLoadedOnlyAfter") : context("bindingSettingsHint")}
            </p>
            {!isSkill && (
              <p className="text-muted-foreground text-xs">{context("textOnlyBinaryElsewhere")}</p>
            )}
          </div>
          {isSkill && (
            <div className="w-56 shrink-0 space-y-1.5">
              <Label>{skill("category2")}</Label>
              <Skeleton className="touch:min-h-11 h-10 w-full rounded-md" />
              <p className="text-muted-foreground text-xs">{skill("groupsListingNeverReaches")}</p>
            </div>
          )}
        </div>
        <div
          className={
            isSkill
              ? "flex min-h-0 flex-1 flex-col gap-3 md:grid md:grid-cols-[minmax(0,15rem)_minmax(0,1fr)] md:grid-rows-1"
              : "flex min-h-0 flex-1 flex-col"
          }
        >
          {isSkill && (
            <div className="hidden min-h-0 flex-col gap-2 md:flex">
              {canEdit && files && (
                <div className="grid grid-cols-3 gap-1">
                  {[0, 1, 2].map((key) => (
                    <Skeleton key={key} className="touch:min-h-11 h-8 rounded-md" />
                  ))}
                </div>
              )}
              <div className="bg-background min-h-0 flex-1 rounded-xl border p-1">
                <Skeleton className="h-8 w-full rounded-md" />
              </div>
            </div>
          )}
          <FileEditorLoading />
        </div>
        <DialogFooter className="shrink-0 flex-row items-center max-md:pt-2">
          <div className="mr-auto flex items-center gap-2">
            <Skeleton className="inline-flex rounded-lg">
              <Button disabled variant="outline" className="invisible max-md:size-11 max-md:p-0">
                <UserPlus />
                <span className="max-md:sr-only">{sharing("share")}</span>
              </Button>
            </Skeleton>
            {fullView && (
              <Skeleton className="inline-flex rounded-lg">
                <Button disabled variant="outline" className="invisible max-md:size-11 max-md:p-0">
                  <ExternalLink />
                  <span className="max-md:sr-only">{skill("page.openFullView")}</span>
                </Button>
              </Skeleton>
            )}
            {!isSkill && canEdit && can(Perm.runsView) && (
              <Skeleton className="inline-flex rounded-lg">
                <Button disabled variant="outline" className="invisible">
                  <Sparkles />
                  {authoring("improve")}
                </Button>
              </Skeleton>
            )}
            {canEdit && (
              <Skeleton className="inline-flex rounded-lg">
                <Button disabled variant="outline" size="icon" className="invisible">
                  <MoreHorizontal />
                </Button>
              </Skeleton>
            )}
          </div>
          <Skeleton className="inline-flex rounded-lg">
            <Button disabled variant="outline" className="invisible">
              {isSkill
                ? skill(canEdit ? "cancel2" : "close")
                : context(canEdit ? "cancel" : "close")}
            </Button>
          </Skeleton>
          {canEdit && (
            <Skeleton className="inline-flex rounded-lg">
              <Button disabled className="invisible">
                {isSkill ? skill("save") : context("save")}
              </Button>
            </Skeleton>
          )}
        </DialogFooter>
      </div>
    </div>
  );
}

/** A pane-shaped placeholder, including its toolbar rather than one solid rectangle. */
export function FileEditorLoading() {
  return (
    <div
      className="bg-background flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border"
      aria-hidden="true"
    >
      <div className="bg-muted/70 flex items-center gap-2 border-b px-3 py-2">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="touch:min-h-11 ml-auto h-9 w-24 rounded-md" />
        <Skeleton className="touch:min-h-11 h-9 w-9 rounded-md" />
      </div>
      <EditorTextLoading />
    </div>
  );
}

export function EditorTextLoading() {
  return (
    <div aria-hidden="true" className="min-h-0 flex-1 space-y-3 overflow-hidden p-3">
      <Skeleton className="h-4 w-3/5" />
      <Skeleton className="h-4 w-4/5" />
      <Skeleton className="h-4 w-2/3" />
    </div>
  );
}
