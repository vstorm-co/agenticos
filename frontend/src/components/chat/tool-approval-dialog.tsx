"use client";

import { Button } from "@/components/ui";
import { usePermissions } from "@/hooks";
import { toolEntry } from "@/lib/tool-catalog";
import type { ActionRequest, ReviewConfig, Decision } from "@/types";
import { Perm } from "@/types/permissions";
import { ShieldAlert } from "lucide-react";
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
    <div className="border-border bg-card space-y-3 rounded-xl border p-3 shadow-sm">
      <div className="flex items-center gap-2">
        <ShieldAlert className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden />
        <span className="text-sm font-medium">{t("toolApprovalRequired")}</span>
      </div>

      <ul className="space-y-2">
        {actionRequests.map((action) => {
          const entry = toolEntry(action.tool_name);
          return (
            <li key={action.id} className="border-border space-y-1.5 rounded-lg border p-2.5">
              {/* The catalog's name where it has one - "Run Python" rather than
                  `run_python`, the same words the step above it uses. */}
              <span className="text-xs font-medium">
                {entry?.displayNameKey === undefined
                  ? action.tool_name
                  : tTools(entry.displayNameKey)}
              </span>
              {/* Read-only, and scrolling rather than wrapping: a shell command is
                  read by its structure, and a 300-character one reflowed to the left
                  margin is unreadable in exactly the moment somebody has to judge it. */}
              <pre className="bg-muted text-foreground/90 max-h-48 overflow-auto rounded-md p-2 font-mono text-[11px] leading-relaxed whitespace-pre">
                {argumentLines(action)}
              </pre>
            </li>
          );
        })}
      </ul>

      {mayDecide ? (
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={() => decideAll("reject")} disabled={disabled}>
            {t("reject")}
          </Button>
          <Button size="sm" onClick={() => decideAll("approve")} disabled={disabled}>
            {t("approve")}
          </Button>
        </div>
      ) : (
        <p className="text-muted-foreground text-xs">{t("decidingNeedsPermission")}</p>
      )}
    </div>
  );
}

/**
 * The arguments as something a person judges, not as a JSON object.
 *
 * A gated call is nearly always one string that matters - the command, the path,
 * the address - and `{"command": "python - <<'PY'\nimport …"}` hides it behind
 * escaping: the newlines that make a script readable arrive as `\n`. So a single
 * string argument is shown as itself, and anything else is indented JSON.
 */
function argumentLines(action: ActionRequest): string {
  const values = Object.values(action.args ?? {});
  const only = values.length === 1 ? values[0] : undefined;
  if (typeof only === "string") return only;
  return JSON.stringify(action.args ?? {}, null, 2);
}
