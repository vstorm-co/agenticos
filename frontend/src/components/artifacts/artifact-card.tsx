"use client";

import Link from "next/link";
import { Globe, PanelsTopLeft } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import { Badge, Card, CardContent } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import type { Artifact } from "@/types/artifact";

/**
 * One artifact in the list.
 *
 * Who can reach it is never implicit: a badge for an organization-wide page and
 * another for one with a public link, because "who else is reading this" is the
 * first thing to know about a report before forwarding it.
 */
export function ArtifactCard({ artifact }: { artifact: Artifact }) {
  const t = useTranslations("artifacts");
  const format = useFormatter();
  return (
    <Link href={ROUTES.ARTIFACT_DETAIL(artifact.id)} className="block h-full">
      <Card className="hover:border-foreground/20 h-full transition-colors">
        <CardContent className="space-y-1.5 p-5">
          <span className="flex items-center gap-2">
            <PanelsTopLeft className="text-muted-foreground h-4 w-4 shrink-0" />
            <span className="text-foreground truncate text-sm font-medium">{artifact.title}</span>
          </span>
          <span className="text-muted-foreground block truncate font-mono text-xs">
            {artifact.name}
          </span>
          <span className="flex flex-wrap items-center gap-1.5">
            {artifact.visibility === "org" && <Badge variant="secondary">{t("sharedOrg")}</Badge>}
            {artifact.public_url !== null && (
              <Badge variant="outline" className="gap-1">
                <Globe className="h-3 w-3" />
                {t("publicBadge")}
              </Badge>
            )}
          </span>
          <span className="text-muted-foreground block text-xs">
            {t("publishedVersion", {
              version: artifact.current_version?.number ?? 0,
              when: format.dateTime(new Date(artifact.published_at), {
                dateStyle: "medium",
                timeStyle: "short",
              }),
            })}
          </span>
        </CardContent>
      </Card>
    </Link>
  );
}
