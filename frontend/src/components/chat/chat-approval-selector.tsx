"use client";

import { ShieldCheck, ShieldAlert, ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";
import { useOrganizationList, usePermissions } from "@/hooks";
import { useSavedChatControls } from "@/hooks/use-saved-chat-controls";
import { useOrgStore } from "@/stores/org-store";
import type { ApprovalMode } from "@/stores/chat-controls-store";
import { Perm } from "@/types/permissions";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
} from "@/components/ui/dropdown-menu";

const MODES: readonly ApprovalMode[] = ["follow_agent", "approve_all", "ask_all"];
function isMode(value: string): value is ApprovalMode {
  return MODES.some((mode) => mode === value);
}

/** The active standing-consent mode remains visible before a message is sent. */
export function ChatApprovalSelector({
  onChange,
  disabled = false,
}: {
  onChange?: (mode: ApprovalMode) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("chat.controls");
  const { can } = usePermissions();
  const orgId = useOrgStore((state) => state.activeOrgId);
  const { data: orgs } = useOrganizationList();
  const org = orgs?.find((org) => org.id === orgId);
  const mayDecide = can(Perm.approvalsDecide);
  const mayWaive = mayDecide && org?.chat_may_waive_approvals === true;
  const { approvalMode, update } = useSavedChatControls(mayWaive);
  const Icon = approvalMode === "approve_all" ? ShieldAlert : ShieldCheck;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          data-chat-permission-mode
          title={t("activeApprovalMode", { mode: t(`mode.${approvalMode}`) })}
          disabled={disabled}
          aria-label={t("activeApprovalMode", { mode: t(`mode.${approvalMode}`) })}
          className="text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-ring touch:min-h-11 inline-flex h-8 max-w-full min-w-0 items-center gap-1.5 rounded-lg px-2 text-xs focus-visible:ring-2 disabled:opacity-50"
        >
          <Icon className="size-3.5 shrink-0" aria-hidden />
          <span className="truncate">{t(`compactMode.${approvalMode}`)}</span>
          <ChevronDown className="size-3 shrink-0" aria-hidden />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="end" className="w-80 max-w-[calc(100vw-2rem)]">
        <DropdownMenuRadioGroup
          value={approvalMode}
          aria-label={t("approvalMode")}
          onValueChange={(value) => {
            if (!isMode(value) || (value === "approve_all" && !mayWaive)) return;
            update({ approvalMode: value });
            onChange?.(value);
          }}
        >
          {MODES.map((mode) => (
            <DropdownMenuRadioItem
              key={mode}
              value={mode}
              disabled={mode === "approve_all" && !mayWaive}
              className="items-start py-2.5"
            >
              <span>
                <span className="block text-sm font-medium">{t(`mode.${mode}`)}</span>
                <span className="text-muted-foreground mt-1 block text-xs leading-relaxed">
                  {t(`modeHint.${mode}`)}
                </span>
              </span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        {!mayWaive && (
          <p className="text-muted-foreground px-3 py-2 text-xs">
            {t(!org ? "waiverUnknown" : !mayDecide ? "waiverPermission" : "waiverOrg")}
          </p>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
