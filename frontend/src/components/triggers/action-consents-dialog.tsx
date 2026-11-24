"use client";

import { ActionSelection } from "./action-selection";
import { DIALOG_COLUMN, DIALOG_WIDE } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { SourceConsentsPanel } from "@/components/triggers/source-consents-panel";
import Link from "next/link";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { useRoutineActions } from "@/hooks/use-routine-actions";
import { useRoutineSources } from "@/hooks/use-routine-sources";
import { useOrgStore } from "@/stores";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Spinner,
} from "@/components/ui";
import { ErrorState } from "@/components/states/error-state";
import type { Trigger } from "@/types/triggers";
import {
  routineActionIdentity as identity,
  routineActionKey,
  type RoutineActionOptions,
} from "@/lib/routine-actions-api";
import {
  routineSourceBlockers,
  type RoutineSourceReview,
  type RoutineSourceMode,
} from "@/lib/routine-sources-api";

export function ActionConsentsDialog({
  trigger,
  onClose,
  onSaved,
}: {
  trigger: Trigger;
  onClose: () => void;
  /** Finish a newly created routine only after its displayed access is saved. */
  onSaved?: () => Promise<void>;
}) {
  const t = useTranslations("triggers.actionConsents");
  const setup = useTranslations("triggers");
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const sources = useRoutineSources(trigger.agent_id, trigger.id);
  const sourcesData = sources.data;
  const [sourceChoice, setSourceChoice] = useState<{
    token: string;
    mode: RoutineSourceMode;
  } | null>(null);
  const sourceMode =
    (sourceChoice?.token === sourcesData?.review_token ? sourceChoice?.mode : undefined) ??
    sourcesData?.mode ??
    "restricted";
  const sourceNeedsSave =
    !!sourcesData && (!sourcesData.current || sourceMode !== (sourcesData.mode ?? "restricted"));
  const [saving, setSaving] = useState(false);
  const { data, isLoading, error, replace, refetch } = useRoutineActions(
    trigger.agent_id,
    trigger.id,
    { enabled: !!sourcesData },
  );
  const [chosen, setChosen] = useState<{ token: string; keys: Set<string> } | null>(null);
  const selected =
    (chosen?.token === data?.review_token ? chosen?.keys : null) ??
    new Set(data?.items.filter((item) => item.consented && item.waivable).map(identity));
  const maxActions = data?.max_actions ?? 100;
  const overLimit = selected.size > maxActions;
  const pending = saving || replace.isPending || sources.replace.isPending;
  const sourceUnavailable =
    !sources.data ||
    !!sources.error ||
    sources.isLoading ||
    routineSourceBlockers(sources.data, sourceMode).length > 0;
  async function save(data: RoutineActionOptions | undefined, sourceReview: RoutineSourceReview) {
    if (!data) return;
    setSaving(true);
    try {
      if (onSaved || sourceNeedsSave)
        await sources.replace.mutateAsync({
          review_token: sourceReview.review_token,
          mode: sourceMode,
        });
      if (data.can_waive || onSaved) {
        await replace.mutateAsync(
          data.can_waive
            ? data.items
                .filter((item) => item.waivable && selected.has(identity(item)))
                .map(routineActionKey)
            : [],
        );
      }
      await onSaved?.();
      onClose();
    } catch {
      // Each mutation reports its refusal and refreshes its review; keep the
      // displayed selection available for correction instead of closing it.
    } finally {
      setSaving(false);
    }
  }
  return (
    <Dialog open onOpenChange={(open) => !open && !pending && onClose()}>
      <DialogContent className={cn(DIALOG_WIDE, DIALOG_COLUMN)}>
        <DialogHeader>
          <DialogTitle>{onSaved ? setup("setupReviewTitle") : t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
          <SourceConsentsPanel
            trigger={trigger}
            showApprove={false}
            mode={sourceMode}
            disabled={pending}
            onModeChange={(mode) =>
              sourcesData && setSourceChoice({ token: sourcesData.review_token, mode })
            }
          />
          {isLoading ? (
            <Spinner />
          ) : error ? (
            <ErrorState cta={{ label: t("retry"), onClick: () => void refetch() }} />
          ) : (
            data && (
              <div className="space-y-4">
                {!data.can_waive && (
                  // Which half refused, so a greyed-out list does not read as broken.
                  <div role="note" className="bg-muted/50 space-y-1 rounded-lg border p-3 text-sm">
                    <p>
                      {t(
                        data.waive_blocked_reason === "permission"
                          ? "notAllowedPermission"
                          : "notAllowedOrganization",
                      )}
                    </p>
                    {/* The organization half is refused only to a caller who may decide
                        approvals, which is who can change the setting. */}
                    {data.waive_blocked_reason === "organization" && activeOrgId && (
                      <Link
                        href={`/orgs/${activeOrgId}/members?tab=governance`}
                        className="text-foreground underline underline-offset-4"
                      >
                        {t("openApprovalSettings")}
                      </Link>
                    )}
                  </div>
                )}
                {!!data.unavailable_sources?.length && (
                  <p className="text-muted-foreground text-sm">
                    {t("checkConnections", { names: data.unavailable_sources.join(", ") })}
                  </p>
                )}
                {!data.items.some((item) => item.waivable) && (
                  <p className="text-muted-foreground text-sm">{t("empty")}</p>
                )}
                {data.review_changes?.map((change) => (
                  <p key={change} role="status" className="text-sm">
                    {t(`changed.${change}`)}
                  </p>
                ))}
                {data.items.some(
                  (item) => item.previously_consented && !item.consented && item.waivable,
                ) && (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={pending || !data.can_waive}
                    onClick={() =>
                      setChosen({
                        token: data.review_token,
                        keys: new Set([
                          ...selected,
                          ...data.items
                            .filter((item) => item.previously_consented && item.waivable)
                            .map(identity),
                        ]),
                      })
                    }
                  >
                    {t("reselectPrevious")}
                  </Button>
                )}
                {overLimit && (
                  <p role="alert" className="text-sm">
                    {t("tooMany", { count: selected.size, limit: maxActions })}
                  </p>
                )}
                <ActionSelection
                  items={data.items}
                  selected={selected}
                  disabled={pending || !data.can_waive}
                  onChange={(keys) => setChosen({ token: data.review_token, keys })}
                />
              </div>
            )
          )}
        </div>
        <DialogFooter>
          {onSaved && (
            <Button variant="outline" disabled={pending} onClick={onClose}>
              {setup("finishLater")}
            </Button>
          )}
          {!onSaved && (
            <Button
              variant="outline"
              disabled={!data || pending}
              onClick={() => replace.mutate([], { onSuccess: onClose })}
            >
              {t("revokeAll")}
            </Button>
          )}
          <Button
            disabled={
              pending ||
              sourceUnavailable ||
              !data ||
              !!error ||
              isLoading ||
              overLimit ||
              (!data.can_waive && !onSaved && !sourceNeedsSave)
            }
            onClick={sourcesData ? () => void save(data, sourcesData) : undefined}
          >
            {onSaved
              ? setup("enableRoutine")
              : sourceMode === "follow_agent"
                ? setup("sourceConsents.saveMode")
                : t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
