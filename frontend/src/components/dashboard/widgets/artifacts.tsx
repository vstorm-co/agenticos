"use client";

import Link from "next/link";
import { ArrowUpRight, PanelsTopLeft } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { useArtifacts } from "@/hooks/use-artifacts";
import { ROUTES } from "@/lib/constants";
import { timeAgo } from "@/lib/utils";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** How many a card lists; the page behind "see all" has the rest. */
const SHOWN = 5;

/**
 * The pages agents published most recently that the caller may open - the
 * report a schedule refreshed this morning, one place to find it. The same
 * listing the Artifacts page reads, first page only.
 */
export function ArtifactsWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.artifacts");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const { artifacts, isLoading, error, refetch } = useArtifacts({ limit: SHOWN });

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : artifacts.length === 0 ? (
        <WidgetEmptyBody
          icon={PanelsTopLeft}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <ul className="space-y-1">
          {artifacts.map((artifact) => (
            <li key={artifact.id}>
              <Link
                href={ROUTES.ARTIFACT_DETAIL(artifact.id)}
                className="hover:bg-muted/60 focus-visible:ring-ring flex items-center gap-3 rounded-lg px-1 py-2.5 outline-none focus-visible:ring-2"
              >
                <span
                  className="bg-foreground/[0.04] text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-lg"
                  aria-hidden
                >
                  <PanelsTopLeft className="size-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="text-foreground block truncate text-sm font-medium">
                    {artifact.title}
                  </span>
                  <span className="text-muted-foreground block text-xs">
                    {timeAgo(artifact.published_at, tTime, locale)}
                  </span>
                </span>
                <ArrowUpRight className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </WidgetFrame>
  );
}
