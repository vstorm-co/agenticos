"use client";

import { useTranslations } from "next-intl";
import { FileWarning } from "lucide-react";

import { CopyButton } from "@/components/chat/copy-button";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui";
import { EmptyState, ErrorState } from "@/components/states";
import { useRunManifest } from "@/hooks";
import { ApiError } from "@/lib/api-client";
import { RunModelInput } from "./run-model-input";

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
  const ts = useTranslations("states");
  const { manifest, isLoading, error } = useRunManifest(runId);

  if (isLoading)
    return (
      <div className="space-y-5" role="status" aria-label={ts("loading")}>
        {[0, 1, 2].map((section) => (
          <section key={section} className="space-y-1.5" aria-hidden>
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-32 w-full" />
          </section>
        ))}
      </div>
    );
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

      <RunModelInput manifest={manifest} />

      {/* What steered the run, and who: a correction the run's model received
          mid-run reads as the agent changing its mind otherwise (#2106). */}
      {!!manifest.reviews?.length && (
        <Section title={t("reviewerCorrections", { count: manifest.reviews.length })}>
          <ul className="space-y-1.5">
            {manifest.reviews.map((review) => (
              <li key={`${review.reviewer}-${review.after_request}`} className="text-sm">
                <span className="text-muted-foreground text-xs">
                  {t("reviewerCorrectionBy", {
                    reviewer: review.reviewer,
                    request: review.after_request,
                  })}
                </span>
                <p>{review.steer}</p>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* One `run_code` step hides every call its script made; this is them (#2107). */}
      {!!manifest.code_runs?.length && (
        <Section title={t("codeRuns", { count: manifest.code_runs.length })}>
          <ul className="space-y-3">
            {manifest.code_runs.map((run) => (
              <li key={run.tool_call_id} className="space-y-1.5">
                <pre className="bg-muted/50 max-h-64 overflow-auto rounded-md p-3 text-xs">
                  {run.code}
                </pre>
                <p className="text-muted-foreground text-xs">
                  {t("codeRunCalls", { count: run.calls.length + (run.omitted_calls ?? 0) })}
                </p>
                <ol className="space-y-0.5">
                  {run.calls.map((call, index) => (
                    <li
                      key={call.tool_call_id ?? index}
                      className="flex min-w-0 items-center gap-2 font-mono text-xs"
                    >
                      <span className={call.status === "failed" ? "text-destructive" : ""}>
                        {call.tool}
                      </span>
                      <span className="text-muted-foreground min-w-0 flex-1 truncate">
                        {call.args}
                      </span>
                      {call.status === "awaiting_approval" && (
                        <Badge variant="outline" className="shrink-0 font-sans">
                          {t("toolState", { status: "awaiting_approval" })}
                        </Badge>
                      )}
                    </li>
                  ))}
                </ol>
                {!!run.omitted_calls && (
                  <p className="text-muted-foreground text-xs">
                    {t("codeRunOmittedCalls", { count: run.omitted_calls })}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}

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
