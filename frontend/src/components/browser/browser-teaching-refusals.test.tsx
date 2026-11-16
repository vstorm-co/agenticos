import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import {
  readTeachingAttempt,
  retainTeachingAttempt,
  teachingAttemptKey,
  type TeachingDraftAttempt,
  type TeachingStartAttempt,
} from "@/lib/browser-teaching-attempts";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import {
  TEACHING_IDS as ids,
  teachingBrowseFixture,
  teachingFixture,
  teachingReviewFixture,
} from "@/test-utils/browser-teaching";
import type { BrowserTeaching, TeachingStart } from "@/types/browser-teaching";
import { BrowserTeachingStart } from "./browser-teaching-start";
import { BrowserTeachingControls } from "./browser-teaching-controls";
import { BrowserTeachingReview } from "./browser-teaching-review";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => true, isLoading: false }),
}));
vi.mock("@/components/dashboard/page-header", () => ({
  PageHeader: ({
    title,
    description,
    secondaryActions,
  }: {
    title: string;
    description: string;
    secondaryActions: ReactNode;
  }) => (
    <header>
      <h1>{title}</h1>
      <p>{description}</p>
      {secondaryActions}
    </header>
  ),
}));

const audience = { actor: ids.owner, organization: ids.org };
const startKey = teachingAttemptKey(audience, "start", [ids.run, "teaching-call", "main"]);
const draftKey = teachingAttemptKey(audience, "propose", [ids.session]);
const startAttempt = (): TeachingStartAttempt => ({
  kind: "start",
  targetSkillId: null,
  body: {
    request_id: ids.session,
    run_id: ids.run,
    call_id: "teaching-call",
    tab_id: "main",
    takeover_id: ids.takeover,
    title: "Retained synthetic demonstration",
    allowed_origins: ["https://reports.example"],
  },
});
const draftAttempt = (): TeachingDraftAttempt => ({
  kind: "propose",
  revision: 2,
  body: { mode: "assistant", max_cost_usd: "1.250000" },
});
const refusal = (status: number) =>
  new ApiError(status, "PRIVATE REFUSAL TEXT", {
    error: {
      code: "BAD_REQUEST",
      message: "PRIVATE REFUSAL TEXT",
      details: { reason_code: "authority_changed" },
    },
  });
let client: QueryClient;
let current: BrowserTeaching;
let readRefusal: ApiError | null;
function setup(node: ReactNode) {
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}
function mountStart(onStarted = vi.fn()) {
  setup(<BrowserTeachingStart browse={teachingBrowseFixture()} canStart onStarted={onStarted} />);
  return onStarted;
}
async function readyStart() {
  const input = await screen.findByLabelText("Demonstration title");
  fireEvent.change(input, { target: { value: "New synthetic demonstration" } });
  const button = screen.getByRole("button", { name: "Start recording" });
  await waitFor(() => expect(button).toBeEnabled());
  return button;
}
async function readyDraft() {
  setup(<BrowserTeachingReview sessionId={ids.session} />);
  const button = await screen.findByRole("button", { name: "Create draft from reviewed steps" });
  await waitFor(() => expect(button).toBeEnabled());
  return button;
}
async function readyConsent(kind: "Start" | "Draft") {
  if (kind === "Start") {
    mountStart();
    return readyStart();
  }
  return readyDraft();
}
function acceptedStart(body: TeachingStart): BrowserTeaching {
  return teachingFixture({
    id: body.request_id,
    run_id: body.run_id,
    call_id: body.call_id,
    tab_id: body.tab_id,
    title: body.title,
    allowed_origins: body.allowed_origins,
    status: "recording",
    revision: 1,
  });
}
beforeEach(() => {
  vi.resetAllMocks();
  sessionStorage.clear();
  useAuthStore.setState({
    user: { id: ids.owner } as NonNullable<ReturnType<typeof useAuthStore.getState>["user"]>,
    accessToken: "synthetic-test-token",
  });
  useOrgStore.setState({ activeOrgId: ids.org });
  current = teachingFixture({ review: teachingReviewFixture() });
  readRefusal = null;
  vi.mocked(apiClient.get).mockImplementation(async (path) => {
    if (path === "/browser-teaching-policy")
      return { enabled: true, generation: ids.other, deployment_enabled: true } as never;
    if (path.endsWith("/browser-teaching-preference"))
      return { agent_id: ids.agent, enabled: false, generation: null, allowed: true } as never;
    if (path.startsWith("/runs/")) return { id: ids.run, agent_id: ids.agent } as never;
    if (path === "/skills") return { items: [], total: 0 } as never;
    if (readRefusal) throw readRefusal;
    return current as never;
  });
  vi.mocked(apiClient.post).mockRejectedValue(new Error("Unexpected consent write"));
});
afterEach(() => {
  cleanup();
  client?.clear();
  vi.restoreAllMocks();
  sessionStorage.clear();
});

