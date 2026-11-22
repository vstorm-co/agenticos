/** A browser-local navigation hint; it never holds drafts, authority or completion. */
const STEPS = new Set([
  ...[
    "workspace",
    "identity",
    "profile",
    "context",
    "subscriptions",
    "team",
    "deployment",
    "organization",
    "task",
  ].map((step) => `admin.${step}`),
  ...["welcome", "profile", "context", "subscriptions", "task"].map((step) => `member.${step}`),
]);
const QUESTIONS: Record<string, readonly string[]> = {
  "admin.deployment": ["access", "destination", "announcement", "extras"],
  "admin.organization": ["budget", "advanced"],
};
export function startLocationKey(userId: string, organizationId: string): string {
  return JSON.stringify([userId, organizationId]);
}

/** Only the existing wizard's own scoped URL vocabulary may become a return link. */
export function safeStartLocation(href: string | undefined, organizationId: string): string | null {
  if (!href || !href.startsWith("/") || href.startsWith("//") || href.includes("\\")) return null;
  const url = new URL(href, "https://onboarding.invalid");
  if (url.pathname !== "/onboarding" || url.hash) return null;
  const step = url.searchParams.get("start-step");
  if (!step || !STEPS.has(step) || url.searchParams.get("workspace") !== organizationId)
    return null;
  const keys = [...url.searchParams.keys()];
  if (
    new Set(keys).size !== keys.length ||
    keys.some((key) => !["start-step", "workspace", "question"].includes(key))
  )
    return null;
  const question = url.searchParams.get("question");
  if (question !== null && !QUESTIONS[step]?.includes(question)) return null;
  return `/onboarding?${url.searchParams.toString()}`;
}
