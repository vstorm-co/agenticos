"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import type { AgentEnvironment } from "@/types/agents";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";

interface PublishDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The number the new version will take: one past the newest published. */
  version: number;
  /**
   * Every environment of the agent, so the dialog can say which ones move - or
   * null for an agent nothing reaches through one, like a judge.
   */
  environments: AgentEnvironment[] | null;
  publishing?: boolean;
  draftBreaks?: boolean;
  onTest?: () => void;
  guardNames?: Record<string, string>;
  onConfirm: () => void | Promise<void>;
  /** What the evals said about this draft, said before it goes live. */
  children?: ReactNode;
}

/**
 * What publishing is about to change, said before it happens.
 *
 * Publishing freezes the draft as a version. Followers take it immediately
 * unless guarded, in which case every guard must pass first; pinned
 * environments stay put. The first publish creates the default environment.
 * A breaking draft test makes retesting the primary action, while publishing
 * remains an explicit choice.
 */
export function PublishDialog({
  open,
  onOpenChange,
  version,
  environments,
  publishing,
  draftBreaks = false,
  onTest,
  guardNames = {},
  onConfirm,
  children,
}: PublishDialogProps) {
  const t = useTranslations("agents");
  const tUi = useTranslations("ui");
  const defaultEnvironment = environments?.find((environment) => environment.is_default);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={DIALOG_CONFIRM}>
        <DialogHeader>
          <DialogTitle>{t("publishDialogTitle", { version })}</DialogTitle>
          <DialogDescription>{t("publishFreezesDraft", { version })}</DialogDescription>
        </DialogHeader>
        {children}
        {environments !== null && (
          <div className="text-muted-foreground space-y-1.5 text-sm">
            {/* Where this version lands, environment by environment. Publishing
              mints a version and moves only what asked to be moved, so the one
              question worth answering before the click is "what changes for
              people using this agent" - and for most agents the answer is
              nothing until somebody promotes. */}
            {defaultEnvironment === undefined ? (
              <p>{t("publishFirstCreatesProduction", { version })}</p>
            ) : (
              environments.map((environment) => (
                <p key={environment.id}>
                  {environment.tracks_latest
                    ? environment.guard_suite_ids.length > 0
                      ? t("publishGuardedFollower", {
                          name: environment.name,
                          version,
                          guards: environment.guard_suite_ids.every((id) => guardNames[id])
                            ? environment.guard_suite_ids.map((id) => guardNames[id]).join(", ")
                            : t("publishGuardedChecks", {
                                count: environment.guard_suite_ids.length,
                              }),
                        })
                      : t("publishMovesFollower", { name: environment.name, version })
                    : t("publishPinnedStays", {
                        name: environment.name,
                        version: environment.version,
                      })}
                </p>
              ))
            )}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={publishing}>
            {tUi("cancel")}
          </Button>
          {draftBreaks && onTest && (
            <Button disabled={publishing} onClick={onTest}>
              {t("publishTestDraft")}
            </Button>
          )}
          <Button
            variant={draftBreaks ? "outline" : "default"}
            disabled={publishing}
            onClick={() => void onConfirm()}
          >
            {publishing ? "…" : t(draftBreaks ? "publishAnyway" : "publishConfirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