describe("teaching consent requires safe attempt retention", () => {
  it.each(["Start", "Draft"] as const)("does not send %s when persistence fails", async (kind) => {
    const button = await readyConsent(kind);
    vi.spyOn(sessionStorage, "setItem").mockImplementation(() => {
      throw new Error("Storage unavailable");
    });
    await userEvent.click(button);
    await screen.findByRole("alert");
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", {
        name: kind === "Start" ? "Start recording" : "Create draft from reviewed steps",
      }),
    ).toBeNull();
  });

  it.each(["Start", "Draft"] as const)(
    "does not send %s when an existing record cannot be read",
    async (kind) => {
      vi.spyOn(sessionStorage, "getItem").mockImplementation(() => {
        throw new Error("Storage unavailable");
      });
      if (kind === "Start") mountStart();
      else setup(<BrowserTeachingReview sessionId={ids.session} />);
      await screen.findByRole("alert");
      expect(apiClient.post).not.toHaveBeenCalled();
      expect(screen.queryByRole("button", { name: /Retry the same/ })).toBeNull();
    },
  );

  it.each([400, 401, 403, 404, 409, 422])(
    "allows correction after a first definite Start refusal %s",
    async (status) => {
      vi.mocked(apiClient.post).mockRejectedValue(refusal(status));
      mountStart();
      await userEvent.click(await readyStart());
      await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
      await waitFor(() => expect(readTeachingAttempt(startKey, "start").attempt).toBeNull());
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Start recording" })).toBeEnabled(),
      );
      expect(screen.queryByText("PRIVATE REFUSAL TEXT")).toBeNull();
    },
  );

  it.each([400, 401, 403, 404, 409, 422])(
    "clears only the first refused Draft tuple for HTTP %s",
    async (status) => {
      vi.mocked(apiClient.post).mockRejectedValue(refusal(status));
      await userEvent.click(await readyDraft());
      await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
      await waitFor(() => expect(readTeachingAttempt(draftKey, "propose").attempt).toBeNull());
      expect(screen.queryByText("PRIVATE REFUSAL TEXT")).toBeNull();
      expect(apiClient.post).toHaveBeenCalledTimes(1);
    },
  );

  it.each(["Start", "Draft"] as const)(
    "retains an uncertain %s after a server failure",
    async (kind) => {
      vi.mocked(apiClient.post).mockRejectedValue(refusal(500));
      const button = await readyConsent(kind);
      await userEvent.click(button);
      await screen.findByRole("button", {
        name: kind === "Start" ? "Retry the same Start request" : "Retry the same Draft request",
      });
      expect(
        readTeachingAttempt(
          kind === "Start" ? startKey : draftKey,
          kind === "Start" ? "start" : "propose",
        ).attempt,
      ).not.toBeNull();
      expect(apiClient.post).toHaveBeenCalledTimes(1);
      expect(screen.queryByText("PRIVATE REFUSAL TEXT")).toBeNull();
    },
  );
});

