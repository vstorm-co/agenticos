"use client";

import { useTranslations } from "next-intl";
import { FileWarning, Wrench } from "lucide-react";

import { CopyButton } from "@/components/chat/copy-button";
import { RunWaterfall } from "@/components/runs/run-waterfall";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/states";
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

  // A finding's outcome is recorded in a later round's dispositions - the
  // agent answers the last round's findings when it asks for the next one -
  // so outcomes resolve across the whole ledger, not per round.
  const solLoopOutcomes: Record<string, string> = {};
  for (const round of manifest.sol_loop_rounds ?? []) {
    for (const [id, outcome] of Object.entries(round.dispositions ?? {})) {
      solLoopOutcomes[id] = outcome;
    }
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
          manifest.system_prompts.length === 0 && (
            <p className="text-muted-foreground text-sm">{t("noInstructionsSent")}</p>
          )
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

      {/* The sol-loop ledger: each round's verdict and findings, with what the
          agent did with them. A round that ran out of budget or that the
          reviewer never answered reads as exactly that, never as approval. */}
      {!!manifest.sol_loop_rounds?.length && (
        <Section title={t("solLoopRounds", { count: manifest.sol_loop_rounds.length })}>
          <ul className="space-y-3">
            {manifest.sol_loop_rounds.map((round) => (
              <li key={round.round} className="space-y-1.5">
                <p className="text-sm font-medium">
                  {t("solLoopRound", {
                    round: round.round,
                    scope: round.scope,
                    verdict: round.verdict,
                  })}
                </p>
                {!!round.stop_reason && (
                  <p className="text-muted-foreground text-xs">
                    {t("solLoopStopReason", { reason: round.stop_reason })}
                  </p>
                )}
                {!!round.reason && <p className="text-muted-foreground text-xs">{round.reason}</p>}
                {round.findings.length > 0 && (
                  <ol className="space-y-1.5">
                    {round.findings.map((finding) => {
                      const outcome = finding.outcome ?? solLoopOutcomes[finding.id];
                      return (
                        <li key={finding.id} className="space-y-0.5 text-sm">
                          <p>
                            {t("solLoopFinding", {
                              id: finding.id,
                              severity: finding.severity,
                              location: `${finding.file}${finding.line ? `:${finding.line}` : ""}`,
                              claim: finding.claim,
                            })}
                          </p>
                          {!!finding.fix && (
                            <p className="text-muted-foreground text-xs">
                              {t("solLoopFix", { fix: finding.fix })}
                            </p>
                          )}
                          {!!outcome && (
                            <p className="text-muted-foreground text-xs">
                              {t("solLoopOutcome", { outcome })}
                            </p>
                          )}
                        </li>
                      );
                    })}
                  </ol>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* The eval tool-tuning runs: each run's score, every case's
          classification, and the draft proposals with their evidence. A
          proposal is a draft for a human to approve, never a fix that has
          been made. */}
      {!!manifest.eval_tool_tuning_runs?.length && (
        <Section title={t("evalToolTuningRuns", { count: manifest.eval_tool_tuning_runs.length })}>
          <ul className="space-y-3">
            {manifest.eval_tool_tuning_runs.map((run, index) => (
              <li key={`${run.tool}-${index}`} className="space-y-1.5">
                <p className="text-sm font-medium">
                  {t("evalToolTuningRun", {
                    tool: run.tool,
                    passed: run.passed,
                    total: run.total,
                  })}
                </p>
                {!!run.dominant_failure && (
                  <p className="text-muted-foreground text-xs">
                    {t("evalToolTuningDominantFailure", { failure: run.dominant_failure })}
                  </p>
                )}
                {run.cases.length > 0 && (
                  <ol className="space-y-1.5">
                    {run.cases.map((c) => (
                      <li key={c.name} className="space-y-0.5 text-sm">
                        <p>
                          {t("evalToolTuningCase", {
                            name: c.name,
                            classification: c.classification,
                          })}
                        </p>
                        <p className="text-muted-foreground text-xs">{c.detail}</p>
                      </li>
                    ))}
                  </ol>
                )}
                {run.proposals.length > 0 && (
                  <ol className="space-y-1.5">
                    {run.proposals.map((proposal) => (
                      <li key={proposal.title} className="space-y-0.5 text-sm">
                        <p>
                          {t("evalToolTuningProposal", {
                            kind: proposal.kind,
                            title: proposal.title,
                          })}
                        </p>
                        <p className="text-muted-foreground text-xs">{proposal.proposed}</p>
                        <p className="text-muted-foreground text-xs">
                          {t("evalToolTuningProposalEvidence", {
                            evidence: proposal.evidence.join(", "),
                            status: proposal.status,
                          })}
                        </p>
                      </li>
                    ))}
                  </ol>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* The burst ledger: each burst's merged outcome and every part's
          status. A part that failed reads as exactly that, never as a part
          that finished - the merge is the record, not a summary of it. */}
      {!!manifest.burst_runs?.length && (
        <Section title={t("burstRuns", { count: manifest.burst_runs.length })}>
          <ul className="space-y-3">
            {manifest.burst_runs.map((burst) => (
              <li key={burst.burst} className="space-y-1.5">
                <p className="text-sm font-medium">
                  {t("burstRun", { burst: burst.burst, task: burst.task })}
                </p>
                <ol className="space-y-0.5">
                  {burst.results.map((part) => (
                    <li key={part.id} className="text-sm">
                      <span className={part.status === "failed" ? "text-destructive" : ""}>
                        {t("burstPart", {
                          id: part.id,
                          title: part.title,
                          status: part.status,
                        })}
                        {part.reason ? ` (${part.reason})` : ""}
                      </span>
                    </li>
                  ))}
                </ol>
                <pre className="bg-muted/50 max-h-64 overflow-auto rounded-md p-3 text-xs whitespace-pre-wrap">
                  {burst.merged}
                </pre>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* The proof scenarios: each reproduction and its observed attempts. A
          scenario is proven only when the same reproduction failed before the
          fix and passed after it - a unit-test attempt never counts, so it
          reads as exactly that, never as proof. */}
      {!!manifest.proof_scenarios?.length && (
        <Section title={t("proofScenarios", { count: manifest.proof_scenarios.length })}>
          <ul className="space-y-3">
            {manifest.proof_scenarios.map((scenario) => {
              const beforeFailed = scenario.attempts.filter(
                (attempt) =>
                  attempt.phase === "before_fix" &&
                  attempt.status === "failed" &&
                  attempt.evidence_kind !== "unit_test",
              );
              const afterPassed = scenario.attempts.filter(
                (attempt) =>
                  attempt.phase === "after_fix" &&
                  attempt.status === "passed" &&
                  attempt.evidence_kind !== "unit_test",
              );
              const normalizeCommand = (command: string) => command.trim().replace(/\s+/g, " ");
              const proven = beforeFailed.some((before) =>
                afterPassed.some(
                  (after) =>
                    normalizeCommand(before.command ?? "") ===
                    normalizeCommand(after.command ?? ""),
                ),
              );
              return (
                <li key={scenario.id} className="space-y-1.5">
                  <p className="text-sm font-medium">
                    {t("proofScenario", {
                      id: scenario.id,
                      name: scenario.name,
                      proven: proven ? t("proofScenarioProven") : t("proofScenarioUnproven"),
                    })}
                  </p>
                  {!!scenario.covers.length && (
                    <p className="text-muted-foreground text-xs">
                      {t("proofScenarioCovers", { files: scenario.covers.join(", ") })}
                    </p>
                  )}
                  {scenario.attempts.length > 0 && (
                    <ol className="space-y-1.5">
                      {scenario.attempts.map((attempt, index) => (
                        <li key={index} className="space-y-0.5 text-sm">
                          <p>
                            {t("proofAttempt", {
                              phase: attempt.phase,
                              status: attempt.status,
                              evidence: attempt.evidence_kind,
                            })}
                          </p>
                          {!!attempt.observed && (
                            <pre className="bg-muted/40 max-h-40 overflow-auto rounded p-3 text-xs whitespace-pre-wrap">
                              {attempt.observed}
                            </pre>
                          )}
                        </li>
                      ))}
                    </ol>
                  )}
                </li>
              );
            })}
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
          <Badge variant="outline" className="text-xs">
            {tool.kind}
          </Badge>
        )}
      </div>
      {tool.description !== null && (
        <p className="text-muted-foreground mt-1 text-xs">{tool.description}</p>
      )}
      <details className="mt-1">
        <summary className="text-muted-foreground cursor-pointer text-xs select-none">
          {t("argumentSchema")}
        </summary>
        <pre className="bg-muted/40 mt-1 max-h-60 overflow-auto rounded p-2 text-xs">
          {JSON.stringify(tool.parameters_json_schema, null, 2)}
        </pre>
      </details>
    </li>
  );
}
