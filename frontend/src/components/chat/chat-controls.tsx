"use client";

import Link from "next/link";
import type { ApprovalMode } from "@/stores/chat-controls-store";
import { useSavedChatControls } from "@/hooks/use-saved-chat-controls";
import { useId, useMemo, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { Check, HelpCircle, SlidersHorizontal, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PersonalCodingAccount } from "@/components/settings/coding-accounts";
import { RememberedApprovals } from "./remembered-approvals";
import { ChatModelPicker } from "./chat-model-picker";
import { WorkOn, ConversationNotifications } from "./work-on";
import { YourConnections } from "./your-connections";
import { ContextHelp } from "@/components/ui/context-help";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useModelProviders, useOrganizationList, usePermissions } from "@/hooks";
import { useAgentSelectionStore, useOrgStore } from "@/stores";
import { useAgents } from "@/hooks/use-agents";
import { useOnboardingStore } from "@/stores/onboarding-store";
import type { PublishedModel } from "@/types/agents";
import { Perm } from "@/types/permissions";
import { stripLocale } from "@/lib/active-route";
import { pageHasSteps } from "@/lib/onboarding/tour";
import { cn } from "@/lib/utils";
import { useShell } from "@/hooks/use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";

/** Offered in this order: what the agent says, then looser, then tighter. */
const APPROVAL_MODES: readonly ApprovalMode[] = ["follow_agent", "approve_all", "ask_all"];

/** The three answers to "how much do I want to be asked", server-side names. */
export type { ApprovalMode } from "@/stores/chat-controls-store";

