import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import {
  preferredOrg,
  serverFallbackOrg,
  useOrganizationList,
  useOrganizations,
  useTenantId,
} from "./use-organizations";
import { apiClient } from "@/lib/api-client";
import { useOrgStore } from "@/stores";
import type { Organization } from "@/types";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function org(overrides: Partial<Organization> = {}): Organization {
  return {
    id: "org-1",
    name: "Acme",
    slug: "acme",
    is_personal: false,
    avatar_url: null,
    speech_to_text_provider: null,
    speech_to_text_model: null,
    speech_to_text_language: null,
    dictation_max_seconds: 300,
    created_at: "2026-07-01T00:00:00Z",
    ...overrides,
  } as Organization;
}

function serve(orgs: Organization[]) {
  vi.mocked(apiClient.get).mockResolvedValue({ items: orgs, total: orgs.length });
}

async function hook(orgs: Organization[] = [org()]) {
  serve(orgs);
  const rendered = renderHook(() => useOrganizations(), { wrapper });
  await waitFor(() => expect(rendered.result.current.orgs).toHaveLength(orgs.length));
  return rendered.result;
}

beforeEach(() => {
  vi.clearAllMocks();
  useOrgStore.setState({ activeOrgId: null, refusedOrgIds: [] });
});

/**
 * Which organizations exist, and which one the screen is showing.
 *
 * `preferredOrg` is the whole of the selection policy and it is pure, which is
 * deliberate: "pick a default" and "recover from a refused organization" both
 * read it, and two implementations of that rule is how the two start handing the
 * selection back and forth forever.
 *
 * The mutations split into two shapes on purpose. `createOrg` and
 * `setMonthlyBudget` let a refusal through, because the server's account of it -
 * a name too short, a cap below what the month has spent - is something a form
 * can put beside a field. The others toast and swallow.
 */
describe("preferredOrg", () => {
  it("prefers the caller's personal organization", () => {
    expect(preferredOrg([org({ id: "a" }), org({ id: "b", is_personal: true })])?.id).toBe("b");
  });

  it("prefers the deployment's default organization over a personal one (#2156)", () => {
    expect(
      preferredOrg([org({ id: "a", is_personal: true }), org({ id: "b", is_default: true })])?.id,
    ).toBe("b");
  });

  it("takes the first one when none is personal", () => {
    expect(preferredOrg([org({ id: "a" }), org({ id: "b" })])?.id).toBe("a");
  });

  it("picks nothing out of an empty list", () => {
    // Which leaves the header off and lets the server fall back.
    expect(preferredOrg([])).toBeNull();
  });

  it("never picks an organization the server has refused this session", () => {
    // Selecting one back undoes the recovery that has just moved off it.
    expect(preferredOrg([org({ id: "a", is_personal: true }), org({ id: "b" })], ["a"])?.id).toBe(
      "b",
    );
    expect(preferredOrg([org({ id: "a" })], ["a"])).toBeNull();
  });
});

describe("serverFallbackOrg", () => {
  // Where the backend acts for a request with no organization header - the same
  // order as `OrganizationService.fallback_for` (#2156).
  it("is the default organization, then the personal one", () => {
    const personal = org({ id: "p", is_personal: true });
    expect(serverFallbackOrg([personal, org({ id: "d", is_default: true })])?.id).toBe("d");
    expect(serverFallbackOrg([org({ id: "a" }), personal])?.id).toBe("p");
  });

  it("is the only organization when there is one, and nothing when there is a choice", () => {
    expect(serverFallbackOrg([org({ id: "a" })])?.id).toBe("a");
    expect(serverFallbackOrg([org({ id: "a" }), org({ id: "b" })])).toBeNull();
    expect(serverFallbackOrg([])).toBeNull();
  });
});

describe("useTenantId", () => {
  it("is the selection when there is one", () => {
    useOrgStore.setState({ activeOrgId: "chosen" });
    serve([org({ id: "d", is_default: true })]);

    const { result } = renderHook(() => useTenantId(), { wrapper });

    expect(result.current).toBe("chosen");
  });

  it("is where the server falls back to while nothing is selected", async () => {
    useOrgStore.setState({ activeOrgId: null });
    serve([org({ id: "p", is_personal: true }), org({ id: "d", is_default: true })]);

    const { result } = renderHook(() => useTenantId(), { wrapper });

    await waitFor(() => expect(result.current).toBe("d"));
  });

  it("cannot tell before the list arrives", () => {
    useOrgStore.setState({ activeOrgId: null });
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useTenantId(), { wrapper });

    expect(result.current).toBeNull();
  });
});

