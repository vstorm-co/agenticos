"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { Users } from "lucide-react";

import { Badge } from "@/components/ui";
import { usePermissions } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";
import type { ToolApproval } from "@/types/runs";

/**
 * Who is asking for this approval, when it is not the agent whose run it is.
 *
 * A delegate's gated tool reaches the parent's approval channel, which is what makes
 * a gated tool inside a delegation usable at all - and it is also why the row would
 * otherwise say `send_email` without saying whether the agent somebody is talking to
 * or a specialist called "researcher" is the one sending it. In a delegation the
 * thing being approved is often more consequential than the agent the approver has
 * in mind, so the actor belongs beside the tool name rather than a click away.
 *
 * Three cases, and the two null ones do not read the same:
 *
 * - **No name.** The run's own agent asked. Nothing is rendered: `agent_id` is
 *   already the run's agent, and a label saying "this agent" would be copy invented
 *   to fill a space.
 * - **A name and an agent.** A published delegate, linked - so an approver can read
 *   its instructions and capabilities before deciding.
 * - **A name and no agent.** An inline specialist: defined inside its parent's spec,
 *   with no version, nothing to link to and no row in `agents`. Said out loud, because
 *   an unlinked name otherwise reads as a published agent whose link somebody forgot.
 *
 * The link is dropped for a caller without `agents:view`, who would land on a page
 * the server refuses. The *name* stays either way - it is what the decision needs,
 * and hiding it would put them back to approving blind.
 */
export function ApprovalDelegate({ approval }: { approval: ToolApproval }) {
  // `pages.runs` rather than a namespace of its own: this reads as part of the queue
  // it sits in, and a second namespace holding three keys would put the queue's copy
  // in two places for a translator to find.
  const t = useTranslations("pages.runs");
  const { can } = usePermissions();

  if (approval.subagent_name === null) return null;

  const asked = t("askedBy", { name: approval.subagent_name });
  const agentId = approval.subagent_agent_id;

  return (
    <span className="flex flex-wrap items-center gap-1.5 text-xs">
      <Users className="text-muted-foreground size-3.5 shrink-0" aria-hidden="true" />
      {agentId !== null && can(Perm.agentsView) ? (
        <Link
          href={ROUTES.AGENT_DETAIL(agentId)}
          className="font-medium underline underline-offset-4"
        >
          {asked}
        </Link>
      ) : (
        <span className="font-medium">{asked}</span>
      )}
      {agentId === null && (
        <Badge variant="outline" title={t("specialistHasNoAgent")}>
          {t("inlineSpecialist")}
        </Badge>
      )}
    </span>
  );
}
