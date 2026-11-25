"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { DIALOG_COLUMN, DIALOG_WIDE } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { SourceConsentsPanel } from "@/components/triggers/source-consents-panel";
import { RoutineToolSelection } from "@/components/triggers/routine-tool-selection";
import { useRoutineTools } from "@/hooks/use-routine-tools";
import { useRoutineSources } from "@/hooks/use-routine-sources";
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
  routineToolIdentity,
  routineToolKey,
  type RoutineToolOptions,
  type RoutineToolSettingValue,
} from "@/lib/routine-tools-api";
import {
  routineSourceBlockers,
  type RoutineSourceMode,
  type RoutineSourceReview,
} from "@/lib/routine-sources-api";

/** Source access and per-tool restrictions are saved explicitly, without waiving agent approvals. */
export function ActionConsentsDialog({
  trigger,
  onClose,
  onSaved,
}: {
  trigger: Trigger;
  onClose: () => void;
  onSaved?: () => Promise<void>;
}) {
  const t = useTranslations("triggers.toolSettings");
  const setup = useTranslations("triggers");
  const common = useTranslations("common");
  const sources = useRoutineSources(trigger.agent_id, trigger.id);
  const sourceReview = sources.data;
  const [sourceChoice, setSourceChoice] = useState<{
    token: string;
    mode: RoutineSourceMode;
  } | null>(null);
  const sourceMode =
    (sourceChoice?.token === sourceReview?.review_token ? sourceChoice?.mode : undefined) ??
    sourceReview?.mode ??
    "restricted";
  const tools = useRoutineTools(trigger.agent_id, trigger.id, { enabled: !!sourceReview });
  const data = tools.data;
  const [choice, setChoice] = useState<{
    data: RoutineToolOptions;
    selected: Map<string, RoutineToolSettingValue>;
  } | null>(null);
  const selected =
    choice !== null && choice.data === data
      ? choice.selected
      : new Map(
          data === undefined
            ? []
            : [
                ...data.items.flatMap((item) =>
                  item.setting === null ? [] : [[routineToolIdentity(item), item.setting] as const],
                ),
                ...data.unavailable_settings.map(
                  (item) => [routineToolIdentity(item), item.setting] as const,
                ),
              ],
        );
  const [saving, setSaving] = useState(false);
  const pending = saving || tools.replace.isPending || sources.replace.isPending;
  const sourceUnavailable =
    !sourceReview ||
    !!sources.error ||
    sources.isLoading ||
    routineSourceBlockers(sourceReview, sourceMode).length > 0;
  async function save(data: RoutineToolOptions, sourceReview: RoutineSourceReview) {
    setSaving(true);
    try {
      if (onSaved || !sourceReview.current || sourceMode !== (sourceReview.mode ?? "restricted")) {
        await sources.replace.mutateAsync({
          review_token: sourceReview.review_token,
          mode: sourceMode,
        });
      }
      await tools.replace.mutateAsync(
        [...data.items, ...data.unavailable_settings].flatMap((item) => {
          const setting = selected.get(routineToolIdentity(item));
          return setting ? [{ ...routineToolKey(item), setting }] : [];
        }),
      );
      await onSaved?.();
      onClose();
    } catch {
      // The mutation reports the refusal; keep the dialog open for correction.
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
              sourceReview && setSourceChoice({ token: sourceReview.review_token, mode })
            }
          />
          {tools.isLoading ? (
            <Spinner />
          ) : tools.error ? (
            <ErrorState cta={{ label: common("retry"), onClick: () => void tools.refetch() }} />
          ) : (
            data && (
              <>
                {trigger.action_mode !== "agent" && (
                  <p className="bg-muted/50 rounded-lg border p-3 text-sm">{t("legacyMode")}</p>
                )}
                {data.unavailable_sources.length > 0 && (
                  <p className="text-muted-foreground text-sm">
                    {t("unavailable", { names: data.unavailable_sources.join(", ") })}
                  </p>
                )}
                {data.unavailable_settings.some((item) =>
                  selected.has(routineToolIdentity(item)),
                ) && (
                  <section className="space-y-2 rounded-lg border p-3">
                    <h3 className="text-sm font-medium">{t("unavailableSettings")}</h3>
                    <p className="text-muted-foreground text-xs">{t("unavailableSettingsBody")}</p>
                    {data.unavailable_settings
                      .filter((item) => selected.has(routineToolIdentity(item)))
                      .map((item) => (
                        <div
                          key={routineToolIdentity(item)}
                          className="flex items-center justify-between gap-3 text-sm"
                        >
                          <span className="min-w-0 break-words">
                            {item.tool_id} · {t(item.setting)}
                            <span className="text-muted-foreground block text-xs break-all">
                              {routineToolIdentity(item)}
                            </span>
                          </span>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            disabled={pending}
                            aria-label={t("removeRestriction", {
                              name: `${item.tool_id} (${routineToolIdentity(item)})`,
                            })}
                            onClick={() => {
                              const next = new Map(selected);
                              next.delete(routineToolIdentity(item));
                              setChoice({ data, selected: next });
                            }}
                          >
                            {common("delete")}
                          </Button>
                        </div>
                      ))}
                  </section>
                )}
                <RoutineToolSelection
                  items={data.items}
                  selected={selected}
                  disabled={pending}
                  onChange={(settings) => setChoice({ data, selected: settings })}
                />
              </>
            )
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" disabled={pending} onClick={onClose}>
            {onSaved ? setup("finishLater") : common("cancel")}
          </Button>
          <Button
            disabled={!data || !!tools.error || pending || sourceUnavailable}
            loading={pending}
            onClick={data && sourceReview ? () => void save(data, sourceReview) : undefined}
          >
            {onSaved ? setup("enableRoutine") : common("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