describe("previously uncertain teaching attempts survive later refusals", () => {
  it("requires a fresh saved review before drafting again after generation refusal", async () => {
    current = teachingFixture({
      review: teachingReviewFixture(),
      generation_state: "refused",
      reason_code: "generation_failed",
    });
    vi.mocked(apiClient.patch).mockImplementation(async () => {
      current = { ...current, revision: 3, generation_state: "none", reason_code: null };
      return current as never;
    });
    setup(<BrowserTeachingReview sessionId={ids.session} />);
    await screen.findByRole("button", { name: "Save reviewed steps" });
    expect(
      screen.queryAllByRole("button", { name: "Create draft from reviewed steps" }),
    ).toHaveLength(0);
    expect(
      screen.queryAllByRole("button", { name: "Create draft with the authoring assistant" }),
    ).toHaveLength(0);
    expect(apiClient.post).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Save reviewed steps" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Create draft from reviewed steps" }),
      ).toBeEnabled(),
    );
    expect(apiClient.patch).toHaveBeenCalledExactlyOnceWith(
      "/browser-teachings/" + ids.session,
      { action: "review", review: teachingReviewFixture() },
      expect.objectContaining({
        headers: { "X-Organization-Id": ids.org, "If-Match": '"2"' },
        retryAfterRefresh: false,
      }),
    );
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("hides retained review metadata for the exact membership refusal without clearing uncertainty", async () => {
    const saved = draftAttempt();
    expect(retainTeachingAttempt(draftKey, saved)).toBe(true);
    setup(<BrowserTeachingReview sessionId={ids.session} />);
    await screen.findByRole("button", { name: "Retry the same Draft request" });
    readRefusal = new ApiError(400, "PRIVATE MEMBERSHIP TEXT", {
      error: {
        code: "BAD_REQUEST",
        message: "PRIVATE MEMBERSHIP TEXT",
        details: { reason_code: "teaching_unavailable" },
      },
    });
    await userEvent.click(screen.getAllByRole("button", { name: "Check again" })[0]!);
    await screen.findByText(/unavailable to the current person/);
    expect(screen.queryByText(current.title)).toBeNull();
    expect(screen.queryByText("PRIVATE MEMBERSHIP TEXT")).toBeNull();
    expect(readTeachingAttempt(draftKey, "propose").attempt).toEqual(saved);
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("keeps the original Start after a refused explicit retry and GET-only Check again", async () => {
    const saved = startAttempt();
    expect(retainTeachingAttempt(startKey, saved)).toBe(true);
    const raw = sessionStorage.getItem(startKey);
    const started = mountStart();
    const retry = await screen.findByRole("button", { name: "Retry the same Start request" });
    vi.mocked(apiClient.post).mockRejectedValue(refusal(403));
    await userEvent.click(retry);
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(retry).toBeEnabled());
    readRefusal = refusal(404);
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith(
        "/browser-teachings/" + saved.body.request_id,
        expect.anything(),
      ),
    );
    expect(apiClient.post).toHaveBeenCalledExactlyOnceWith(
      "/browser-teachings",
      saved.body,
      expect.objectContaining({ retryAfterRefresh: false }),
    );
    expect(sessionStorage.getItem(startKey)).toBe(raw);
    expect(started).not.toHaveBeenCalled();
    expect(screen.queryByText("PRIVATE REFUSAL TEXT")).toBeNull();
  });

  it("keeps the original Draft revision and budget through write/read refusal", async () => {
    const saved = draftAttempt();
    expect(retainTeachingAttempt(draftKey, saved)).toBe(true);
    const raw = sessionStorage.getItem(draftKey);
    setup(<BrowserTeachingReview sessionId={ids.session} />);
    const retry = await screen.findByRole("button", { name: "Retry the same Draft request" });
    vi.mocked(apiClient.post).mockImplementation(async () => {
      readRefusal = refusal(404);
      throw refusal(403);
    });
    await userEvent.click(retry);
    await screen.findByText(/unavailable to the current person/);
    expect(apiClient.post).toHaveBeenCalledExactlyOnceWith(
      "/browser-teachings/" + ids.session + "/propose",
      saved.body,
      expect.objectContaining({
        headers: { "X-Organization-Id": ids.org, "If-Match": '"2"' },
        retryAfterRefresh: false,
      }),
    );
    const reads = vi.mocked(apiClient.get).mock.calls.length;
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    await waitFor(() => expect(vi.mocked(apiClient.get).mock.calls.length).toBeGreaterThan(reads));
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem(draftKey)).toBe(raw);
    expect(screen.queryByText(current.title)).toBeNull();
  });

  it.each(["id", "run_id", "call_id", "tab_id", "target_skill_id"] as const)(
    "does not settle Start recovery with mismatched %s",
    async (field) => {
      const saved = startAttempt();
      expect(retainTeachingAttempt(startKey, saved)).toBe(true);
      current = { ...acceptedStart(saved.body), [field]: ids.other };
      const started = mountStart();
      await userEvent.click(await screen.findByRole("button", { name: "Check again" }));
      await screen.findByRole("alert");
      expect(started).not.toHaveBeenCalled();
      expect(readTeachingAttempt(startKey, "start").attempt).toEqual(saved);
      expect(apiClient.post).not.toHaveBeenCalled();
    },
  );

  it.each(["id", "run_id", "call_id", "tab_id", "agent_id", "target_skill_id"] as const)(
    "does not settle a Draft POST with mismatched %s",
    async (field) => {
      vi.mocked(apiClient.post).mockResolvedValue({
        ...current,
        [field]: ids.other,
        generation_state: "queued",
        revision: 3,
      });
      await userEvent.click(await readyDraft());
      await screen.findByRole("button", { name: "Retry the same Draft request" });
      expect(readTeachingAttempt(draftKey, "propose").attempt).toEqual({
        kind: "propose",
        revision: 2,
        body: { mode: "reviewed" },
      });
      expect(screen.queryByText("Draft queued")).toBeNull();
      expect(apiClient.post).toHaveBeenCalledTimes(1);
    },
  );

  it("hides malformed per-ID recovery data without replacing a saved Draft", async () => {
    const saved = draftAttempt();
    expect(retainTeachingAttempt(draftKey, saved)).toBe(true);
    current = teachingFixture({ id: ids.other, title: "Wrong capture must stay hidden" });
    setup(<BrowserTeachingReview sessionId={ids.session} />);
    await screen.findByText(/unavailable to the current person/);
    expect(screen.queryByText(current.title)).toBeNull();
    expect(readTeachingAttempt(draftKey, "propose").attempt).toEqual(saved);
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});

