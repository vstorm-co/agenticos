"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { useBranding } from "@/components/branding/branding-provider";
import { Badge } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import type { RoutineAccessReview, RoutineSourceItem } from "@/lib/routine-access-api";

/**
 * The reviewed sources grouped by kind, each kind folded to a count and each
 * source by its name - its id only on hover, for whoever has to look it up.
 * An unavailable source is marked on its row, and its kind opens by itself.
 */
export function RoutineAccessSources({
  agentId,
  review,
}: {
  agentId: string;
  review: RoutineAccessReview;
}) {
  const t = useTranslations("triggers.access");
  const { appName } = useBranding();
  const unavailable = new Set(review.unavailable_sources);
  const required = new Set(review.required_unavailable_sources);
  const kinds = new Map<RoutineSourceItem["kind"], RoutineSourceItem[]>();
  for (const item of review.sources) kinds.set(item.kind, [...(kinds.get(item.kind) ?? []), item]);
  if (review.sources.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("noSources")}</p>;
  }
  return (
    <div className="space-y-2">
      {[...kinds.entries()].map(([kind, sources]) => (
        <details
          key={kind}
          open={sources.some((source) => source.name != null && unavailable.has(source.name))}
          className="rounded-md border px-2 py-1"
        >
          <summary className="cursor-pointer text-sm">
            {t("kindCount", { name: t("kind", { kind }), count: sources.length })}
          </summary>
          <ul className="space-y-1 py-1 pl-4 text-xs break-words">
            {sources.map((source) => {
              const name = kind === "platform" ? appName : (source.name ?? t("unnamed"));
              const missing =
                source.name == null || !unavailable.has(source.name)
                  ? null
                  : required.has(source.name)
                    ? "requiredMark"
                    : "unavailableMark";
              return (
                <li
                  key={`${source.id}:${source.name}:${source.detail}`}
                  title={source.id ?? undefined}
                  className="flex flex-wrap items-center gap-2"
                >
                  <span>
                    {name}
                    {source.detail && (
                      <span className="text-muted-foreground"> · {source.detail}</span>
                    )}
                  </span>
                  {missing && (
                    <>
                      <Badge variant={missing === "requiredMark" ? "destructive" : "secondary"}>
                        {t(missing)}
                      </Badge>
                      <Link
                        className="underline underline-offset-4"
                        href={`${ROUTES.AGENT_DETAIL(agentId)}?highlight=agent-mcp`}
                      >
                        {t("inspectAgent")}
                      </Link>
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        </details>
      ))}
    </div>
  );
}
