"use client";

import { ChevronDown, MessageSquare, ShieldCheck } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import {
  AGENT_DRAFT_TOOL,
  AgentDraftProposal,
  draftArgs,
} from "@/components/chat/agent-draft-proposal";
import {
  AccountBadge,
  ApprovalDetails,
  ToolMark,
  useActionPhrase,
} from "@/components/runs/approval-request";
import { Button } from "@/components/ui";
import { usePermissions } from "@/hooks";
import { approvalSummary } from "@/lib/agent-step-captions";
import { callSummary } from "@/lib/approval-view";
import { cn } from "@/lib/utils";
import type { ActionRequest, ReviewConfig, Decision } from "@/types";
import { Perm } from "@/types/permissions";
import { useTranslations } from "next-intl";

interface ToolApprovalDialogProps {
  actionRequests: ActionRequest[];
  reviewConfigs: ReviewConfig[];
  onDecisions: (decisions: Decision[]) => void;
  disabled?: boolean;
  mayRemember?: boolean;
}

/**
 * The decision a parked run is waiting on, taken where the conversation is.
 *
 * **It checks `approvals:decide` itself**, for the same reason the model picker
 * beside it checks `connections:manage`: the permission belongs to the write, and
 * `onDecisions` sends `POST /approvals/{id}` followed by `POST /runs/{id}/resume`,
 * both gated on `Perm.APPROVALS_DECIDE`. Running an agent is not - `member` and
 * `builder` hold `agents:run` and not the decision - so the everyday chat user was
 * offered a Submit and refused by the API on the first call. What stays for them is
 * the call itself and the sentence saying who can decide: a panel that goes quiet
 * leaves a stopped conversation unexplained.
 *
 * **The arguments are read, not edited.** They used to sit in a `<textarea>` whose
 * contents were diffed into an `edit` decision - and the backend never offered it:
 * every `review_config` it sends carries `allow_edit: false`, because the arguments
 * were already recorded on the row the approver is deciding about and letting the
 * chat rewrite them would mean approving something other than what was asked. So
 * the edit path was dead, and the raw JSON box it needed was the loudest thing in
 * the transcript.
 *
 * What replaces it is a question a person can answer at a glance: the service's
 * logo or the tool's mark, "Allow Search in Notion?", the one argument that says
 * what it is about, and two plain answers - with every other argument folded
 * behind Details, because a page of `"page_url": ""` leads with nothing. Approve
 * and Reject rather than "Submit 1 call" - the question is not how many calls
 * there are.
 */
