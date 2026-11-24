"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { usePermissions } from "@/hooks/use-permissions";
import { ruleCounts, useFailureLearning } from "@/hooks/use-failure-learning";
import { Perm } from "@/types/permissions";

import { EvalCasesPanel } from "./eval-cases-panel";
import { LedgerEntryDetail } from "./ledger-entry-detail";
import { LedgerPanel } from "./ledger-panel";
import { PatternsPanel } from "./patterns-panel";
import { ProposalsPanel } from "./proposals-panel";

/**
 * The agent's failure-learning tab: its mined patterns, its ledger, its
 * eval cases and its proposals. The rule counts up top are the
 * instruction-bloat surface: applied proposals are the rules live in the
 * instructions now, open entries the rules still being worked - a resolved
 * entry is its applied proposal, so the two are counted separately, never
 * added. Selecting a ledger entry filters the cases and proposals below
 * to that entry.
 */
export function FailureLearningTab({ agentId }: { agentId: string }) {
  const t = useTranslations("failureLearning");
  const { can } = usePermissions();
  const {
    patterns,
    patternsLoading,
    patternsError,
    entries,
    entriesLoading,
    entriesError,
    cases,
    casesLoading,
    casesError,
    proposals,
    proposalsLoading,
    proposalsError,
    track,
    updateEntry,
    removeEntry,
    createCase,
    removeCase,
    createProposal,
    apply,
    revert,
    reject,
    startTry,
  } = useFailureLearning(agentId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = entries.find((entry) => entry.id === selectedId) ?? null;
  // The try runner's proposal picker lives in the eval cases section above,
  // so a proposal's "Try this text" sets it from here.
  const [tryProposalId, setTryProposalId] = useState("none");
  const [proposalPrefill, setProposalPrefill] = useState<{
    evalTryId: string;
    newText: string;
  } | null>(null);
  const counts = ruleCounts(entries, proposals);
  const canEdit = can(Perm.agentsEdit);

  return (
    <div className="space-y-6" data-tour="agent-failure-learning">
      <section className="space-y-3">
        <h3 className="text-base font-semibold">{t("liveRules")}</h3>
        <p className="text-muted-foreground text-sm">
          {t("appliedRules", { count: counts.appliedProposals })}
          {" · "}
          {t("openEntries", { count: counts.openEntries })}
          {" · "}
          {t("resolvedEntries", { count: counts.resolvedEntries })}
        </p>
        <p className="text-muted-foreground text-sm">{t("ruleCountsHint")}</p>
      </section>
      <section className="space-y-3">
        <h3 className="text-base font-semibold">{t("patterns")}</h3>
        <p className="text-muted-foreground text-sm">{t("patternsDescription")}</p>
        <PatternsPanel
          patterns={patterns}
          isLoading={patternsLoading}
          error={patternsError}
          canTrack={canEdit}
          onTrack={(pattern, input) => track.mutate({ pattern, input })}
        />
      </section>
      <section className="space-y-3">
        <h3 className="text-base font-semibold">{t("ledger")}</h3>
        <p className="text-muted-foreground text-sm">{t("ledgerDescription")}</p>
        <LedgerPanel
          entries={entries}
          isLoading={entriesLoading}
          error={entriesError}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
        {selected && (
          <LedgerEntryDetail
            entry={selected}
            canEdit={canEdit}
            onUpdate={(entryId, input) => updateEntry.mutate({ entryId, input })}
            onDelete={(entryId) => {
              removeEntry.mutate(entryId);
              setSelectedId(null);
            }}
          />
        )}
      </section>
      <section className="space-y-3">
        <h3 className="text-base font-semibold">{t("evalCases")}</h3>
        <p className="text-muted-foreground text-sm">{t("evalCasesDescription")}</p>
        <EvalCasesPanel
          agentId={agentId}
          cases={cases}
          proposals={proposals}
          isLoading={casesLoading}
          error={casesError}
          ledgerEntryId={selectedId}
          canEdit={canEdit}
          onCreate={(input) => createCase.mutate(input)}
          onDelete={(caseId) => removeCase.mutate(caseId)}
          onStartTry={async (input) => startTry.mutateAsync(input)}
          onProposeFromTry={(tryId, newText) => setProposalPrefill({ evalTryId: tryId, newText })}
          tryProposalId={tryProposalId}
          onTryProposalChange={setTryProposalId}
        />
      </section>
      <section className="space-y-3">
        <h3 className="text-base font-semibold">{t("proposals")}</h3>
        <p className="text-muted-foreground text-sm">{t("proposalsDescription")}</p>
        <ProposalsPanel
          proposals={proposals}
          isLoading={proposalsLoading}
          error={proposalsError}
          ledgerEntryId={selectedId}
          canEdit={canEdit}
          canApplyInstructions={can(Perm.agentsPublish)}
          canApplySkill={can(Perm.skillsEdit)}
          canTry={canEdit}
          canRevert={can(Perm.skillsEdit)}
          canReject={canEdit}
          prefill={proposalPrefill}
          onCreate={(input) => createProposal.mutate(input)}
          onApply={(proposalId) => apply.mutate(proposalId)}
          onTry={(proposalId) => setTryProposalId(proposalId)}
          onRevert={(proposalId) => revert.mutate(proposalId)}
          onReject={(proposalId, reason) => reject.mutate({ proposalId, reason })}
          onPrefillConsumed={() => setProposalPrefill(null)}
        />
      </section>
    </div>
  );
}
