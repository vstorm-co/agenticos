"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { ErrorState } from "@/components/states/error-state";
import { RoutineAccessBanner } from "@/components/triggers/routine-access-banner";
import { RoutineAccessSources } from "@/components/triggers/routine-access-sources";
import { RoutineAccessTools, type SetAll } from "@/components/triggers/routine-access-tools";
import { RoutineAccessTrust } from "@/components/triggers/routine-access-trust";
import {
  Alert,
  AlertDescription,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Spinner,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  TooltipProvider,
} from "@/components/ui";
import { isStaleReview, useRoutineAccess } from "@/hooks/use-routine-access";
import { DIALOG_COLUMN, DIALOG_WIDE } from "@/lib/dialog-sizes";
import {
  mayRunFreely,
  routineToolIdentity as identity,
  routineToolKey,
  shownSetting,
  type RoutineAccessMode,
  type RoutineAccessReview,
  type RoutineDelegateSetting,
  type RoutineToolOption,
  type RoutineToolSettingValue,
} from "@/lib/routine-access-api";
import { cn } from "@/lib/utils";
import type { Trigger } from "@/types/triggers";

export type RoutineAccessTab = "tools" | "sources";

/** The creator's choices on top of one review, dropped when the review changes. */
interface Choice {
  token: string;
  tools: Record<string, RoutineToolSettingValue>;
  delegates?: RoutineDelegateSetting;
  mode?: RoutineAccessMode;
}

/**
 * What the review starts from: the stored settings, with anything the creator may
 * no longer choose narrowed to what they may - so saving it is never refused.
 */
function initial(review: RoutineAccessReview) {
  const tools = new Map<string, RoutineToolSettingValue>();
  for (const tool of review.tools) {
    const shown = shownSetting(tool);
    tools.set(
      identity(tool),
      shown === "allow" && !mayRunFreely(tool, review.can_allow) ? "ask" : shown,
    );
  }
  return {
    tools,
    delegates: review.delegates === "allow" && !review.can_allow ? "ask" : review.delegates,
    mode: review.mode === "trust_agent" && !review.can_trust ? "reviewed" : review.mode,
  } as const;
}

function setAll(
  review: RoutineAccessReview,
  current: ReadonlyMap<string, RoutineToolSettingValue>,
  choice: SetAll,
): Record<string, RoutineToolSettingValue> {
  const next: Record<string, RoutineToolSettingValue> = {};
  for (const tool of review.tools) {
    const key = identity(tool);
    const free = mayRunFreely(tool, review.can_allow);
    // "As the agent" resets every tool; the other two keep a tool that is off, off.
    if (choice === "agent") next[key] = free ? "allow" : "ask";
    else if (current.get(key) === "off") next[key] = "off";
    else next[key] = choice === "allow" && free ? "allow" : "ask";
  }
  return next;
}

/**
 * A routine's one access review: a setting for each tool its agent gives it, the
 * sources it reaches, and - where allowed - trusting the agent outright.
 *
 * With `onSaved` it finishes a routine's setup: saving enables it.
 */