describe("useOrganizationList", () => {
  it("reads the list on the route that survives a refused selection", async () => {
    // `/orgs` is keyed on the caller rather than on the org header, which is what
    // makes it usable for recovery.
    serve([org()]);

    const { result } = renderHook(() => useOrganizationList(), { wrapper });

    await waitFor(() => expect(result.current.data).toHaveLength(1));
    expect(apiClient.get).toHaveBeenCalledWith("/orgs");
  });
});

describe("useOrganizations", () => {
  it("selects a default once the list arrives", async () => {
    await hook([org({ id: "org-2" }), org({ id: "org-personal", is_personal: true })]);

    await waitFor(() => expect(useOrgStore.getState().activeOrgId).toBe("org-personal"));
  });

  it("leaves an existing selection alone", async () => {
    useOrgStore.setState({ activeOrgId: "org-2" });

    await hook([org({ id: "org-2" }), org({ id: "org-personal", is_personal: true })]);

    expect(useOrgStore.getState().activeOrgId).toBe("org-2");
  });

  it("selects nothing when every organization has been refused", async () => {
    useOrgStore.setState({ refusedOrgIds: ["org-1"] });

    await hook();

    expect(useOrgStore.getState().activeOrgId).toBeNull();
  });

  it("resolves the active organization to the row, not just the id", async () => {
    useOrgStore.setState({ activeOrgId: "org-1" });

    const result = await hook();

    expect(result.current.activeOrg?.name).toBe("Acme");
  });

  it("has no active organization when the selection is not in the list", async () => {
    // Which is what a refused or deleted organization looks like on a reload.
    useOrgStore.setState({ activeOrgId: "org-gone" });

    const result = await hook();

    expect(result.current.activeOrg).toBeNull();
  });

  it("adds a created organization to the list without refetching it", async () => {
    const result = await hook();
    vi.mocked(apiClient.post).mockResolvedValue(org({ id: "org-2", name: "Beta" }));

    const created = await result.current.createOrg({ name: "Beta" });

    expect(created.id).toBe("org-2");
    await waitFor(() => expect(result.current.orgs.map((o) => o.id)).toEqual(["org-1", "org-2"]));
    expect(toast.success).toHaveBeenCalledWith("Organization created");
  });

  it("lets a refused creation through, because the form has a field to blame", async () => {
    // This used to toast "Failed to create organization" and discard what the
    // server said was wrong.
    const result = await hook();
    vi.mocked(apiClient.post).mockRejectedValue(new Error("Slug already in use"));

    await expect(result.current.createOrg({ name: "Acme" })).rejects.toThrow("Slug already in use");
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("patches a renamed organization into the list", async () => {
    const result = await hook();
    vi.mocked(apiClient.patch).mockResolvedValue(org({ name: "Acme Inc" }));

    await result.current.patchOrg("org-1", { name: "Acme Inc" });

    await waitFor(() => expect(result.current.orgs[0]?.name).toBe("Acme Inc"));
    expect(apiClient.patch).toHaveBeenCalledWith("/orgs/org-1", { name: "Acme Inc" });
  });

  it("reports a refused rename rather than raising it", async () => {
    const result = await hook();
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("nope"));

    await expect(result.current.patchOrg("org-1", { name: "x" })).resolves.toBeNull();
    expect(toast.error).toHaveBeenCalledWith("Failed to update organization");
  });

  it("always sends the cap, including as the null that lifts it", async () => {
    // Omitting the field is how every other update leaves the cap alone, so an
    // omitted field cannot also mean "remove the limit".
    const result = await hook();
    vi.mocked(apiClient.patch).mockResolvedValue(org());

    await result.current.setMonthlyBudget("org-1", null);

    expect(apiClient.patch).toHaveBeenCalledWith("/orgs/org-1", { monthly_budget_usd: null });
  });

  it("lets a refused cap through, for the same reason creation does", async () => {
    // "That is below what this month has already spent" is a sentence worth
    // putting beside the field.
    const result = await hook();
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("Below month-to-date spend"));

    await expect(result.current.setMonthlyBudget("org-1", 5)).rejects.toThrow(
      "Below month-to-date spend",
    );
  });

  it("keeps the new cap in the list it just wrote", async () => {
    const result = await hook();
    vi.mocked(apiClient.patch).mockResolvedValue(org({ name: "Capped" }));

    await result.current.setMonthlyBudget("org-1", 100);

    await waitFor(() => expect(result.current.orgs[0]?.name).toBe("Capped"));
  });

  it("saves the proactivity settings as named and keeps the answer in the list (#2301)", async () => {
    // Zero is a value - a limit of nothing - not an omitted field.
    const result = await hook();
    vi.mocked(apiClient.patch).mockResolvedValue(org({ name: "Quiet" }));

    await result.current.setProactivity("org-1", {
      proactive_enabled: true,
      proactive_model_profile_id: "mp-1",
      proactive_limit_usd: 0,
    });

    expect(apiClient.patch).toHaveBeenCalledWith("/orgs/org-1", {
      proactive_enabled: true,
      proactive_model_profile_id: "mp-1",
      proactive_limit_usd: 0,
    });
    await waitFor(() => expect(result.current.orgs[0]?.name).toBe("Quiet"));
  });

  it("saves the welcome message, where null is the built-in greeting (#2301)", async () => {
    const result = await hook();
    vi.mocked(apiClient.patch).mockResolvedValue(org({ name: "Greeting" }));

    await result.current.setWelcomeDm("org-1", { welcome_dm_enabled: true, welcome_dm_text: null });

    expect(apiClient.patch).toHaveBeenCalledWith("/orgs/org-1", {
      welcome_dm_enabled: true,
      welcome_dm_text: null,
    });
    await waitFor(() => expect(result.current.orgs[0]?.name).toBe("Greeting"));
  });

  it("sends the approval waiver as the boolean it is", async () => {
    // A boolean somebody deliberately set to false is not an omitted field, and
    // the ceiling on standing consent is exactly the setting where the two must
    // not be confused (#925).
    const result = await hook();
    vi.mocked(apiClient.patch).mockResolvedValue(org());

    await result.current.setChatApprovalWaiver("org-1", true);

    expect(apiClient.patch).toHaveBeenCalledWith("/orgs/org-1", {
      chat_may_waive_approvals: true,
    });
  });

  it("lets a refused waiver through, so the switch can say why", async () => {
    const result = await hook();
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("Needs approvals:decide"));

    await expect(result.current.setChatApprovalWaiver("org-1", true)).rejects.toThrow(
      "Needs approvals:decide",
    );
  });

  it("keeps the answered waiver in the list it just wrote", async () => {
    const result = await hook();
    vi.mocked(apiClient.patch).mockResolvedValue(org({ chat_may_waive_approvals: true }));

    await result.current.setChatApprovalWaiver("org-1", true);

    await waitFor(() => expect(result.current.orgs[0]?.chat_may_waive_approvals).toBe(true));
  });

  it("sends the voice settings in one PATCH and caches the answer", async () => {
    // One request, because the server validates them together: a provider
    // without its model is refused whole.
    const settings = {
      speech_to_text_provider: "openai",
      speech_to_text_model: "gpt-4o-transcribe",
      speech_to_text_language: null,
      dictation_max_seconds: 120,
    };
    const result = await hook();
    vi.mocked(apiClient.patch).mockResolvedValue(org(settings));

    await act(() => result.current.setVoiceSettings("org-1", settings));

    expect(apiClient.patch).toHaveBeenCalledWith("/orgs/org-1", settings);
    await waitFor(() =>
      expect(result.current.orgs[0]?.speech_to_text_model).toBe("gpt-4o-transcribe"),
    );
  });

  it("drops a deleted organization and clears the selection if it was the one", async () => {
    useOrgStore.setState({ activeOrgId: "org-1" });
    const result = await hook();
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);

    await result.current.deleteOrg("org-1");

    await waitFor(() => expect(result.current.orgs).toEqual([]));
    expect(useOrgStore.getState().activeOrgId).toBeNull();
  });

  it("keeps the selection when a different organization is deleted", async () => {
    useOrgStore.setState({ activeOrgId: "org-1" });
    const result = await hook([org(), org({ id: "org-2" })]);
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);

    await result.current.deleteOrg("org-2");

    expect(useOrgStore.getState().activeOrgId).toBe("org-1");
  });

  it("reports a refused deletion", async () => {
    const result = await hook();
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("nope"));

    await result.current.deleteOrg("org-1");

    expect(toast.error).toHaveBeenCalledWith("Failed to delete organization");
    expect(result.current.orgs).toHaveLength(1);
  });

  it("switches the selection", async () => {
    const result = await hook([org(), org({ id: "org-2" })]);

    result.current.switchOrg("org-2");

    expect(useOrgStore.getState().activeOrgId).toBe("org-2");
  });

  it("refetches the list on demand, whatever the caller passes", async () => {
    // The `force` argument is kept for call-site compatibility; invalidation
    // always refetches.
    const result = await hook();

    await result.current.fetchOrgs(true);

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
  });
});
