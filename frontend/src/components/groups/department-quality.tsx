"use client";

import Link from "next/link";
import { MessageSquareWarning, ThumbsUp } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { ErrorState, LoadingState } from "@/components/states";
import { Figure, ListCard, ListCardEmpty } from "@/components/ui";
import { useAgents, useGroupQuality } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import type { Agent } from "@/types/agents";
import type { Group, GroupDownRatedAnswer } from "@/types/groups";

/**
 * How well agents answer a department's people over the last 30 days (#2101):
 * the helpful share, the agents its people ran most and the answers they rated
 * not helpful, each with its run.
 *
 * Mounted for a reader holding `runs:view` or leading this department - the two
 * the endpoint answers.
 */
export function DepartmentQuality({ orgId, group }: { orgId: string; group: Group }) {
  const t = useTranslations("groups.quality");
  const tErrors = useTranslations("errors");
  const { quality, isLoading, error } = useGroupQuality(orgId, group.id);
  const { agents } = useAgents();
  const byId = new Map(agents.map((agent) => [agent.id, agent]));
  const total = (quality?.likes ?? 0) + (quality?.dislikes ?? 0);

  return (
    <ListCard
      title={t("title")}
      counted={isLoading || error ? null : t("ratingCount", { count: total })}
    >
      {error ? (
        <ErrorState description={getErrorMessage(error, tErrors)} />
      ) : isLoading || !quality ? (
        <LoadingState variant="skeleton-panel" rows={2} />
      ) : total === 0 && quality.top_agents.length === 0 ? (
        <ListCardEmpty
          icon={ThumbsUp}
          title={t("emptyTitle")}
          description={t("emptyWhy", { name: group.name })}
        />
      ) : (
        <div className="space-y-5">
          <Figure
            value={total === 0 ? "-" : `${Math.round((quality.likes / total) * 100)}%`}
            caption={total === 0 ? t("noRatings") : t("helpful", { likes: quality.likes, total })}
          />
          {quality.top_agents.length > 0 && (
            <section className="space-y-2">
              <h3 className="text-muted-foreground text-xs font-medium">{t("mostUsed")}</h3>
              <ul className="space-y-1.5">
                {quality.top_agents.map((use) => (
                  <li key={use.agent_id} className="flex items-center justify-between gap-3">
                    <Link
                      href={ROUTES.AGENT_DETAIL(use.agent_id)}
                      className="flex min-w-0 items-center gap-2 text-sm hover:underline"
                    >
                      <Face agent={byId.get(use.agent_id)} agentId={use.agent_id} />
                      <span className="truncate">{use.name}</span>
                    </Link>
                    <span className="text-muted-foreground shrink-0 text-xs tabular-nums">
                      {t("runs", { count: use.run_count })}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {quality.down_rated.length > 0 && (
            <section className="space-y-2">
              <h3 className="text-muted-foreground text-xs font-medium">{t("notHelpful")}</h3>
              <ul className="divide-border divide-y">
                {quality.down_rated.map((answer, index) => (
                  <DownRated
                    key={`${answer.rated_at}-${index}`}
                    answer={answer}
                    agent={answer.agent_id ? byId.get(answer.agent_id) : undefined}
                  />
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </ListCard>
  );
}

function DownRated({ answer, agent }: { answer: GroupDownRatedAnswer; agent: Agent | undefined }) {
  const t = useTranslations("groups.quality");
  const format = useFormatter();
  return (
    <li className="flex items-start gap-2.5 py-2.5 first:pt-0 last:pb-0">
      {answer.agent_id ? (
        <Face agent={agent} agentId={answer.agent_id} />
      ) : (
        <MessageSquareWarning className="text-muted-foreground mt-0.5 h-5 w-5 shrink-0" />
      )}
      <div className="min-w-0 flex-1">
        <p className="text-sm">
          {answer.comment ? (
            t("quoted", { comment: answer.comment })
          ) : (
            <span className="text-muted-foreground">{t("noComment")}</span>
          )}
        </p>
        <p className="text-muted-foreground mt-0.5 text-xs">
          {t("ratedOn", {
            agent: answer.agent_name ?? t("unknownAgent"),
            date: format.dateTime(new Date(answer.rated_at), { dateStyle: "medium" }),
          })}
        </p>
      </div>
      {answer.run_id && (
        <Link
          href={`${ROUTES.RUNS}?run=${answer.run_id}`}
          className="text-muted-foreground hover:text-foreground shrink-0 text-xs underline-offset-2 hover:underline"
        >
          {t("openRun")}
        </Link>
      )}
    </li>
  );
}

/** The agent's face, from the catalog this card already loads - the rows name it by id. */
function Face({ agent, agentId }: { agent: Agent | undefined; agentId: string }) {
  return (
    <AgentAvatar
      agentId={agentId}
      slug={agent?.slug ?? ""}
      hasAvatar={agent?.has_avatar ?? false}
      size="sm"
      className="h-5 w-5"
    />
  );
}
