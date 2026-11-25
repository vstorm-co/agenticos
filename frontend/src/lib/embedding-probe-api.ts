/**
 * The Test behind every change that could move a collection's vector space.
 *
 * A probe re-embeds a few stored chunks with the values being tried and compares
 * them with the vectors already in the index. Failure is a 200 with
 * `passed: false` and a named outcome, never an error, so the dialogs can say
 * which collection failed and why. A passing result carries a short-lived token
 * bound to the exact values tested; a save sends it back and the server refuses
 * it if anything differs.
 */

import { apiClient } from "./api-client";
import type { KBScope } from "@/types";

export type EmbeddingProbeOutcome =
  | "passed"
  | "no_chunks"
  | "unreachable"
  | "key_refused"
  | "model_unknown"
  | "wrong_width"
  | "vectors_differ";

export interface EmbeddingProbeKnowledgeBase {
  knowledge_base_id: string;
  name: string;
  outcome: EmbeddingProbeOutcome;
  min_cosine: number | null;
  calls: number;
}

export interface EmbeddingProbeResult {
  passed: boolean;
  outcome: EmbeddingProbeOutcome;
  /** The width the endpoint answered with, when one was measured. */
  dim: number | null;
  calls: number;
  knowledge_bases: EmbeddingProbeKnowledgeBase[];
  probe_token: string | null;
  expires_at: string | null;
}

/** What a test would bill, said before it is run. */
export interface EmbeddingProbeEstimate {
  calls: number;
  max_calls: number;
  knowledge_bases: number;
}

/** The proposed settings of a collection change; omitted fields keep their value. */
export interface KbEmbeddingProbeBody {
  embedding_provider?: string;
  embedding_endpoint_id?: string;
  embedding_secret_id?: string;
  embedding_base_url?: string | null;
  embedding_model?: string;
}

/** Measure a new custom model's width with one call, before a collection exists. */
export async function probeNewEmbedding(body: {
  embedding_endpoint_id: string;
  embedding_model: string;
  scope: KBScope;
}): Promise<EmbeddingProbeResult> {
  return apiClient.post<EmbeddingProbeResult>("/kb/embedding-probe", body);
}

export async function estimateKbProbe(kbId: string): Promise<EmbeddingProbeEstimate> {
  return apiClient.get<EmbeddingProbeEstimate>(`/kb/${kbId}/embedding-probe/estimate`);
}

export async function probeKbEmbedding(
  kbId: string,
  body: KbEmbeddingProbeBody,
): Promise<EmbeddingProbeResult> {
  return apiClient.post<EmbeddingProbeResult>(`/kb/${kbId}/embedding-probe`, body);
}
