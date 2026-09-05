"use client";

import { useMemo, useState } from "react";
import { ChevronDown, Sliders } from "lucide-react";
import { useTranslations } from "next-intl";

import { ChatModelPicker } from "./chat-model-picker";
import { YourConnections } from "./your-connections";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import { useModelProviders, useOrganizationList, usePermissions } from "@/hooks";
import { useConversationStore, useOrgStore } from "@/stores";
import type { PublishedModel } from "@/types/agents";
import { Perm } from "@/types/permissions";
import { cn } from "@/lib/utils";

/** Offered in this order: what the agent says, then looser, then tighter. */
const APPROVAL_MODES: readonly ApprovalMode[] = ["follow_agent", "approve_all", "ask_all"];

/** The three answers to "how much do I want to be asked", server-side names. */
export type ApprovalMode = "follow_agent" | "approve_all" | "ask_all";

interface ChatControlsProps {
  /** The model profile this conversation runs on, or null for the agent's own. */
  onModelProfileChange?: (profileId: string | null) => void;
  /** How much this conversation wants to be asked before a gated tool runs. */
  onApprovalModeChange?: (mode: ApprovalMode) => void;
  /** The selected agent's published model, shown as current when there is no override. */
  agentModel?: PublishedModel | null;
}

/**
 * What this conversation overrides, for the turns it sends.
 *
 * One thing: which of the organization's models to spend, recorded on the run
 * so the override stays attributable. There were a temperature slider and a
 * thinking-effort picker beside it, and both were sent on every turn and read by
 * nothing - the run always used the agent's spec (#924). A control that says it
 * does something and does not is worse than one that is absent, so they are gone;
 * thinking effort in particular is a capability binding, not a model setting, and
 * overriding it per turn is a larger design than a slider (see `spec.py`).
 *
 * The model is chosen the way the Builder chooses one - provider first, then the
 * model - and what runs is still one of the vault's model profiles: a choice that
 * matches an existing profile reuses it, a new one is created on the provider's
 * vault key. An organization that rotates a key changes what this picker can
 * offer, because it is the same set of rows.
 *
 * **The second thing is the approval mode**, and it is on the right side of that
 * line by a small margin. It does not change what the agent may reach; it changes
 * who is asked before it does, and the person being asked is the one setting it -
 * a property of the session, like the model being spent (#925).
 *
 * Two of the three options are not always offered, and each absence is a
 * different fact:
 *
 * - *approve everything* needs `approvals:decide`, because a standing consent is
 *   the decision the approval queue exists to record - `member` and `builder` run
 *   agents without it - and it needs the organization to allow waiving at all.
 *   Rendering it and letting the socket refuse would be a control that looks
 *   available and is not;
 * - *ask about everything* is always there. It only ever tightens, so it needs no
 *   permission and no ceiling.
 */
