import type { StartRead, StartScope, StartScopeState, StartStep } from "@/lib/onboarding-api";

export const ORGANIZATION_STEPS = [
  "workspace",
  "identity",
  "models",
  "tools",
  "team",
  "organization",
] as const;
export type OrganizationStartStep = (typeof ORGANIZATION_STEPS)[number];
const PERSONAL_STEPS = [
  "preferences.language",
  "preferences.appearance",
  "member.welcome",
  "member.profile",
  "member.context",
  "member.subscriptions",
  "member.models",
  "member.tools",
  "member.task",
] as const;

/** Scope comes from a known navigation step, never from a URL's claimed authority. */
export function scopeForStartStep(step: string | null): StartScope | null {
  if (step === "admin.deployment") return "deployment";
  if (ORGANIZATION_STEPS.some((item) => step === `admin.${item}`)) return "organization";
  if (personalStartStep(step)) return "personal";
  return null;
}

export function pendingSharedStart(data: StartRead): boolean {
  return (
    data.scopes?.some(
      (scope) => scope.applicable && !scope.completed && scope.scope !== "personal",
    ) ?? false
  );
}

/** A personal completion never conceals newly introduced shared setup stages. */
export function startIsComplete(data: StartRead): boolean {
  return data.scopes
    ? data.scopes.filter((scope) => scope.applicable).every((scope) => scope.completed)
    : data.completed;
}

export function availableStartScopes(data: StartRead): StartScopeState[] {
  return data.scopes?.filter((scope) => scope.applicable) ?? [];
}

/** Earlier stages remain reviewable; unfinished predecessors block later stages. */
export function canReviewStartScope(
  scopes: readonly StartScopeState[],
  target: StartScope,
): boolean {
  const index = scopes.findIndex((scope) => scope.scope === target);
  return index >= 0 && scopes.slice(0, index).every((scope) => scope.completed);
}

export function personalStartStep(value: string | null | undefined): StartStep | null {
  const known = PERSONAL_STEPS.find((step) => step === value);
  if (known) return known;
  const legacy = {
    "admin.profile": "member.profile",
    "admin.context": "member.context",
    "admin.subscriptions": "member.subscriptions",
    "admin.task": "member.task",
  } as const;
  return Object.entries(legacy).find(([step]) => step === value)?.[1] ?? null;
}
