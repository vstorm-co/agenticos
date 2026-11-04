"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import {
  createStepEval,
  deleteStepEval,
  listStepEvals,
  tryStepEvals,
} from "@/lib/workflows/evals-api";
import type { EvalCaseCreate } from "@/lib/workflows/types";

/** How often a try with cases still running is read again. */
const POLL_MS = 2000;

/**
 * A model step's eval cases and its latest try, with writing a case, removing
 * one and trying them all. The list is read again every couple of seconds while
 * the latest try has cases still running, so each one's verdict lands by itself.
 */
export function useStepEvals(workflowId: string, nodeId: string) {
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const key = qk.workflows.evals(workflowId, nodeId);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: key });
  const fail = (error: unknown) => toast.error(getErrorMessage(error, tErrors));

  const { data, isLoading } = useQuery({
    queryKey: key,
    queryFn: () => listStepEvals(workflowId, nodeId),
    refetchInterval: (query) => ((query.state.data?.latest?.pending ?? 0) > 0 ? POLL_MS : false),
  });
  const create = useMutation({
    mutationFn: (input: EvalCaseCreate) => createStepEval(workflowId, nodeId, input),
    onSuccess: refresh,
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: (evalId: string) => deleteStepEval(workflowId, evalId),
    onSuccess: refresh,
    onError: fail,
  });
  const run = useMutation({
    mutationFn: () => tryStepEvals(workflowId, nodeId),
    onSuccess: refresh,
    onError: fail,
  });
  return { cases: data?.items ?? [], latest: data?.latest ?? null, isLoading, create, remove, run };
}