interface ChatControlsProps {
  agentCapabilities?: readonly string[] | null;
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
  agentCapabilities = null,
}: ChatControlsProps) {
  const t = useTranslations("chat.controls");
  const panel = useRef<HTMLDivElement>(null);
  const tCommon = useTranslations("common");
  const waiverHintId = useId();
  const tOnboarding = useTranslations("onboarding");
  const pathname = usePathname();
  const openPage = useOnboardingStore((state) => state.openPage);
  const [open, setOpen] = useState(false);
  const desktop = isDesktopShell(useShell());
  const [tab, setTab] = useState("model");
  const selectedAgentId = useAgentSelectionStore((state) => state.selectedAgentId);
  const { agents } = useAgents();
  const selectedAgent = agents.find((agent) => agent.id === selectedAgentId);
  const personalHarness = selectedAgent?.personal_coding_harness ?? null;
  // What the agent reaches, kept apart from the model it runs on: the folder,
  // browser, screen and coding agent on the desktop, and the coding account an
  // agent that codes on the person's own account needs anywhere.
  // A delegate can need either personal harness, even when the selected agent
  // has no coding binding itself. Keep both connection doors in that case.
  const delegates =
    (agentCapabilities ?? selectedAgent?.published_capabilities)?.includes("subagents") === true;
  const harnesses = delegates
    ? (["claude_code", "codex"] as const)
    : personalHarness
      ? [personalHarness]
      : [];
  const tools = desktop || harnesses.length > 0;
  const selectedTab = !tools && tab === "tools" ? "model" : tab;
  const { profiles } = useModelProviders();
  const { can } = usePermissions();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { data: orgs } = useOrganizationList();
  const activeOrg = orgs?.find((org) => org.id === activeOrgId) ?? null;
  // Both halves, and the organization's is the one that can be false for an
  // owner: the permission says who may waive, the setting says whether anybody
  // here may.
  const mayWaive = can(Perm.approvalsDecide) && activeOrg?.chat_may_waive_approvals === true;

  const {
    modelProfileId: profileId,
    approvalMode,
    update: savePreferences,
  } = useSavedChatControls(mayWaive);
  const setProfileId = (modelProfileId: string | null) => savePreferences({ modelProfileId });
  const setApprovalMode = (approvalMode: ApprovalMode) => savePreferences({ approvalMode });

  const selectedProfile = profiles.find((profile) => profile.id === profileId) ?? null;
  // The model that answers, whichever it is: an override when there is one,
  // the agent's own otherwise. The trigger is an icon, so this is its tooltip.
  const triggerTitle = useMemo(() => {
    const model = selectedProfile?.label ?? agentModel?.label ?? null;
    return model === null ? t("label") : t("modelTitle", { model });
  }, [selectedProfile, agentModel, t]);
  const hasOverride = profileId !== null || approvalMode !== "follow_agent";

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={t("label")}
          title={triggerTitle}
          // The /settings slash command opens these settings by clicking the
          // trigger through this attribute - see ChatContainer's slashContext.
          data-chat-settings-trigger
          data-tour="chat-settings"
          // One icon beside the microphone: the model is a choice made once
          // and remembered across chats; its name took the width of the row it sat in.
          // The dot is what an override leaves visible once the settings close.
          className={cn(
            "hover:bg-foreground/[0.06] hover:text-foreground relative inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors",
            hasOverride ? "text-foreground" : "text-muted-foreground",
          )}
        >
          <SlidersHorizontal className="h-4 w-4" aria-hidden />
          {hasOverride && (
            <span
              data-testid="override-dot"
              aria-hidden
              className="bg-foreground absolute top-1.5 right-1.5 h-1.5 w-1.5 rounded-full"
            />
          )}
        </button>
      </PopoverTrigger>

      <PopoverContent
        ref={panel}
        style={{ backgroundColor: "var(--color-card)" }}
        aria-label={t("label")}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          panel.current?.focus();
        }}
        side="top"
        align="end"
        sideOffset={12}
        tabIndex={-1}
        className="bg-card flex max-h-[min(680px,var(--radix-popover-content-available-height))] w-[480px] flex-col overflow-hidden rounded-xl p-0 shadow-2xl"
        // The page tour walks through these settings sections. Its caption takes
        // focus and its overlay takes the pointer - both outside - and closing on
        // either left the next stop pinned to a section that had gone.
        onInteractOutside={(event) => {
          if (
            document.querySelector(".driver-popover") ||
            (event.target instanceof Element &&
              event.target.closest("[data-coding-account-connect]"))
          )
            event.preventDefault();
        }}
      >
        <div className="flex shrink-0 items-center justify-between px-5 pt-4 pb-3">
          <h2 className="text-base font-semibold tracking-tight">{t("label")}</h2>
          <button
            type="button"
            aria-label={tCommon("close")}
            onClick={() => setOpen(false)}
            className="text-foreground/75 hover:bg-accent hover:text-foreground flex size-8 items-center justify-center rounded-md"
          >
            <X className="size-4" aria-hidden />
          </button>
        </div>
        <Tabs value={selectedTab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
          <TabsList className="mx-5 shrink-0 gap-5">
            <TabsTrigger value="model" data-tour="chat-settings-model" className="px-0">
              {t("modelSection")}
            </TabsTrigger>
            {tools && (
              <TabsTrigger value="tools" data-tour="chat-settings-tools" className="px-0">
                {t("toolsTab")}
              </TabsTrigger>
            )}
            <TabsTrigger value="preferences" data-tour="chat-settings-preferences" className="px-0">
              {t("preferencesTab")}
            </TabsTrigger>
          </TabsList>
          <div className="min-h-0 flex-1 scrollbar-thin overflow-y-auto overscroll-contain px-5 py-5">
            <TabsContent value="model" forceMount hidden={selectedTab !== "model"} className="mt-0">
              <p className="text-muted-foreground mb-4 text-[13px] leading-5">
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
                  className="text-muted-foreground hover:text-foreground mt-3 text-xs underline-offset-2 hover:underline"
                >
                  {t("backAgentAposS")}
                </button>
              )}
            </TabsContent>
            {tools && (
              <TabsContent
                value="tools"
                forceMount
                hidden={selectedTab !== "tools"}
                className="mt-0"
              >
                {harnesses.map((harness) => (
                  <PersonalCodingAccount key={harness} harness={harness} />
                ))}
                {desktop && <WorkOn agentCapabilities={agentCapabilities} />}
              </TabsContent>
            )}
            <TabsContent
              value="preferences"
              forceMount
              hidden={selectedTab !== "preferences"}
              className="mt-0"
            >
              <div className="space-y-4" data-tour="chat-approval-mode">
                <div className="mb-2 flex items-center gap-1">
                  <h3 className="text-foreground/85 text-[13px] font-medium">
                    {t("permissionsSection")}
                  </h3>
                  <ContextHelp>
                    <p>{t("howMuchToBeAsked")}</p>
                    <ul className="mt-3 space-y-3">
                      {APPROVAL_MODES.map((mode) => (
                        <li key={mode}>
                          <strong className="font-medium">{t(`mode.${mode}`)}</strong>
                          <p className="text-muted-foreground mt-1">{t(`modeHint.${mode}`)}</p>
                        </li>
                      ))}
                    </ul>
                  </ContextHelp>
                </div>
                <div
                  role="radiogroup"
                  aria-label={t("approvalMode")}
                  aria-describedby={!mayWaive ? waiverHintId : undefined}
                  className="space-y-2"
                >
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
                        aria-label={t(`mode.${mode}`)}
                        aria-describedby={`${waiverHintId}-${mode}`}
                        disabled={!offered}
                        onClick={() => {
                          setApprovalMode(mode);
                          onApprovalModeChange?.(mode);
                        }}
                        className={cn(
                          "focus-visible:ring-ring flex w-full items-start justify-between gap-4 rounded-xl border px-3.5 py-3 text-left transition-colors outline-none focus-visible:ring-2 focus-visible:ring-inset",
                          approvalMode === mode
                            ? "border-foreground/20 bg-foreground/[0.04] text-foreground"
                            : "border-border/60 text-foreground/80 hover:bg-foreground/[0.025]",
                          !offered && "text-muted-foreground cursor-not-allowed border-dashed",
                        )}
                      >
                        <span
                          aria-hidden
                          className={cn(
                            "order-last mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border",
                            approvalMode === mode
                              ? "border-foreground bg-foreground text-background"
                              : "border-input",
                          )}
                        >
                          {approvalMode === mode && <Check className="size-3" />}
                        </span>
                        <span className="min-w-0">
                          <span className="block text-[13px] font-medium">{t(`mode.${mode}`)}</span>
                          <span
                            id={`${waiverHintId}-${mode}`}
                            className="text-muted-foreground mt-1 block text-xs leading-relaxed"
                          >
                            {t(`modeHint.${mode}`)}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
                {can(Perm.approvalsDecide) && <RememberedApprovals />}
                {!mayWaive && (
                  <div className="text-muted-foreground mt-2 space-y-2 text-xs leading-relaxed">
                    <p id={waiverHintId}>
                      {t(
                        !can(Perm.approvalsDecide)
                          ? "waiverPermission"
                          : typeof activeOrg?.chat_may_waive_approvals !== "boolean"
                            ? "waiverUnknown"
                            : "waiverOrg",
                      )}
                    </p>
                    {can(Perm.approvalsDecide) && activeOrg?.chat_may_waive_approvals === false && (
                      <Link
                        href={`/orgs/${activeOrg.id}/members?tab=governance`}
                        onClick={() => setOpen(false)}
                        className="text-foreground underline underline-offset-4"
                      >
                        {t("waiverSettings")}
                      </Link>
                    )}
                  </div>
                )}
              </div>
              <ConversationNotifications />
              <YourConnections />
              {/* Chat has no PageHeader, so its tips are replayed from here - beside
              the other controls, rather than under the composer (#2301). Closed
              first: the tour walks through these settings. */}
              {pageHasSteps(stripLocale(pathname ?? "/")) && (
                <div className="border-foreground/10 mt-4 border-t pt-3">
                  <button
                    type="button"
                    onClick={() => {
                      setOpen(false);
                      openPage();
                    }}
                    className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 text-xs transition-colors"
                  >
                    <HelpCircle className="h-3.5 w-3.5" aria-hidden />
                    {tOnboarding("pageHelp")}
                  </button>
                </div>
              )}
            </TabsContent>
          </div>
        </Tabs>

        <div className="text-muted-foreground flex shrink-0 items-center justify-between px-5 pt-1 pb-4 text-[11px]">
          <span className="inline-flex items-center gap-1.5">{t("savedAutomatically")}</span>
          <span>{t("escToClose")}</span>
        </div>
      </PopoverContent>
    </Popover>
  );
}
