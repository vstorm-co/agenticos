"use client";

import { Button } from "@/components/ui";
import { usePermissions } from "@/hooks";
import { approvalSummary, toolDisplayName } from "@/lib/agent-step-captions";
import { cn } from "@/lib/utils";
import type { ActionRequest, ReviewConfig, Decision } from "@/types";
import { Perm } from "@/types/permissions";
import { Check, ShieldAlert, X } from "lucide-react";
import { useTranslations } from "next-intl";

interface ToolApprovalDialogProps {
  actionRequests: ActionRequest[];
  reviewConfigs: ReviewConfig[];
  onDecisions: (decisions: Decision[]) => void;
  disabled?: boolean;
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
 * What replaces it is the shape the rest of the chat uses: a card, the step's own
 * name from `lib/tool-catalog.ts`, its arguments as read-only code, and
 * two plain answers. Approve and Reject rather than "Submit 1 call" - the question
 * is not how many calls there are.
 */
export function ToolApprovalDialog({
  actionRequests,
  onDecisions,
  disabled = false,
}: ToolApprovalDialogProps) {
  const t = useTranslations("chat");
  const tTools = useTranslations("chat.tools");
  const { can } = usePermissions();
  const mayDecide = can(Perm.approvalsDecide);

  const decideAll = (type: "approve" | "reject") =>
    onDecisions(actionRequests.map(() => ({ type })));

  return (
    // The voice call's approval card, in the chat: the warning tone and ring of
    // anything waiting on a person, the step's name, why it is asked, and its
    // arguments one row each - a JSON object read as a stray code block.
    <section
      role="group"
      aria-label={t("toolApprovalRequired")}
      className="bg-card border-warning/60 flex w-full max-w-[560px] flex-col gap-3 rounded-[14px] border p-3.5 shadow-[0_0_0_3px_color-mix(in_oklch,var(--color-warning)_16%,transparent),0_8px_30px_-12px_rgb(0_0_0/0.25)]"
    >
      <div className="flex items-center gap-2 text-[13px] font-semibold">
        <ShieldAlert className="text-warning h-4 w-4 shrink-0" aria-hidden />
        <span>{t("toolApprovalRequired")}</span>
      </div>

      {actionRequests.map((action) => {
        const { reason, ...rest } = action.args ?? {};
        const summary = approvalSummary(action.capability_tool_id, action.context, tTools);
        return (
          <div key={action.id} className="flex flex-col gap-2">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <b className="text-base font-semibold tracking-tight">
                {toolDisplayName(action.tool_name, tTools)}
              </b>
              <code className="bg-muted rounded px-1.5 font-mono text-xs">{action.tool_name}</code>
            </div>
            {/* Why the agent asks, in its own words, first: a request to share a
                view mid-way through "publish a page" reads as unrelated without it. */}
            {typeof reason === "string" && reason !== "" && (
              <p className="text-sm leading-relaxed">{reason}</p>
            )}
            {/* What will happen, in names rather than the ids below - resolved when
                the call was parked, as the person the run acts for. */}
            {summary !== null && <p className="text-sm leading-relaxed font-medium">{summary}</p>}
            {Object.keys(rest).length > 0 && <Arguments args={rest} />}
            <details>
              <summary className="text-muted-foreground w-fit cursor-pointer text-xs">
                {t("approvalExactJson")}
              </summary>
              <pre className="bg-muted mt-1.5 max-h-48 overflow-auto rounded-lg px-2.5 py-2 font-mono text-xs">
                {JSON.stringify(action.args ?? {}, null, 2)}
              </pre>
            </details>
          </div>
        );
      })}

      {mayDecide ? (
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            variant="outline"
            className="min-w-[104px]"
            onClick={() => decideAll("reject")}
            disabled={disabled}
          >
            <X aria-hidden />
            {t("reject")}
          </Button>
          <Button
            className="min-w-[104px]"
            onClick={() => decideAll("approve")}
            disabled={disabled}
          >
            <Check aria-hidden />
            {t("approve")}
          </Button>
        </div>
      ) : (
        <p className="text-muted-foreground text-xs">{t("decidingNeedsPermission")}</p>
      )}
    </section>
  );
}

/** A value as the tool will receive it: a scalar as written, anything else as JSON. */
function shown(value: unknown): string {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean"
    ? String(value)
    : JSON.stringify(value, null, 2);
}

/**
 * The arguments as something a person judges, one row each, as the voice card
 * draws them: a single command or path is read as itself, with no escaping in
 * the way, and the exact JSON stays one click away.
 */
function Arguments({ args }: { args: Record<string, unknown> }) {
  return (
    <dl className="divide-border divide-y overflow-hidden rounded-[10px] border">
      {Object.entries(args).map(([key, value]) => (
        <div
          key={key}
          className="grid grid-cols-[minmax(92px,auto)_minmax(0,1fr)] items-baseline gap-3 px-3 py-2"
        >
          <dt className="text-muted-foreground font-mono text-xs">{key}</dt>
          <dd
            className={cn(
              "max-h-48 min-w-0 overflow-auto text-sm font-medium [overflow-wrap:anywhere] whitespace-pre-wrap",
              typeof value === "number" && "font-mono",
            )}
          >
            {shown(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}
