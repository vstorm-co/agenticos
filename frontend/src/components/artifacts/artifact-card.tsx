"use client";

import Link from "next/link";
import { Globe } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import { ArtifactThumbnail } from "@/components/artifacts/artifact-thumbnail";
import { Badge, Card, DocPeek } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import type { Artifact } from "@/types/artifact";

/**
 * One artifact in the list: the page itself, live, on top.
 *
 * Earlier versions stack behind it, one sheet per version kept past the first,
 * so a report that has been through seven drafts looks it. Who can reach it is
 * never implicit: a badge for an organization-wide page and another for one with
 * a public link, because "who else is reading this" is the first thing to know
 * about a report before forwarding it.
 */
export function ArtifactCard({ artifact }: { artifact: Artifact }) {
  const t = useTranslations("artifacts");
  const format = useFormatter();
  const version = artifact.current_version?.number ?? 0;
  return (
    <Link href={ROUTES.ARTIFACT_DETAIL(artifact.id)} className="group block h-full">
      <Card className="peek-card group-hover:border-foreground/20 flex h-full flex-col overflow-hidden">
        <DocPeek
          sheets={version - 1}
          badge={version > 0 ? t("versionBadge", { version }) : undefined}
          className="h-40"
          paperClassName="p-0"
        >
          {artifact.current_version !== null && (
            <ArtifactThumbnail artifactId={artifact.id} title={artifact.title} />
          )}
        </DocPeek>
        <span className="flex flex-1 flex-col gap-1.5 p-4 pt-3.5">
          <span className="text-foreground truncate text-sm font-medium">{artifact.title}</span>
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
          <span className="text-muted-foreground mt-auto block pt-1 text-xs">
            {t("publishedVersion", {
              version,
              when: format.dateTime(new Date(artifact.published_at), {
                dateStyle: "medium",
                timeStyle: "short",
              }),
            })}
          </span>
        </span>
      </Card>
    </Link>
  );
}