export function RoutineAccessDialog({
  trigger,
  initialTab = "tools",
  onClose,
  onSaved,
}: {
  trigger: Trigger;
  initialTab?: RoutineAccessTab;
  onClose: () => void;
  /** Finish a paused routine's setup once its access is saved. */
  onSaved?: () => Promise<void>;
}) {
  const t = useTranslations("triggers.access");
  const triggers = useTranslations("triggers");
  const common = useTranslations("common");
  const { data, isLoading, error, refetch, save } = useRoutineAccess(trigger.agent_id, trigger.id);
  const [tab, setTab] = useState<RoutineAccessTab>(initialTab);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [finishing, setFinishing] = useState(false);
  const pending = save.isPending || finishing;
  const start = data ? initial(data) : null;
  const ours = data && choice?.token === data.review_token ? choice : null;
  const settings = new Map(start?.tools);
  for (const [key, value] of Object.entries(ours?.tools ?? {})) settings.set(key, value);
  const delegates = ours?.delegates ?? start?.delegates ?? "ask";
  const mode = ours?.mode ?? start?.mode ?? "reviewed";
  const changed =
    !!data &&
    (!data.current ||
      mode !== data.mode ||
      (data.has_delegates && delegates !== data.delegates) ||
      data.tools.some((tool) => tool.setting !== settings.get(identity(tool))));
  const counts = { allow: 0, ask: 0, off: 0 };
  for (const value of settings.values()) counts[value] += 1;
  const blocked = !data || data.required_unavailable_sources.length > 0;
  const choose = (update: Partial<Omit<Choice, "token">>) =>
    data &&
    setChoice({
      token: data.review_token,
      tools: { ...ours?.tools, ...update.tools },
      delegates: update.delegates ?? ours?.delegates,
      mode: update.mode ?? ours?.mode,
    });

  async function submit(review: RoutineAccessReview) {
    try {
      await save.mutateAsync({
        review_token: review.review_token,
        mode,
        tools: review.tools.map((tool: RoutineToolOption) => ({
          ...routineToolKey(tool),
          setting: settings.get(identity(tool)) ?? "ask",
        })),
        delegates,
      });
      if (onSaved) {
        setFinishing(true);
        await onSaved();
      }
      onClose();
    } catch {
      // The hook reports the refusal and reads the review again; the dialog stays
      // open on the refreshed review rather than closing on a choice not saved.
    } finally {
      setFinishing(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !pending && onClose()}>
      <DialogContent className={cn(DIALOG_WIDE, DIALOG_COLUMN)}>
        <DialogHeader>
          <DialogTitle>
            {t("title", { named: trigger.name ? "yes" : "no", name: trigger.name ?? "" })}
          </DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
          {isLoading ? (
            <Spinner />
          ) : error || !data ? (
            <ErrorState cta={{ label: t("retry"), onClick: () => void refetch() }} />
          ) : (
            // Its own provider: the dialog opens from places that mount none.
            <TooltipProvider>
              {isStaleReview(save.error) && (
                <Alert variant="warning">
                  <AlertDescription>{t("stale")}</AlertDescription>
                </Alert>
              )}
              <RoutineAccessBanner agentId={trigger.agent_id} review={data} />
              <Tabs value={tab} onValueChange={(next) => setTab(next as RoutineAccessTab)}>
                <TabsList>
                  <TabsTrigger value="tools">{t("tabTools")}</TabsTrigger>
                  <TabsTrigger value="sources">{t("tabSources")}</TabsTrigger>
                </TabsList>
                <TabsContent value="tools" className="pt-3">
                  <RoutineAccessTools
                    agentId={trigger.agent_id}
                    review={data}
                    settings={settings}
                    delegates={delegates}
                    disabled={pending}
                    onTool={(tool, value) => choose({ tools: { [identity(tool)]: value } })}
                    onDelegates={(value) => choose({ delegates: value })}
                    onSetAll={(all) =>
                      choose({
                        tools: setAll(data, settings, all),
                        delegates: all !== "ask" && data.can_allow ? "allow" : "ask",
                      })
                    }
                  />
                </TabsContent>
                <TabsContent value="sources" className="pt-3">
                  <RoutineAccessSources agentId={trigger.agent_id} review={data} />
                </TabsContent>
              </Tabs>
              <RoutineAccessTrust
                review={data}
                mode={mode}
                disabled={pending}
                onChange={(next) => choose({ mode: next })}
              />
            </TooltipProvider>
          )}
        </div>
        {data && (
          <p role="status" className="text-muted-foreground text-sm">
            {t("summary", counts)}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" disabled={pending} onClick={onClose}>
            {onSaved ? triggers("finishLater") : common("cancel")}
          </Button>
          <Button
            disabled={pending || blocked || !!error || (!onSaved && !changed)}
            onClick={() => data && void submit(data)}
          >
            {onSaved ? t("saveAndEnable") : t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
