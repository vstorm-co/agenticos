"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import { useAgentVersion } from "@/hooks";
import type { AgentSpec } from "@/types/agents";

import { specText } from "./version-history";

interface PublishStateProps {
  agentId: string;
  /** The version that is live, or null when nothing has ever been published. */
  currentVersionId: string | null;
  /** The stored draft - the server's copy, never the local edit. */
  draftSpec: AgentSpec;
}

/**
 * Whether the agent people are talking to is the one on screen.
 *
 * The "Unsaved" badge answers "is my edit stored" and clears the moment the
 * autosave settles - at which point the page reads as finished while every
 * channel, widget and API call is still answering with the published version.
 * This badge answers the other question: the stored draft against the frozen
 * version spec, so it holds still while typing and no debounce can clear it.
 * Compared as sorted-keys YAML (`specText`), the same serialization the diff
 * reads, so key order that moves between two dumps cannot read as a change
 * nobody made.
 *
 * Absent for an agent that has never published - the status badge already says
 * "draft", and there is no version to differ from - and quiet until the
 * version arrives.
 */
export function PublishState({ agentId, currentVersionId, draftSpec }: PublishStateProps) {
  const t = useTranslations("agents");
  const { version } = useAgentVersion(agentId, currentVersionId);
  const differs = useMemo(
    () => (version ? specText(draftSpec) !== specText(version.spec) : false),
    [draftSpec, version],
  );
  if (!version) return null;
  return differs ? (
    <Badge
      variant="outline"
      className="text-muted-foreground"
      title={t("draftDiffersHint", { version: version.version })}
    >
      <span aria-hidden className="bg-warning h-1.5 w-1.5 shrink-0 rounded-full" />
      {t("draftDiffersFromPublished", { version: version.version })}
    </Badge>
  ) : (
    <Badge variant="outline" className="text-muted-foreground">
      <span aria-hidden className="bg-success h-1.5 w-1.5 shrink-0 rounded-full" />
      {t("upToDateWithPublished", { version: version.version })}
    </Badge>
  );
}
