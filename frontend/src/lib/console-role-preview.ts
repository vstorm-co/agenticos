import type { CatalogPolicy } from "./console-experience-api";

/** Preview restrictions without fetching connected accounts or installed private skills. */
export function previewCatalogPolicies(policies: readonly (CatalogPolicy | null | undefined)[]): {
  approvedLimit: number | null;
  availableOnly: boolean;
} {
  let approved: Set<string> | null = null;
  for (const policy of policies) {
    if (policy?.mode !== "allow-list") continue;
    approved = new Set(policy.keys.filter((key) => approved === null || approved.has(key)));
  }
  return {
    approvedLimit: approved?.size ?? null,
    availableOnly: policies.some((policy) => policy?.mode === "available"),
  };
}
