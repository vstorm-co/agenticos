"use client";

import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";

import { ArtifactThumbnail } from "@/components/artifacts/artifact-thumbnail";
import { ROUTES } from "@/lib/constants";

export interface PublishedArtifactPayload {
  artifactId: string;
  versionId: string;
  version: number;
  title: string;
  /** True when the page matched the current version and nothing new was stored. */
  unchanged: boolean;
}

/**
 * Parse a `publish_artifact` result, or null for anything else - a refusal, a
 * steer returned on the last attempt - so the caller falls back to the text.
 */
export function parsePublishedArtifact(result: string): PublishedArtifactPayload | null {
  try {
    const p = JSON.parse(result);
    if (
      p &&
      typeof p === "object" &&
      p.kind === "artifact" &&
      typeof p.artifact_id === "string" &&
      typeof p.version_id === "string"
    ) {
      return {
        artifactId: p.artifact_id,
        versionId: p.version_id,
        version: Number(p.version),
        title: String(p.title ?? ""),
        unchanged: p.unchanged === true,
      };
    }
  } catch {
    /* not JSON - fall back to the raw renderer */
  }
  return null;
}

/**
 * The page a run published, as a link to the version *this* run wrote.
 *
 * The version and not the artifact, so a conversation read back after the agent
 * republished still opens what was published in it - which is the evidence the
 * run left, not whatever the link shows today.
 */
export function PublishedArtifactResult({ data }: { data: PublishedArtifactPayload }) {
  const t = useTranslations("chat.tools");
  return (
    <Link
      href={`${ROUTES.ARTIFACT_DETAIL(data.artifactId)}?version=${encodeURIComponent(data.versionId)}`}
      className="hover:bg-accent/40 my-1 flex items-center gap-3 rounded-xl border p-2 pr-3 transition-colors"
    >
      {/* The page itself, the way the Artifacts listing draws it: an icon and a
          title said a page existed, and nothing about whether it was the one
          that was asked for. */}
      <span className="border-foreground/10 bg-muted/40 relative h-24 w-36 shrink-0 overflow-hidden rounded-lg border sm:h-28 sm:w-44">
        <ArtifactThumbnail
          artifactId={data.artifactId}
          versionId={data.versionId}
          title={data.title}
        />
      </span>
      <span className="min-w-0 flex-1">
        <span className="text-foreground line-clamp-2 text-sm font-medium">{data.title}</span>
        <span className="text-muted-foreground mt-1 block text-xs">
          {data.unchanged
            ? t("artifactUnchanged", { version: data.version })
            : t("artifactVersion", { version: data.version })}
        </span>
      </span>
      <ExternalLink className="text-muted-foreground h-4 w-4 shrink-0" />
    </Link>
  );
}
