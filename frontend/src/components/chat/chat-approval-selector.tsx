"use client";

import Link from "next/link";
import { ShieldCheck, ShieldAlert, ChevronDown, Hand, ArrowUpRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { useOrganizationList, usePermissions } from "@/hooks";
import { useSavedChatControls } from "@/hooks/use-saved-chat-controls";
import { useOrgStore } from "@/stores/org-store";
import type { ApprovalMode } from "@/stores/chat-controls-store";
import { cn } from "@/lib/utils";
import { Perm } from "@/types/permissions";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuLabel,
  DropdownMenuRadioItem,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";

const MODES: readonly ApprovalMode[] = ["follow_agent", "ask_all", "approve_all"];
const MODE_ICONS = { follow_agent: ShieldCheck, ask_all: Hand, approve_all: ShieldAlert };
function isMode(value: string): value is ApprovalMode {
  return MODES.some((mode) => mode === value);
}

/** The active standing-consent mode remains visible before a message is sent. */
export function ChatApprovalSelector({
  onChange,
  disabled = false,
  iconOnly = false,
}: {
  onChange?: (mode: ApprovalMode) => void;
  disabled?: boolean;
  iconOnly?: boolean;
}) {
  const t = useTranslations("chat.controls");
  const { can } = usePermissions();
  const orgId = useOrgStore((state) => state.activeOrgId);
  const { data: orgs } = useOrganizationList();
  const org = orgs?.find((org) => org.id === orgId);
  const mayDecide = can(Perm.approvalsDecide);
  const mayOpenSettings = can(Perm.orgSettings) || can(Perm.budgetsManage) || mayDecide;
  const mayWaive = mayDecide && org?.chat_may_waive_approvals === true;
  const { approvalMode, update } = useSavedChatControls(mayWaive);
  const Icon = MODE_ICONS[approvalMode];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          data-chat-permission-mode
          data-icon-only={iconOnly}
          data-approval-mode={approvalMode}
          title={t("activeApprovalMode", { mode: t(`mode.${approvalMode}`) })}
          disabled={disabled}
          aria-label={t("activeApprovalMode", { mode: t(`mode.${approvalMode}`) })}
          className={cn(
            "group/approval text-muted-foreground hover:bg-muted hover:text-foreground data-[state=open]:bg-accent data-[state=open]:text-foreground focus-visible:ring-ring touch:min-h-11 inline-flex h-8 max-w-full min-w-0 items-center gap-1.5 rounded-lg px-2 text-xs transition-colors outline-none focus-visible:ring-2 disabled:opacity-50",
            iconOnly && "size-9 shrink-0 justify-center px-0",
            iconOnly && approvalMode === "approve_all" && "text-warning-ink",
            iconOnly && approvalMode === "ask_all" && "text-foreground",
          )}
        >
          <Icon className="size-3.5 shrink-0" aria-hidden />
          {!iconOnly && (
            <>
              <span className="truncate">{t(`compactMode.${approvalMode}`)}</span>
              <ChevronDown
                className="size-3 shrink-0 transition-transform group-data-[state=open]/approval:rotate-180 motion-reduce:transition-none"
                aria-hidden
              />
            </>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        side="top"
        align="end"
        className="w-[23rem] max-w-[calc(100vw-1.5rem)] p-1.5"
      >
        <DropdownMenuLabel className="px-2.5 py-1.5 text-xs font-normal">
          {t("approvalMode")}
        </DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={approvalMode}
          aria-label={t("approvalMode")}
          onValueChange={(value) => {
            if (!isMode(value) || (value === "approve_all" && !mayWaive)) return;
            update({ approvalMode: value });
            onChange?.(value);
          }}
        >
          {MODES.map((mode) => {
            const ModeIcon = MODE_ICONS[mode];
            return (
              <DropdownMenuRadioItem
                key={mode}
                value={mode}
                indicator="check"
                disabled={mode === "approve_all" && !mayWaive}
                className={cn(
                  "data-[state=checked]:bg-control items-start gap-2.5 px-2.5 py-2 pr-8",
                  mode === "approve_all" && mayWaive && "text-warning-ink focus:text-warning-ink",
                )}
              >
                <span className="mt-0.5 shrink-0" aria-hidden>
                  <ModeIcon className="size-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-medium">{t(`mode.${mode}`)}</span>
                  <span
                    className={cn(
                      "mt-0.5 block text-xs leading-5 font-normal",
                      mode === "approve_all" && mayWaive
                        ? "text-warning-ink"
                        : "text-muted-foreground",
                    )}
                  >
                    {t(`modeHint.${mode}`)}
                  </span>
                </span>
              </DropdownMenuRadioItem>
            );
          })}
        </DropdownMenuRadioGroup>
        {!mayWaive && (
          <div className="border-border/60 mx-2.5 mt-1 border-t pt-2 pb-1">
            <p className="text-muted-foreground text-xs leading-5">
              {t(!org ? "waiverUnknown" : !mayDecide ? "waiverPermission" : "waiverOrg")}
            </p>
            {org && mayOpenSettings && org.chat_may_waive_approvals === false && (
              <DropdownMenuItem
                asChild
                className="text-brand mt-1 gap-2 px-0 text-xs underline underline-offset-4"
              >
                <Link href={`/orgs/${org.id}/members?tab=governance`}>
                  {t("waiverSettings")}
                  <ArrowUpRight className="size-4" aria-hidden />
                </Link>
              </DropdownMenuItem>
            )}
          </div>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
