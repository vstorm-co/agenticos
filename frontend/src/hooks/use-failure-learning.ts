"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import {
  applyProposal,
  createEvalCase,
  createLedgerEntry,
  createProposal,
  deleteEvalCase,
  deleteLedgerEntry,
  getEvalTry,
  getProposal,
  listAgentPatterns,
  listEvalCases,
  listLedgerEntries,
  listOrgPatterns,
  listProposals,
  rejectProposal,
  revertProposal,
  startEvalTry,
  trackPattern,
  updateLedgerEntry,
  type EvalCaseCreate,
  type FailurePattern,
  type LedgerEntryCreate,
  type LedgerEntryUpdate,
  type LedgerStatus,
  type ProposalCreate,
  type ProposalStatus,
} from "@/lib/failure-learning-api";
import { qk } from "@/lib/query-keys";

/** How often a try with cases still running is read again. */
const POLL_MS = 2000;

/**
 * The org-wide mined patterns: every agent's recurring failures in the last
 * 7 days, and what the mining cannot see. Read-only; the route gate is
 * `runs:view`, so a caller without it never gets this far.
 */
export function useOrgPatterns() {
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: qk.failureLearning.orgPatterns(),
    queryFn: () => listOrgPatterns(),
  });
  // Tracking curates the pattern into its agent's ledger in place - the
  // entry is what the agent's tab then shows.
  const track = useMutation({
    mutationFn: ({
      pattern,
      input,
    }: {
      pattern: FailurePattern;
      input: { title: string; summary: string };
    }) => trackPattern(pattern, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: qk.failureLearning.orgPatterns(),
      });
      void queryClient.invalidateQueries({ queryKey: ["failure-learning", "agents"] });
    },
    onError: (err: unknown) => toast.error(getErrorMessage(err, tErrors)),
  });
  return { patterns: data?.items ?? [], notes: data?.notes ?? [], isLoading, error, track };
}

/**
 * One agent's loop: its patterns, ledger, eval cases, proposals, and the
 * try that evidences a proposal. Writing is `agents:edit`; applying is
 * `agents:publish` (or `skills:edit` for a skill target) - the components
 * hide what the caller may not use, and the server re-checks either way.
 *
 * A try's verdicts are judged when the try is read, so the try is read
 * again every couple of seconds while any case is still running.
 */
