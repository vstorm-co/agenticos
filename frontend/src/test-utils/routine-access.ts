import type { RoutineAccessReview } from "@/lib/routine-access-api";

/** A current access review with nothing to choose, for tests that only pass through it. */
export function routineAccessFixture(
  overrides: Partial<RoutineAccessReview> = {},
): RoutineAccessReview {
  return {
    mode: "reviewed",
    grandfathered: false,
    current: true,
    review_reason: null,
    review_token: "access",
    version_id: "v1",
    sources: [],
    unavailable_sources: [],
    required_unavailable_sources: [],
    tools: [],
    unlisted_accounts: [],
    has_delegates: false,
    delegates: "ask",
    can_allow: true,
    allow_blocked_reason: null,
    can_trust: false,
    trust_blocked_reason: "organization",
    ...overrides,
  };
}