export function ToolApprovalDialog({
  actionRequests,
  onDecisions,
  disabled = false,
  mayRemember = false,
}: ToolApprovalDialogProps) {
  const t = useTranslations("chat");
  const tTools = useTranslations("chat.tools");
  const { can } = usePermissions();
  const mayDecide = can(Perm.approvalsDecide);
  const phrase = useActionPhrase();
  const batch = actionRequests.length > 1;

  const sameTool =
    actionRequests.length > 0 &&
    actionRequests.every(
      (action) =>
        action.can_remember === true &&
        !action.subagent_name &&
        action.tool_name === actionRequests[0]!.tool_name &&
        action.account === actionRequests[0]!.account,
    );
  const mayApprove = actionRequests.every(
    (action) => !(action.always_asks && action.content_hidden),
  );
  const decideAll = (type: "approve" | "reject", scope?: Decision["remember_scope"]) =>
    onDecisions(
      actionRequests.map((_, index) => ({
        type,
        ...(index === 0 && scope ? { remember_scope: scope } : {}),
      })),
    );

  return (
    // A batch uses the full card width, with decisions below the scrolling
    // list: its scrollbar must not look like a divider beside the buttons.
    // For one call, the answers sit beside the question: under it, a
    // folded Details left a band of empty card between what was asked and the
    // buttons that answer it.
    // Laid out by the card's own width, not the window's: in the Architect's
    // widget the window is wide and the card is not, and buttons beside the
    // question squeezed what was asked into a column a third of the card.
    <div className="@container" role="group" aria-label={t("toolApprovalRequired")}>
      <div
        className={cn(
          "border-border bg-card flex flex-col gap-3 rounded-xl border p-3 shadow-sm",
          !batch && "@xl:flex-row @xl:items-start",
        )}
      >
        <ul
          className={cn(
            "min-w-0 flex-1 space-y-4",
            batch &&
              "-mr-1 max-h-[min(36dvh,20rem)] scrollbar-thin [scrollbar-gutter:stable] overflow-y-auto overscroll-contain pr-2",
          )}
        >
          {actionRequests.map((action) => {
            // The Architect's agent draft is decided as a draft, not as a JSON call (#1799).
            const draft = action.tool_name === AGENT_DRAFT_TOOL ? draftArgs(action.args) : null;
            const { reason, ...args } = action.args ?? {};
            // What the call will do in names rather than the ids below, resolved when
            // it was parked as the person the run acts for; else the one telling argument.
            const summary =
              draft === null
                ? (approvalSummary(action.capability_tool_id, action.context, tTools) ??
                  callSummary(args))
                : null;
            return (
              <li key={action.id} className="flex gap-3">
                <ToolMark toolName={action.tool_name} />
                <div className="min-w-0 flex-1 space-y-1.5">
                  <p className="text-muted-foreground text-xs font-medium">
                    {t("toolApprovalRequired")}
                  </p>
                  {/* The question, in the words the step above it uses - "Allow
                    Search in Notion?" - rather than `notion_notion-search`. */}
                  <p className="text-foreground text-sm font-medium">
                    {draft !== null
                      ? t("draftProposalTitle")
                      : t("approvalAsk", { action: phrase(action.tool_name) })}
                  </p>
                  <AccountBadge account={action.account} />
                  {/* Why the agent asks, in its own words, first: a request to share a
                    view mid-way through "publish a page" reads as unrelated without it. */}
                  {typeof reason === "string" && reason !== "" && (
                    <p className="text-sm leading-relaxed">{reason}</p>
                  )}
                  {/* The one argument that says what the call is about. A command
                    is read by its characters, so it keeps a code face. */}
                  {summary !== null && (
                    <p
                      className={cn(
                        "text-foreground/80 line-clamp-2 text-sm break-words",
                        ("command" in args || "cmd" in args) && "font-mono text-xs",
                      )}
                      title={summary}
                    >
                      {summary}
                    </p>
                  )}
                  {draft !== null ? (
                    <AgentDraftProposal draft={draft} />
                  ) : (
                    <ApprovalDetails toolName={action.tool_name} args={args} />
                  )}
                </div>
              </li>
            );
          })}
        </ul>

        {mayDecide ? (
          <div className={cn("flex shrink-0 justify-end gap-2", !batch && "@xl:pt-4")}>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => decideAll("reject")}
              disabled={disabled}
            >
              {t("reject")}
            </Button>
            <div className="flex items-center gap-1">
              {mayApprove ? (
                <Button size="sm" onClick={() => decideAll("approve")} disabled={disabled}>
                  {t("approve")}
                </Button>
              ) : (
                <p className="text-muted-foreground max-w-56 text-xs">{t("approvalNeedsTheRun")}</p>
              )}
              {mayApprove && mayRemember && sameTool && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      size="sm"
                      variant="secondary"
                      className="px-2"
                      disabled={disabled}
                      aria-label={t("approvalRememberOptions")}
                    >
                      <ChevronDown className="size-3.5" aria-hidden />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="max-w-[calc(100vw-2rem)]">
                    <DropdownMenuItem onSelect={() => decideAll("approve", "conversation")}>
                      <MessageSquare className="size-4" aria-hidden />
                      {t("approvalRememberChat")}
                    </DropdownMenuItem>
                    <DropdownMenuItem onSelect={() => decideAll("approve", "agent")}>
                      <ShieldCheck className="size-4" aria-hidden />
                      {t("approvalRememberAgent")}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </div>
          </div>
        ) : (
          <p className="text-muted-foreground max-w-56 shrink-0 text-xs @xl:pt-4">
            {t("decidingNeedsPermission")}
          </p>
        )}
      </div>
    </div>
  );
}
