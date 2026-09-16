/**
 * API client for an organization's data-retention policy.
 *
 * Three answers rather than one number per class, because a page showing only
 * what sweeps cannot explain why the period it displays is not the period
 * somebody typed: a deployment-wide ceiling cuts a longer one, and the audit
 * floor raises a shorter one (#1420).
 */

import { apiClient } from "./api-client";

/** What a period can be set on, in the order the page shows them. */
export const RETENTION_CLASSES = [
  "conversations",
  "runs",
  "workspaces",
  "memory",
  "knowledge_documents",
  "audit",
] as const;

export type RetentionClass = (typeof RETENTION_CLASSES)[number];

/** Days per class. A class absent means nothing has been said about it; `null` means for ever. */
export type RetentionDays = Partial<Record<RetentionClass, number | null>>;

export interface RetentionPolicy {
  /** What this organization set. */
  requested: RetentionDays;
  /** What actually sweeps, after the deployment's defaults, ceiling and floor. */
  effective: RetentionDays;
  /** The deployment's per-class maximum. A class absent has none. */
  ceilings: RetentionDays;
  /** The shortest an audit entry may live here. An organization may only lengthen it. */
  audit_floor_days: number;
  /** Classes whose deployment settings contradict each other, for the operator. */
  conflicts: RetentionClass[];
}

const path = (orgId: string) => `/orgs/${orgId}/retention`;

export async function getRetention(orgId: string): Promise<RetentionPolicy> {
  return apiClient.get<RetentionPolicy>(path(orgId));
}

export async function putRetention(
  orgId: string,
  retention_days: RetentionDays,
): Promise<RetentionPolicy> {
  return apiClient.put<RetentionPolicy>(path(orgId), { retention_days });
}
