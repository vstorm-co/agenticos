import { describe, expect, it } from "vitest";
import type { Onboarding, StartScopeState } from "@/lib/onboarding-api";
import {
  availableStartScopes,
  canReviewStartScope,
  pendingSharedStart,
  personalStartStep,
  scopeForStartStep,
  startIsComplete,
} from "./scopes";
const scopes: StartScopeState[] = ["deployment", "organization", "personal"].map((scope) => ({
  scope:
    scope === "deployment" ? "deployment" : scope === "organization" ? "organization" : "personal",
  applicable: true,
  completed: false,
  completed_at: null,
  current_step: null,
  updated_at: null,
}));
const data: Onboarding = {
  organization_id: "org",
  organization_name: "Acme",
  goal: null,
  dismissed: true,
  completed: true,
  snoozed_until: null,
  can_prepare: false,
  can_configure_model: false,
  support_email: null,
  agents: [],
  setup_agent: null,
  latest_conversation_id: null,
  latest_completed_at: null,
  has_result: true,
  has_activity: true,
};
it("keeps shared setup unfinished for an existing, completed and snoozed person", () => {
  const state = { ...data, scopes };
  expect(pendingSharedStart(state)).toBe(true);
  expect(startIsComplete(state)).toBe(false);
  expect(startIsComplete(data)).toBe(true);
  expect(startIsComplete({ ...data, completed: false })).toBe(false);
  expect(pendingSharedStart(data)).toBe(false);
  expect(availableStartScopes(data)).toEqual([]);
  expect(
    startIsComplete({ ...state, scopes: scopes.map((scope) => ({ ...scope, completed: true })) }),
  ).toBe(true);
});
it("never presents an inapplicable stage as a required predecessor", () => {
  const state = {
    ...data,
    scopes: scopes.map((scope) => ({ ...scope, applicable: scope.scope === "personal" })),
  };
  expect(availableStartScopes(state).map((scope) => scope.scope)).toEqual(["personal"]);
  expect(pendingSharedStart(state)).toBe(false);
  expect(canReviewStartScope(availableStartScopes(state), "personal")).toBe(true);
  expect(canReviewStartScope(availableStartScopes(state), "deployment")).toBe(false);
  expect(canReviewStartScope(scopes, "deployment")).toBe(true);
  expect(canReviewStartScope(scopes, "organization")).toBe(false);
  expect(
    canReviewStartScope(
      scopes.map((scope) => ({ ...scope, completed: scope.scope !== "personal" })),
      "personal",
    ),
  ).toBe(true);
});
describe("known routes only", () => {
  it.each(["workspace", "identity", "models", "tools", "team", "organization"])(
    "assigns admin.%s to shared organization setup",
    (step) => expect(scopeForStartStep(`admin.${step}`)).toBe("organization"),
  );
  it("assigns deployment and preserves legacy personal resumes", () => {
    expect(scopeForStartStep("admin.deployment")).toBe("deployment");
    for (const step of ["profile", "context", "subscriptions", "task"]) {
      expect(personalStartStep(`admin.${step}`)).toBe(`member.${step}`);
      expect(scopeForStartStep(`admin.${step}`)).toBe("personal");
    }
    for (const step of [
      "preferences.language",
      "preferences.appearance",
      "member.welcome",
      "member.models",
      "member.tools",
    ]) {
      expect(scopeForStartStep(step)).toBe("personal");
      expect(personalStartStep(step)).toBe(step);
    }
    expect(scopeForStartStep("member.arbitrary")).toBeNull();
    expect(scopeForStartStep(null)).toBeNull();
    expect(personalStartStep(undefined)).toBeNull();
    expect(personalStartStep("admin.deployment")).toBeNull();
  });
});
