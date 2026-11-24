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
import { isBrowserCredentialPreparation } from "@/lib/browser-credential-approval";
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
 * `onDecisions` sends `POST /approvals/{id}` followed by `POST /runs/{id}/resume`.
 * A member or builder holds the permission at `OWN` - their own runs only - so
 * the role check alone would offer them a Submit on somebody else's run and
 * have the API refuse it on the first call. Each action therefore also carries
 * the backend's own `can_decide`, which a reloaded panel reads and the live
 * frame leaves absent; what stays for somebody who may not decide is the call
 * itself and the sentence saying who can decide: a panel that goes quiet
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
  const browser = useTranslations("browserCredentials");
  const { can } = usePermissions();
  // The role check, narrowed per action where the backend answered: a reloaded
  // panel names runs that are not this person's, and the live frame - which
  // carries no `can_decide` - keeps the role check alone, since it only ever
  // reaches whoever was watching their own run park.
  const mayDecide =
    can(Perm.approvalsDecide) && actionRequests.every((action) => action.can_decide !== false);
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
    // Keep batch decisions below the scrollable requests. A single request has
    // room for decisions beside it whenever the card itself is wide enough.
    <div className="@container" role="group" aria-label={t("toolApprovalRequired")}>
      <div
        className={cn(
          "border-border bg-card flex flex-col gap-2 rounded-xl border px-3 py-2 shadow-sm",
          !batch && "@md:flex-row @md:items-start",
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
              <li key={action.id} className="flex gap-2.5">
                <ToolMark toolName={action.tool_name} className="size-7" />
                <div className="min-w-0 flex-1 space-y-0.5">
                  {/* The question, in the words the step above it uses - "Allow
                    Search in Notion?" - rather than `notion_notion-search`. */}
                  <p className="text-foreground pt-1 text-sm leading-5 font-medium">
                    {draft !== null
                      ? t("draftProposalTitle")
                      : t("approvalAsk", { action: phrase(action.tool_name) })}
                  </p>
                  <AccountBadge account={action.account} />
                  {isBrowserCredentialPreparation(
                    action.capability_tool_id ?? action.tool_name,
                  ) && (
                    <p className="text-muted-foreground text-sm">
                      {browser("requestPreparationOnly")}
                    </p>
                  )}
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
                        "text-muted-foreground line-clamp-2 text-xs break-words",
                        ("command" in args || "cmd" in args) && "font-mono",
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
          <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
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
          <p className="text-muted-foreground max-w-56 shrink-0 text-xs @md:pt-1">
            {t("decidingNeedsPermission")}
          </p>
        )}
      </div>
    </div>
  );
}
