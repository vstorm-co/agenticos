"use client";

import { useMemo } from "react";
import { FlaskConical } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge, Button } from "@/components/ui";
import { useDraftBase } from "@/hooks";
import type { AgentEnvironment, AgentSpec } from "@/types/agents";

import { specText } from "./version-history";

interface PublishStateProps {
  agentId: string;
  /** The default environment - what channels, widgets and the API answer with. */
  production: AgentEnvironment | undefined;
  /** The stored draft - the server's copy, never the local edit. */
  draftSpec: AgentSpec;
  /** Test the draft against its base; offered only while the two differ. */
  onTest?: () => void;
}

/**
 * Whether the draft on screen is a published version, and which version
 * production runs.
 *
 * The "Unsaved" badge answers "is my edit stored" and clears the moment the
 * autosave settles. This badge answers the other question: the stored draft
 * against the version it is based on - the latest published one - so it holds
 * still while typing and no debounce can clear it. Compared as sorted-keys YAML
 * (`specText`), the same serialization the diff reads, so key order that moves
 * between two dumps cannot read as a change nobody made.
 *
 * A failing guard can hold production on an older version than the latest, and
 * then that is a badge of its own: the draft differing from production is not
 * the draft differing from what it was made from.
 *
 * Absent for an agent that has never published - the status badge already says
 * "draft", and there is no version to differ from - and quiet until the
 * version arrives.
 */
export function PublishState({ agentId, production, draftSpec, onTest }: PublishStateProps) {
  const t = useTranslations("agents");
  const { base } = useDraftBase(agentId);
  const differs = useMemo(
    () => (base ? specText(draftSpec) !== specText(base.spec) : false),
    [draftSpec, base],
  );
  if (!base) return null;
  const behind = production !== undefined && production.version_id !== base.id;
  const waiting =
    behind &&
    production.tracks_latest &&
    production.guard_suite_ids.length > 0 &&
    production.behind_by > 0;
  return (
    <>
      {differs ? (
        <>
          <Badge
            variant="outline"
            className="text-muted-foreground"
            title={t("draftDiffersHint", { version: base.version })}
          >
            <span aria-hidden className="bg-warning h-1.5 w-1.5 shrink-0 rounded-full" />
            {t("draftDiffersFromPublished", { version: base.version })}
          </Badge>
          {onTest && (
            <Button
              size="sm"
              variant="outline"
              className="h-6 px-2 text-xs"
              onClick={onTest}
              data-tour="agent-test-draft"
            >
              <FlaskConical className="h-3 w-3" aria-hidden />
              {t("testDraft")}
            </Button>
          )}
        </>
      ) : (
        <Badge variant="outline" className="text-muted-foreground">
          <span aria-hidden className="bg-success h-1.5 w-1.5 shrink-0 rounded-full" />
          {t("upToDateWithPublished", { version: base.version })}
        </Badge>
      )}
      {behind && (
        <Badge
          variant="outline"
          className="text-muted-foreground"
          title={t("productionHint", { version: production.version })}
        >
          {t(waiting ? "productionWaiting" : "productionOn", { version: production.version })}
        </Badge>
      )}
    </>
  );
}
