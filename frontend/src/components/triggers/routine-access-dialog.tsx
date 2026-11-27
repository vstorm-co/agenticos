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
  modeDefault,
  routineToolIdentity as identity,
  routineToolKey,
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
 * What the review starts from: the routine's own settings (or, before its first
 * review, the proposed ones) and its mode. A tool with none shows its mode's
 * default and is saved without one.
 */
function initial(review: RoutineAccessReview) {
  const tools = new Map<string, RoutineToolSettingValue>();
  for (const tool of review.tools) {
    if (tool.setting !== null) tools.set(identity(tool), tool.setting);
  }
  return {
    tools,
    delegates: review.delegates === "allow" && !review.can_allow ? "ask" : review.delegates,
    mode: review.mode === "trust_agent" && !review.can_trust ? "reviewed" : review.mode,
  } as const;
}

/**
 * What a tool shows and saves: its own setting or its mode's default, narrowed to
 * what the caller may choose - so saving it is never refused.
 */
function toolValue(
  canAllow: boolean,
  tool: RoutineToolOption,
  own: RoutineToolSettingValue | undefined,
  mode: RoutineAccessMode,
): RoutineToolSettingValue {
  const value = own ?? modeDefault(tool, mode);
  return value === "allow" && !mayRunFreely(tool, canAllow, mode) ? "ask" : value;
}

function setAll(
  review: RoutineAccessReview,
  mode: RoutineAccessMode,
  valueOf: (tool: RoutineToolOption) => RoutineToolSettingValue,
  choice: SetAll,
): Record<string, RoutineToolSettingValue> {
  const next: Record<string, RoutineToolSettingValue> = {};
  for (const tool of review.tools) {
    const free = mayRunFreely(tool, review.can_allow, mode);
    // "As the agent" resets every tool; the other two keep a tool that is off, off.
    if (choice === "agent") next[identity(tool)] = free ? "allow" : "ask";
    else if (valueOf(tool) === "off") next[identity(tool)] = "off";
    else next[identity(tool)] = choice === "allow" && free ? "allow" : "ask";
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
  const canAllow = data?.can_allow === true;
  const valueOf = (tool: RoutineToolOption) =>
    toolValue(canAllow, tool, settings.get(identity(tool)), mode);
  const changed =
    !!data &&
    (!data.current ||
      mode !== data.mode ||
      (data.has_delegates && delegates !== data.delegates) ||
      data.tools.some((tool) => valueOf(tool) !== (tool.setting ?? modeDefault(tool, data.mode))));
  const counts = { allow: 0, ask: 0, off: 0 };
  for (const tool of data?.tools ?? []) counts[valueOf(tool)] += 1;
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
        // Only the routine's own settings: a tool left out takes its mode's default.
        tools: review.tools.flatMap((tool: RoutineToolOption) =>
          settings.has(identity(tool)) ? [{ ...routineToolKey(tool), setting: valueOf(tool) }] : [],
        ),
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
                    mode={mode}
                    valueOf={valueOf}
                    delegates={delegates}
                    disabled={pending}
                    onTool={(tool, value) => choose({ tools: { [identity(tool)]: value } })}
                    onDelegates={(value) => choose({ delegates: value })}
                    onSetAll={(all) =>
                      choose({
                        tools: setAll(data, mode, valueOf, all),
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