describe("teaching consent races stay with their original audience", () => {
  it("sends one Start for two immediate clicks and preserves its one request ID", async () => {
    let resolve!: (value: BrowserTeaching) => void;
    vi.mocked(apiClient.post).mockReturnValue(
      new Promise<BrowserTeaching>((done) => {
        resolve = done;
      }),
    );
    const started = mountStart();
    const button = await readyStart();
    act(() => {
      fireEvent.click(button);
      fireEvent.click(button);
    });
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    const body = vi.mocked(apiClient.post).mock.calls[0]![1] as TeachingStart;
    expect(readTeachingAttempt<TeachingStartAttempt>(startKey, "start").attempt?.body).toEqual(
      body,
    );
    await act(async () => {
      resolve(acceptedStart(body));
    });
    await waitFor(() => expect(started).toHaveBeenCalledTimes(1));
    expect(readTeachingAttempt(startKey, "start").attempt).toBeNull();
  });

  it("sends one Draft for two immediate clicks at the reviewed revision", async () => {
    let resolve!: (value: BrowserTeaching) => void;
    vi.mocked(apiClient.post).mockReturnValue(
      new Promise<BrowserTeaching>((done) => {
        resolve = done;
      }),
    );
    const button = await readyDraft();
    act(() => {
      fireEvent.click(button);
      fireEvent.click(button);
    });
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    current = { ...current, generation_state: "queued", generation_mode: "reviewed", revision: 3 };
    await act(async () => {
      resolve(current);
    });
    await screen.findByText("Draft queued");
    expect(readTeachingAttempt(draftKey, "propose").attempt).toBeNull();
  });

  it.each(["actor", "organization"] as const)(
    "does not let a late Start reopen controls after %s remount",
    async (scope) => {
      let resolve!: (value: BrowserTeaching) => void;
      vi.mocked(apiClient.post).mockReturnValue(
        new Promise<BrowserTeaching>((done) => {
          resolve = done;
        }),
      );
      setup(<BrowserTeachingControls browse={teachingBrowseFixture()} canControl />);
      await userEvent.click(screen.getByRole("button", { name: "Teach a browser procedure" }));
      await userEvent.click(await readyStart());
      await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
      const body = vi.mocked(apiClient.post).mock.calls[0]![1] as TeachingStart;
      const raw = sessionStorage.getItem(startKey);
      act(() => {
        if (scope === "actor")
          useAuthStore.setState({
            user: { id: ids.other } as NonNullable<
              ReturnType<typeof useAuthStore.getState>["user"]
            >,
          });
        else useOrgStore.setState({ activeOrgId: ids.other });
      });
      await act(async () => {
        resolve(acceptedStart(body));
      });
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(screen.queryByRole("button", { name: "Pause recording" })).toBeNull();
      await userEvent.click(screen.getByRole("button", { name: "Teach a browser procedure" }));
      expect(await screen.findByLabelText("Demonstration title")).toHaveValue("");
      expect(screen.queryByRole("button", { name: "Retry the same Start request" })).toBeNull();
      expect(sessionStorage.getItem(startKey)).toBe(raw);
      expect(
        client.getQueryData(
          qk.browserTeaching.detail(
            scope === "actor" ? ids.other : ids.owner,
            scope === "organization" ? ids.other : ids.org,
            body.request_id,
          ),
        ),
      ).toBeUndefined();
    },
  );

  it.each(["actor", "organization"] as const)(
    "does not revive a Draft after %s remount and denied read",
    async (scope) => {
      let resolve!: (value: BrowserTeaching) => void;
      vi.mocked(apiClient.post).mockReturnValue(
        new Promise<BrowserTeaching>((done) => {
          resolve = done;
        }),
      );
      await userEvent.click(await readyDraft());
      await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
      const raw = sessionStorage.getItem(draftKey);
      readRefusal = refusal(403);
      act(() => {
        if (scope === "actor")
          useAuthStore.setState({
            user: { id: ids.other } as NonNullable<
              ReturnType<typeof useAuthStore.getState>["user"]
            >,
          });
        else useOrgStore.setState({ activeOrgId: ids.other });
      });
      await screen.findByText(/unavailable to the current person/);
      await act(async () => {
        resolve({ ...current, generation_state: "queued", revision: 3 });
      });
      expect(screen.queryByText(current.title)).toBeNull();
      expect(screen.queryByText("Draft queued")).toBeNull();
      expect(sessionStorage.getItem(draftKey)).toBe(raw);
      expect(apiClient.post).toHaveBeenCalledTimes(1);
      expect(screen.queryByText("PRIVATE REFUSAL TEXT")).toBeNull();
    },
  );
});
