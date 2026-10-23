import { beforeEach, describe, expect, it } from "vitest";

import { useAuthStore } from "@/stores";
import type { User } from "@/types";

import { adoptAccountContext, contextSavedBy } from "./account-context";

const ADA: User = {
  id: "u-1",
  email: "ada@example.com",
  is_active: true,
  created_at: "2026-10-21T00:00:00Z",
  job_title: null,
  about: null,
};

beforeEach(() => useAuthStore.setState({ user: ADA }));

describe("contextSavedBy", () => {
  it("reads the role and work the platform's own tool saved", () => {
    const saved = '{"job_title": "Head of sales", "about": "Runs the EMEA pipeline"}';

    expect(contextSavedBy("agenticos_set_my_profile", saved)).toEqual({
      job_title: "Head of sales",
      about: "Runs the EMEA pipeline",
    });
  });

  it("reads a field the account holds no value for as empty", () => {
    expect(
      contextSavedBy("agenticos_set_my_profile", '{"job_title": "CFO", "about": null}'),
    ).toEqual({ job_title: "CFO", about: null });
  });

  it("trusts no other server's tool of the same name", () => {
    const saved = '{"job_title": "CFO", "about": "Money"}';

    expect(contextSavedBy("notion_set_my_profile", saved)).toBeNull();
    expect(contextSavedBy("set_my_profile", saved)).toBeNull();
  });

  it("reads nothing from a refusal or an answer of another shape", () => {
    expect(contextSavedBy("agenticos_set_my_profile", "403 FORBIDDEN: no")).toBeNull();
    expect(contextSavedBy("agenticos_set_my_profile", "null")).toBeNull();
    expect(contextSavedBy("agenticos_set_my_profile", '{"job_title": "CFO"}')).toBeNull();
  });
});

describe("adoptAccountContext", () => {
  it("records what was saved on the signed-in account", () => {
    adoptAccountContext({ job_title: "CFO", about: "Money" });

    expect(useAuthStore.getState().user).toMatchObject({ job_title: "CFO", about: "Money" });
  });

  it("does nothing once nobody is signed in", () => {
    useAuthStore.setState({ user: null });

    adoptAccountContext({ job_title: "CFO", about: null });

    expect(useAuthStore.getState().user).toBeNull();
  });
});
