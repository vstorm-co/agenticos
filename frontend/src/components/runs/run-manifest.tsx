"use client";

import { useTranslations } from "next-intl";
import { FileWarning, Wrench } from "lucide-react";

import { CopyButton } from "@/components/chat/copy-button";
import { RunWaterfall } from "@/components/runs/run-waterfall";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui";
import { useRunManifest } from "@/hooks";
import { ApiError } from "@/lib/api-client";
import type { ManifestTool } from "@/types/runs";

/**
 * What the run handed its model: the prompt, the tools, the settings, and the
 * requests it made.
 *
 * The panel exists because none of it is visible anywhere else and none of it is
 * derivable from the spec. What the model was told is the spec's instructions
 * plus the platform's, plus whatever a channel binding appended, plus the bound
 * skills, plus whichever reminder fired on this request; what it could call is
 * the capability registry plus the organization's MCP servers minus whatever
 * tool search hid. So it is recorded from the wire as the run happens and read
 * back here - which means what this shows is what was sent, rather than a good
 * guess assembled from the stored spec.
 *
 * **A run with nothing recorded says so, and says which nothing it is.** The
 * endpoint answers 404 for a run that never reached a model - refused by a
 * budget, blocked on the way in, or simply older than this record - and that is
 * a different sentence from a request that failed. Drawing both as an empty
 * panel would claim the agent was given no prompt and no tools.
 */
export function RunManifest({ runId }: { runId: string }) {
  const t = useTranslations("pages.runs");
  const { manifest, isLoading, error } = useRunManifest(runId);

  if (isLoading) return <LoadingState variant="skeleton-panel" rows={3} />;
  if (manifest === undefined) {
    return error instanceof ApiError && error.status === 404 ? (
      <EmptyState
        icon={FileWarning}
        title={t("nothingRecordedForThisRun")}
        description={t("nothingRecordedBecause")}
      />
    ) : (
      <ErrorState title={t("manifestCouldNotBeRead")} />
    );
  }

  return (
    <div className="space-y-5">
      {manifest.truncated && (
        <p className="text-muted-foreground border-warning/40 border-l-2 pl-3 text-xs">
          {t("recordWasTrimmed")}
        </p>
      )}

      <Section title={t("systemPrompt")} copyText={manifest.instructions ?? undefined}>
        {manifest.instructions === null ? (
          <p className="text-muted-foreground text-sm">{t("noInstructionsSent")}</p>
        ) : (
          <pre className="bg-muted/40 max-h-80 overflow-auto rounded p-3 text-xs whitespace-pre-wrap">
            {manifest.instructions}
          </pre>
        )}
        {/* Separate on the wire, so separate here: an agent built with a system
            prompt sends one of these and a capability injecting a reminder sends
            another, and a reader comparing spec with reality needs both. */}
        {manifest.system_prompts.map((prompt, index) => (
          <pre
            key={index}
            className="bg-muted/40 mt-2 max-h-60 overflow-auto rounded p-3 text-xs whitespace-pre-wrap"
          >
            {prompt}
          </pre>
        ))}
      </Section>

      {Object.keys(manifest.settings).length > 0 && (
        <Section title={t("modelSettings")}>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(manifest.settings).map(([key, value]) => (
              <Badge key={key} variant="secondary" className="font-mono text-xs">
                {t("settingPair", { key, value: String(value) })}
              </Badge>
            ))}
          </div>
        </Section>
      )}

      <Section title={t("toolsSent", { count: manifest.tools.length })}>
        {manifest.tools.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("noToolsSent")}</p>
        ) : (
          <ul className="space-y-1.5">
            {manifest.tools.map((tool) => (
              <ToolRow key={`${tool.kind}-${tool.name}`} tool={tool} />
            ))}
          </ul>
        )}
      </Section>

      <Section title={t("requests", { count: manifest.requests.length })}>
        <RunWaterfall requests={manifest.requests} />
      </Section>

      {manifest.messages.length > 0 && (
        <Section
          title={t("lastRequestContext")}
          copyText={JSON.stringify(manifest.messages, null, 2)}
        >
          <details className="rounded-md border">
            <summary className="text-muted-foreground cursor-pointer px-3 py-1.5 text-xs select-none">
              {t("messagesCount", { count: manifest.messages.length })}
            </summary>
            <pre className="max-h-96 overflow-auto border-t p-3 text-xs">
              {JSON.stringify(manifest.messages, null, 2)}
            </pre>
          </details>
        </Section>
      )}
    </div>
  );
}

function Section({
  title,
  copyText,
  children,
}: {
  title: string;
  copyText?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="group space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">
          {title}
        </h4>
        {copyText !== undefined && <CopyButton text={copyText} />}
      </div>
      {children}
    </section>
  );
}

/**
 * One tool, with the sentence the model reads.
 *
 * The description leads rather than hiding behind a disclosure: it is what the
 * model decides on, and an agent that never calls a tool it has is usually an
 * agent whose tool describes itself badly. The schema is behind the disclosure
 * because it is long and is read second.
 */
function ToolRow({ tool }: { tool: ManifestTool }) {
  const t = useTranslations("pages.runs");
  return (
    <li className="rounded-md border px-3 py-2">
      <div className="flex items-center gap-2">
        <Wrench className="text-muted-foreground h-3 w-3 shrink-0" aria-hidden />
        <span className="font-mono text-xs">{tool.name}</span>
        {tool.kind !== "function" && (
          <Badge variant="outline" className="text-[10px]">
            {tool.kind}
          </Badge>
        )}
      </div>
      {tool.description !== null && (
        <p className="text-muted-foreground mt-1 text-xs">{tool.description}</p>
      )}
      <details className="mt-1">
        <summary className="text-muted-foreground cursor-pointer text-[11px] select-none">
          {t("argumentSchema")}
        </summary>
        <pre className="bg-muted/40 mt-1 max-h-60 overflow-auto rounded p-2 text-[11px]">
          {JSON.stringify(tool.parameters_json_schema, null, 2)}
        </pre>
      </details>
    </li>
  );
}