export function useFailureLearning(agentId: string) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("failureLearning");
  const queryClient = useQueryClient();
  const agentKey = ["failure-learning", "agents", agentId] as const;
  const refresh = () => void queryClient.invalidateQueries({ queryKey: agentKey });
  const fail = (error: unknown) => toast.error(getErrorMessage(error, tErrors));

  const patternsQuery = useQuery({
    queryKey: qk.failureLearning.agentPatterns(agentId),
    queryFn: () => listAgentPatterns(agentId),
  });
  const ledgerQuery = useQuery({
    queryKey: qk.failureLearning.ledger(agentId),
    queryFn: () => listLedgerEntries(agentId),
  });
  const casesQuery = useQuery({
    queryKey: qk.failureLearning.cases(agentId),
    queryFn: () => listEvalCases(agentId),
  });
  const proposalsQuery = useQuery({
    queryKey: qk.failureLearning.proposals(agentId),
    queryFn: () => listProposals(agentId),
  });

  const track = useMutation({
    mutationFn: ({
      pattern,
      input,
    }: {
      pattern: FailurePattern;
      input: { title: string; summary: string };
    }) => trackPattern(pattern, input),
    onSuccess: refresh,
    onError: fail,
  });
  const createEntry = useMutation({
    mutationFn: (input: LedgerEntryCreate) => createLedgerEntry(agentId, input),
    onSuccess: refresh,
    onError: fail,
  });
  const updateEntry = useMutation({
    mutationFn: ({ entryId, input }: { entryId: string; input: LedgerEntryUpdate }) =>
      updateLedgerEntry(agentId, entryId, input),
    onSuccess: refresh,
    onError: fail,
  });
  const removeEntry = useMutation({
    mutationFn: (entryId: string) => deleteLedgerEntry(agentId, entryId),
    onSuccess: refresh,
    onError: fail,
  });
  const createCase = useMutation({
    mutationFn: (input: EvalCaseCreate) => createEvalCase(agentId, input),
    onSuccess: refresh,
    onError: fail,
  });
  const removeCase = useMutation({
    mutationFn: (caseId: string) => deleteEvalCase(agentId, caseId),
    onSuccess: refresh,
    onError: fail,
  });
  const createProposalMutation = useMutation({
    mutationFn: (input: ProposalCreate) => createProposal(agentId, input),
    onSuccess: refresh,
    onError: fail,
  });
  const apply = useMutation({
    mutationFn: (proposalId: string) => applyProposal(agentId, proposalId),
    onSuccess: () => {
      toast.success(t("proposalApplied"));
      refresh();
    },
    onError: fail,
  });
  const revert = useMutation({
    mutationFn: (proposalId: string) => revertProposal(agentId, proposalId),
    onSuccess: () => {
      toast.success(t("proposalReverted"));
      refresh();
    },
    onError: fail,
  });
  const reject = useMutation({
    mutationFn: ({ proposalId, reason }: { proposalId: string; reason: string }) =>
      rejectProposal(agentId, proposalId, reason),
    onSuccess: refresh,
    onError: fail,
  });
  const startTry = useMutation({
    mutationFn: (input: { case_ids: string[]; proposal_id?: string | null; samples?: number }) =>
      startEvalTry(agentId, input),
    onSuccess: refresh,
    onError: fail,
  });

  return {
    patterns: patternsQuery.data?.items ?? [],
    patternNotes: patternsQuery.data?.notes ?? [],
    patternsLoading: patternsQuery.isLoading,
    patternsError: patternsQuery.error,
    entries: ledgerQuery.data?.items ?? [],
    entriesLoading: ledgerQuery.isLoading,
    entriesError: ledgerQuery.error,
    cases: casesQuery.data?.items ?? [],
    casesLoading: casesQuery.isLoading,
    casesError: casesQuery.error,
    proposals: proposalsQuery.data?.items ?? [],
    proposalsLoading: proposalsQuery.isLoading,
    proposalsError: proposalsQuery.error,
    track,
    createEntry,
    updateEntry,
    removeEntry,
    createCase,
    removeCase,
    createProposal: createProposalMutation,
    apply,
    revert,
    reject,
    startTry,
  };
}

/**
 * One try, read again while any case is still running so each verdict lands
 * by itself. The try is what a proposal's apply is judged by, so a
 * proposal review that shows a pending try shows this.
 */
export function useEvalTry(agentId: string, tryId: string | null) {
  const { data, isLoading } = useQuery({
    queryKey: qk.failureLearning.try(agentId, tryId ?? ""),
    queryFn: () => getEvalTry(agentId, tryId ?? ""),
    enabled: tryId !== null,
    refetchInterval: (query) => ((query.state.data?.pending ?? 0) > 0 ? POLL_MS : false),
  });
  return { try: data ?? null, isLoading };
}

/** One proposal, with its eval evidence and its apply record. */
export function useProposal(agentId: string, proposalId: string | null) {
  const { data, isLoading } = useQuery({
    queryKey: qk.failureLearning.proposal(agentId, proposalId ?? ""),
    queryFn: () => getProposal(agentId, proposalId ?? ""),
    enabled: proposalId !== null,
  });
  return { proposal: data ?? null, isLoading };
}

/**
 * The per-agent rule-count surface (§7.2's instruction-bloat surface):
 * open entries, resolved entries, and applied proposals, as separate
 * figures rather than one sum. A resolved entry *is* its applied proposal
 * - the entry resolves when the proposal applies - so adding the two
 * would count one rule twice. The live rules are the applied proposals;
 * the open entries are the rules still being worked.
 */
export function ruleCounts(
  entries: { status: LedgerStatus }[],
  proposals: { status: ProposalStatus }[],
): { openEntries: number; resolvedEntries: number; appliedProposals: number } {
  return {
    // Open means draft or open, the same definition the ledger uses: a
    // draft entry is a rule already being worked, not one that is done.
    openEntries: entries.filter((entry) => entry.status === "open" || entry.status === "draft")
      .length,
    resolvedEntries: entries.filter((entry) => entry.status === "resolved").length,
    appliedProposals: proposals.filter((proposal) => proposal.status === "applied").length,
  };
}