export function ChatControls({
  onModelProfileChange,
  onApprovalModeChange,
  agentModel = null,
}: ChatControlsProps) {
  const t = useTranslations("chat.controls");
  const currentConversationId = useConversationStore((state) => state.currentConversationId);
  const { profiles } = useModelProviders();
  const { can } = usePermissions();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { data: orgs } = useOrganizationList();
  const activeOrg = orgs?.find((org) => org.id === activeOrgId) ?? null;
  // Both halves, and the organization's is the one that can be false for an
  // owner: the permission says who may waive, the setting says whether anybody
  // here may.
  const mayWaive = can(Perm.approvalsDecide) && activeOrg?.chat_may_waive_approvals === true;

  const [profileId, setProfileId] = useState<string | null>(null);
  const [approvalMode, setApprovalMode] = useState<ApprovalMode>("follow_agent");

  const selectedProfile = profiles.find((profile) => profile.id === profileId) ?? null;
  const triggerSummary = useMemo(
    () => selectedProfile?.label ?? t("controls"),
    [selectedProfile, t],
  );
  const hasOverride = profileId !== null || approvalMode !== "follow_agent";

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={t("label")}
          // The /settings slash command opens this popover by clicking the
          // trigger through this attribute - see ChatContainer's slashContext.
          data-chat-settings-trigger
          className={cn(
            "border-foreground/10 bg-card hover:border-foreground/25 hover:bg-foreground/[0.04] inline-flex items-center gap-1.5 rounded-full border py-1 pr-2 pl-2.5 font-mono text-[11px] tracking-wider uppercase transition-colors",
            hasOverride ? "text-foreground" : "text-foreground/65",
          )}
        >
          <Sliders className="h-3 w-3" />
          <span className="max-w-[200px] truncate">{triggerSummary}</span>
          {hasOverride && (
            <span aria-hidden className="bg-foreground inline-block h-1 w-1 rounded-full" />
          )}
          <ChevronDown className="text-foreground/45 h-3 w-3" />
        </button>
      </PopoverTrigger>

      <PopoverContent
        align="end"
        sideOffset={8}
        className="border-border bg-popover relative w-[380px] overflow-hidden rounded-2xl border p-0 shadow-md"
      >
        <div className="max-h-[420px] scrollbar-thin overflow-y-auto p-4">
          <p className="text-foreground/55 mb-3 text-xs leading-relaxed">
            {t("whichModelRunsHere")}
          </p>
          <ChatModelPicker
            value={profileId}
            agentModel={agentModel}
            onChange={(next) => {
              setProfileId(next);
              onModelProfileChange?.(next);
            }}
            // "No override" is not "the organization default": an agent names its
            // own model, and leaving that alone is the default here - so there is
            // no row for one.
          />
          {profileId !== null && (
            <button
              type="button"
              onClick={() => {
                setProfileId(null);
                onModelProfileChange?.(null);
              }}
              className="text-foreground/55 hover:text-foreground mt-3 text-[11px] underline-offset-2 hover:underline"
            >
              {t("backAgentAposS")}
            </button>
          )}

          <div className="border-foreground/10 mt-4 border-t pt-4" data-tour="chat-approval-mode">
            <p className="text-foreground/55 mb-3 text-xs leading-relaxed">
              {t("howMuchToBeAsked")}
            </p>
            <div role="radiogroup" aria-label={t("approvalMode")} className="space-y-1">
              {APPROVAL_MODES.map((mode) => {
                // Rendered but unavailable, rather than hidden: "you cannot waive
                // approvals here" is a fact worth reading, where a menu that is
                // one item shorter for some people is a menu nobody can reason
                // about. The reason is said beneath it.
                const offered = mode !== "approve_all" || mayWaive;
                return (
                  <button
                    key={mode}
                    type="button"
                    role="radio"
                    aria-checked={approvalMode === mode}
                    disabled={!offered}
                    onClick={() => {
                      setApprovalMode(mode);
                      onApprovalModeChange?.(mode);
                    }}
                    className={cn(
                      "w-full rounded-xl px-3 py-2 text-left transition-colors",
                      approvalMode === mode
                        ? "bg-foreground/[0.06] text-foreground"
                        : "text-foreground/70 hover:bg-foreground/[0.04]",
                      !offered && "cursor-not-allowed opacity-45",
                    )}
                  >
                    <span className="block text-xs font-medium">{t(`mode.${mode}`)}</span>
                    <span className="text-foreground/50 block text-[11px] leading-relaxed">
                      {t(`modeHint.${mode}`)}
                    </span>
                  </button>
                );
              })}
            </div>
            {!mayWaive && (
              <p className="text-foreground/45 mt-2 text-[11px] leading-relaxed">
                {t("cannotWaive")}
              </p>
            )}
          </div>
          <YourConnections />
        </div>

        <div className="border-foreground/10 text-foreground/45 flex items-center justify-between border-t px-4 py-2 font-mono text-[10px] tracking-wider uppercase">
          <span className="inline-flex items-center gap-1.5">
            <span
              aria-hidden
              className="bg-foreground inline-block h-1 w-1 animate-pulse rounded-full"
            />
            {currentConversationId ? t("savedForChat") : t("savesOnSend")}
          </span>
          <span>{t("escToClose")}</span>
        </div>
      </PopoverContent>
    </Popover>
  );
}
