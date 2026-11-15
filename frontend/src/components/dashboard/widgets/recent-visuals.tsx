"use client";

import Link from "next/link";
import { Code2, GitBranch, Shapes } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { qk } from "@/lib/query-keys";
import { VisualFrame } from "@/components/chat/visual-frame";
import { PreviewSkeleton } from "@/components/ui/preview-skeleton";

import { ArtifactThumbnail } from "@/components/artifacts/artifact-thumbnail";
import { useRecentVisuals } from "@/hooks/use-recent-visuals";
import { ROUTES } from "@/lib/constants";
import { timeAgo } from "@/lib/utils";
import { getVisualPreview, visualThumbnailUrl, type VisualListItem } from "@/lib/visuals-api";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** How many a card shows: two rows of three on a wide card. */
const SHOWN = 6;

const KIND_ICON = { svg: Shapes, mermaid: GitBranch, html: Code2 } as const;

/**
 * The drawings agents made for the caller lately - a diagram from this morning's
 * thread, the explainer someone asked for yesterday - each a tile that opens the
 * conversation it was drawn in.
 */
export function RecentVisualsWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.recent-visuals");
  const { visuals, isLoading, error, refetch } = useRecentVisuals(SHOWN);

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton variant="gallery" rows={6} />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : visuals.length === 0 ? (
        <WidgetEmptyBody
          icon={Shapes}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {visuals.map((visual) => (
            <li key={visual.id}>
              <VisualTile visual={visual} />
            </li>
          ))}
        </ul>
      )}
    </WidgetFrame>
  );
}

function VisualTile({ visual }: { visual: VisualListItem }) {
  const t = useTranslations("dashboard.widgets.recent-visuals");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const [broken, setBroken] = useState(false);
  const Icon = KIND_ICON[visual.kind];
  const live = !visual.has_thumbnail && visual.artifact_id !== null;
  const pictured = !live && (visual.has_thumbnail || visual.kind === "html");
  return (
    <Link
      href={`${ROUTES.CHAT}?id=${visual.conversation_id}`}
      className="group hover:bg-accent/40 flex min-w-0 flex-col gap-1.5 rounded-xl p-1.5"
    >
      {/* Named above the picture: under it, a picture taller than the card's row
          took the name and the date past the card's edge. */}
      <span className="flex min-w-0 items-baseline justify-between gap-2">
        <span className="text-foreground truncate text-sm font-medium">{visual.title}</span>
        <span className="text-muted-foreground shrink-0 text-xs">
          {timeAgo(visual.created_at, tTime, locale)}
        </span>
      </span>
      <span className="bg-foreground/[0.04] relative flex aspect-[16/9] items-center justify-center overflow-hidden rounded-lg">
        {live && visual.artifact_id !== null ? (
          <ArtifactThumbnail artifactId={visual.artifact_id} title={visual.title} />
        ) : pictured && !broken ? (
          // A same-origin address behind the console's session, which `next/image`
          // would only fetch a second time.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={visualThumbnailUrl(visual.id)}
            alt=""
            onError={() => setBroken(true)}
            className="h-full w-full object-contain object-center transition-transform group-hover:scale-[1.02]"
          />
        ) : (
          <VisualPreviewFallback
            visual={visual}
            icon={<Icon className="text-muted-foreground size-7" aria-hidden />}
          />
        )}
        {visual.artifact_id !== null && (
          <span className="bg-background/90 text-foreground absolute top-1.5 right-1.5 rounded-full px-1.5 py-0.5 text-[10px] font-medium">
            {t("app")}
          </span>
        )}
      </span>
    </Link>
  );
}

function VisualPreviewFallback({
  visual,
  icon,
}: {
  visual: VisualListItem;
  icon: React.ReactNode;
}) {
  const [visible, setVisible] = useState(false);
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!box) return;
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setVisible(true);
      },
      { rootMargin: "240px" },
    );
    observer.observe(box);
    return () => observer.disconnect();
  }, [box]);
  const query = useQuery({
    queryKey: qk.visuals.preview(visual.id),
    queryFn: () => getVisualPreview(visual.id),
    enabled: visible,
    staleTime: Infinity,
    retry: false,
  });
  return (
    <div ref={setBox} className="pointer-events-none absolute inset-0" aria-hidden>
      {query.data ? (
        <div className="h-[400%] w-[400%] origin-top-left scale-25">
          <VisualFrame
            kind={query.data.kind}
            content={query.data.content}
            title={query.data.title}
            done
            height={360}
            fill
          />
        </div>
      ) : query.isError ? (
        <div className="flex h-full items-center justify-center">{icon}</div>
      ) : (
        <PreviewSkeleton />
      )}
    </div>
  );
}
