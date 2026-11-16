import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useCallback, useState, type ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BrowserCredentialReview } from "./browser-credential-review";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { BROWSER_IDS as ids } from "@/test-utils/browser-credential-fixtures";
import {
  browserEligibilityFixture,
  browserPlanFixture,
  browserSubmissionFixture,
} from "@/test-utils/browser-credential-plan-fixtures";
import {
  browserSubmissionKey,
  retainBrowserSubmissionAttempt,
} from "@/lib/browser-credential-review";
import type { BrowserCredentialPlan } from "@/types/browser-credentials";
import type { BrowserSubmissionAttempt } from "@/lib/browser-credentials-api";
import { useBrowserCredentialPlan } from "@/hooks/use-browser-credential-plan";
import { BrowserWindow } from "@/components/chat/browser-window";
import { protectBrowse, type Browse } from "@/lib/browse";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));
const path = `/runs/${ids.run}/browser-credential-plans/${ids.plan}`;
const audience = { actor: ids.owner, organization: ids.org };
let current: BrowserCredentialPlan;
let child: BrowserCredentialPlan | null;
let eligible: unknown;
let client: QueryClient;
function setup(
  props: Partial<ComponentProps<typeof BrowserCredentialReview>> = {},
  onMutationSuccess?: () => void,
) {
  client = new QueryClient({
    mutationCache: new MutationCache({ onSuccess: onMutationSuccess }),
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <BrowserCredentialReview runId={ids.run} planId={ids.plan} {...props} />
    </QueryClientProvider>,
  );
}
async function confirmButton() {
  const button = await screen.findByRole("button", { name: "Confirm fill" });
  await waitFor(() => expect(button).toBeEnabled());
  return button;
}
async function submitButton(name = "Submit this form") {
  const button = await screen.findByRole("button", { name });
  await waitFor(() => expect(button).toBeEnabled());
  return button;
}
beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  useAuthStore.setState({ user: { id: ids.owner } as never, accessToken: "test-token" });
  useOrgStore.setState({ activeOrgId: ids.org });
  current = browserPlanFixture();
  child = null;
  eligible = [browserEligibilityFixture()];
  vi.mocked(apiClient.get).mockImplementation(async (url) => {
    if (url.endsWith("/browser-credentials")) return eligible as never;
    if (url.endsWith("/submission")) return child as never;
    return current as never;
  });
  vi.mocked(apiClient.post).mockImplementation(async (url, body) => {
    if (url.endsWith("/confirmation")) {
      if (!(body as { approve: boolean }).approve) {
        current = { ...current, state: "declined" };
        return current as never;
      }
      const confirmed = { ...current, state: "approved" as const };
      current = {
        ...current,
        state: "filled",
        output_protected: true,
        submission_expires_at: new Date(Date.now() + 60_000).toISOString(),
      };
      return confirmed as never;
    }
    child = browserSubmissionFixture(current);
    return child as never;
  });
});
afterEach(() => {
  cleanup();
  client?.clear();
  vi.restoreAllMocks();
  vi.useRealTimers();
  sessionStorage.clear();
  useAuthStore.setState({ user: null });
  useOrgStore.setState({ activeOrgId: null });
});

describe("exact saved credential consent", () => {
  it("replaces an inline raw browser with the protected receipt when its confirmation read reports protection", async () => {
    const send = vi.fn();
    function Window() {
      const [browse, setBrowse] = useState<Browse>({
        runId: ids.run,
        callId: "browser-call",
        tabId: "main",
        credentialPlanId: ids.plan,
        goal: "RAW WINDOW TASK",
        title: "RAW WINDOW TITLE",
        url: "https://accounts.example/private",
        image: "data:image/jpeg;base64,RAW",
        imageStep: 1,
        steps: [],
        maxSteps: null,
        outcome: null,
        detail: null,
      });
      const protect = useCallback(() => setBrowse(protectBrowse), []);
      return (
        <BrowserWindow browse={browse} control={{ canControl: true, send }} onProtected={protect} />
      );
    }
    client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <Window />
      </QueryClientProvider>,
    );
    expect(screen.getByRole("img")).toBeInTheDocument();
    await userEvent.click(await confirmButton());
    await screen.findByRole("heading", { name: "Protected browser" });
    await submitButton();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.queryByRole("application")).not.toBeInTheDocument();
    expect(screen.queryByText(/RAW WINDOW/)).not.toBeInTheDocument();
    expect(screen.getByText("https://accounts.example")).toBeVisible();
    expect(apiClient.post).toHaveBeenCalledTimes(1);
  });
  it("recovers a refused receipt read through Check again without issuing consent", async () => {
    vi.mocked(apiClient.get).mockRejectedValueOnce(new ApiError(403, "forbidden"));
    setup();
    await screen.findByText("This credential receipt could not be verified.");
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    await confirmButton();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("treats an unknown wire state as uncertain and an invalid deadline as unavailable", async () => {
    current.expires_at = "invalid";
    const view = setup();
    await screen.findByText("Time unavailable");
    expect(screen.getByRole("button", { name: "Confirm fill" })).toBeDisabled();
    view.unmount();
    client.clear();
    current = browserPlanFixture({ state: "future-state" as never });
    setup();
    await screen.findByText("Outcome unknown");
    expect(screen.queryByText("future-state")).not.toBeInTheDocument();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it.each(["id", "document_id", "authorization_generation"] as const)(
    "does not accept a confirmation response whose %s changed",
    async (field) => {
      vi.mocked(apiClient.post).mockResolvedValue({
        ...current,
        [field]: ids.child,
        state: "filled",
      });
      setup();
      await userEvent.click(await confirmButton());
      await screen.findByText(/confirmation result could not be verified/);
      expect(screen.queryByText("Selected fields filled")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Submit this form" })).not.toBeInTheDocument();
      expect(apiClient.post).toHaveBeenCalledTimes(1);
    },
  );

  it("admits only one fill click in a synchronous burst and does not interleave a status check", async () => {
    let finish!: (value: BrowserCredentialPlan) => void;
    vi.mocked(apiClient.post).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    setup();
    const confirm = await confirmButton();
    const check = screen.getByRole("button", { name: "Check again" });
    act(() => {
      confirm.click();
      confirm.click();
      check.click();
    });
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    current = { ...current, state: "declined" };
    await act(async () => finish(current));
    await screen.findByText("Fill declined");
  });
  it("shows the exact origin and selected field names, with no automatic confirmation or private value echo", async () => {
    eligible = [{ ...browserEligibilityFixture(), hint: "HIDDEN", password: "NEVER-RENDER" }];
    setup();
    await confirmButton();
    expect(screen.getByText("https://accounts.example")).toBeVisible();
    expect(screen.getByText("Synthetic account")).toBeVisible();
    expect(screen.getByText("Username")).toBeVisible();
    expect(screen.getByText("Password")).toBeVisible();
    expect(screen.queryByText(/HIDDEN|NEVER-RENDER/)).not.toBeInTheDocument();
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(apiClient.get).toHaveBeenCalledWith(
      `/runs/${ids.run}/browser-credentials`,
      expect.objectContaining({
        cache: "no-store",
        params: { call_id: "browser-call", tab_id: "main" },
      }),
    );
  });

  it("requires explicit fill confirmation and a second explicit Submit, each carrying only the exact receipt tuple", async () => {
    const protectedView = vi.fn();
    setup({ onProtected: protectedView });
    await userEvent.click(await confirmButton());
    const submit = await submitButton();
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    expect(apiClient.post).toHaveBeenNthCalledWith(
      1,
      path + "/confirmation",
      {
        document_id: ids.document,
        authorization_generation: ids.generation,
        approve: true,
      },
      expect.objectContaining({ retryAfterRefresh: false, cache: "no-store" }),
    );
    expect(protectedView).toHaveBeenCalled();
    await userEvent.click(submit);
    await screen.findByText("Submit action acknowledged");
    expect(apiClient.post).toHaveBeenCalledTimes(2);
    expect(apiClient.post).toHaveBeenNthCalledWith(
      2,
      path + "/submission",
      {
        request_id: expect.any(String),
        document_id: ids.document,
        authorization_generation: ids.generation,
      },
      expect.objectContaining({ retryAfterRefresh: false, cache: "no-store" }),
    );
    expect(screen.getByText(/does not establish that sign-in succeeded/)).toBeVisible();
    expect(
      vi
        .mocked(apiClient.post)
        .mock.calls.every(([url]) => !url.includes(ids.child + "/confirmation")),
    ).toBe(true);
  });

  it("declines through the dedicated route without submitting or filling", async () => {
    setup();
    await confirmButton();
    await userEvent.click(screen.getByRole("button", { name: "Decline fill" }));
    await screen.findByText("Fill declined");
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    expect(apiClient.post).toHaveBeenCalledWith(
      path + "/confirmation",
      {
        document_id: ids.document,
        authorization_generation: ids.generation,
        approve: false,
      },
      expect.any(Object),
    );
  });

  it.each(["missing", "generation", "wrapper", "denied"] as const)(
    "retains the receipt but refuses new confirmation when current eligibility is %s",
    async (scenario) => {
      if (scenario === "missing") eligible = [];
      if (scenario === "generation")
        eligible = [{ ...browserEligibilityFixture(), authorization_generation: ids.child }];
      if (scenario === "wrapper") eligible = { items: [browserEligibilityFixture()] };
      if (scenario === "denied")
        vi.mocked(apiClient.get).mockImplementation(async (url) => {
          if (url.endsWith("/browser-credentials")) throw new ApiError(403, "forbidden");
          return current as never;
        });
      setup();
      const button = await screen.findByRole("button", { name: "Confirm fill" });
      await screen.findByText(/Current credential eligibility could not be verified/);
      expect(button).toBeDisabled();
      expect(screen.getByText("https://accounts.example")).toBeVisible();
      expect(screen.queryByText("Synthetic account")).not.toBeInTheDocument();
      fireEvent.click(button);
      expect(apiClient.post).not.toHaveBeenCalled();
    },
  );

  it.each(["origin", "fields", "document", "expired"] as const)(
    "refuses an unverifiable %s confirmation boundary",
    async (boundary) => {
      if (boundary === "origin") current.origin = "https://accounts.example/private";
      if (boundary === "fields") current.fields = ["password", "unknown"] as never;
      if (boundary === "document") current.document_id = null;
      if (boundary === "expired") current.expires_at = new Date(Date.now() - 1).toISOString();
      setup();
      const button = await screen.findByRole("button", { name: "Confirm fill" });
      expect(button).toBeDisabled();
      fireEvent.click(button);
      expect(apiClient.post).not.toHaveBeenCalled();
      if (boundary === "origin")
        expect(screen.queryByRole("link", { name: "Open this site" })).not.toBeInTheDocument();
    },
  );

  it("does not display a different run's receipt or fetch eligibility for it", async () => {
    current = { ...current, run_id: ids.child, origin: "https://private.other.example" };
    setup();
    await screen.findByText("This credential receipt could not be verified.");
    expect(screen.queryByText("https://private.other.example")).not.toBeInTheDocument();
    expect(vi.mocked(apiClient.get).mock.calls).toHaveLength(1);
  });

  it("reconciles a lost confirmation acknowledgement with reads and never repeats the confirmation automatically", async () => {
    vi.mocked(apiClient.post).mockImplementation(async () => {
      current = {
        ...current,
        state: "unknown",
        output_protected: true,
        reason_code: "uncertain_fill_effect",
      };
      throw new TypeError("lost acknowledgement");
    });
    setup();
    await userEvent.click(await confirmButton());
    await screen.findByText("Outcome unknown");
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Confirm fill" })).not.toBeInTheDocument();
  });
});

describe("one recoverable separate submission", () => {
  beforeEach(() => {
    current = browserPlanFixture({
      state: "filled",
      output_protected: true,
      expires_at: new Date(Date.now() - 60_000).toISOString(),
      submission_expires_at: new Date(Date.now() + 60_000).toISOString(),
    });
  });
  it("admits one explicit Submit from a synchronous double click", async () => {
    let finish!: (value: BrowserCredentialPlan) => void;
    vi.mocked(apiClient.post).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    setup();
    const submit = await submitButton();
    act(() => {
      submit.click();
      submit.click();
    });
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    child = browserSubmissionFixture(current);
    await act(async () => finish(child!));
    await screen.findByText("Submit action acknowledged");
  });
  it("keeps the original attempt when the POST response has a different document", async () => {
    vi.mocked(apiClient.post).mockResolvedValue(
      browserSubmissionFixture(current, { document_id: ids.child }),
    );
    setup();
    await userEvent.click(await submitButton());
    await submitButton("Retry the same submission");
    expect(screen.queryByText("Submit action acknowledged")).not.toBeInTheDocument();
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    const original = vi.mocked(apiClient.post).mock.calls[0]![1];
    expect(JSON.parse(sessionStorage.getItem(browserSubmissionKey(audience, current))!)).toEqual(
      original,
    );
  });
  it("uses the independent submission window even after the old fill confirmation deadline", async () => {
    setup();
    await submitButton();
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Open this site" })).toHaveAttribute(
      "href",
      "https://accounts.example",
    );
    expect(screen.getByText(/use Stop in the chat where it is running/)).toBeVisible();
    expect(screen.getByText(/Hosted sign-in and cookies are not transferred/)).toBeVisible();
  });
  it("never submits after the separate submission deadline", async () => {
    current.submission_expires_at = new Date(Date.now() - 1).toISOString();
    setup();
    const button = await screen.findByRole("button", { name: "Submit this form" });
    await screen.findByText(/separate submission window has expired/);
    expect(button).toBeDisabled();
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it("recovers a lost response across reload and reuses the exact original request only after another click", async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce(new TypeError("lost response"));
    const view = setup();
    await userEvent.click(await submitButton());
    await submitButton("Retry the same submission");
    const first = vi.mocked(apiClient.post).mock.calls[0]![1] as BrowserSubmissionAttempt;
    expect(first.request_id).toMatch(/^[0-9a-f-]{36}$/);
    view.unmount();
    client.clear();
    setup();
    const retry = await submitButton("Retry the same submission");
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    await userEvent.click(retry);
    await screen.findByText("Submit action acknowledged");
    expect(vi.mocked(apiClient.post).mock.calls[1]![1]).toEqual(first);
  });
  it("preserves an uncertain attempt through a denied recovery read and recognizes a terminal child without a fresh retry", async () => {
    let denied = false;
    vi.mocked(apiClient.get).mockImplementation(async (url) => {
      if (url.endsWith("/browser-credentials")) return eligible as never;
      if (url.endsWith("/submission")) {
        if (denied) throw new ApiError(403, "forbidden");
        return child as never;
      }
      return current as never;
    });
    vi.mocked(apiClient.post).mockImplementation(async () => {
      denied = true;
      child = browserSubmissionFixture(current, {
        state: "unknown",
        reason_code: "uncertain_fill_effect",
      });
      throw new TypeError("lost response");
    });
    const view = setup();
    await userEvent.click(await submitButton());
    await screen.findByText(/Check the existing submission before/);
    const attempt = vi.mocked(apiClient.post).mock.calls[0]![1];
    view.unmount();
    client.clear();
    setup();
    const retry = await screen.findByRole("button", { name: "Retry the same submission" });
    expect(retry).toBeDisabled();
    denied = false;
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    await screen.findByText("Outcome unknown");
    expect(
      screen.queryByRole("button", { name: "Retry the same submission" }),
    ).not.toBeInTheDocument();
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    expect(JSON.parse(sessionStorage.getItem(browserSubmissionKey(audience, current))!)).toEqual(
      attempt,
    );
  });
  it.each(["refused", "unknown", "expired", "submitted"] as const)(
    "treats an existing %s child as consuming the single submission slot",
    async (status) => {
      child = browserSubmissionFixture(current, { state: status });
      setup();
      await screen.findByText(/already has its one submission attempt/);
      expect(screen.queryByRole("button", { name: "Submit this form" })).not.toBeInTheDocument();
      expect(apiClient.post).not.toHaveBeenCalled();
    },
  );
  it("refuses a foreign child receipt rather than using it to clear an uncertain request", async () => {
    child = browserSubmissionFixture(current, { parent_plan_id: ids.child });
    setup();
    await screen.findByText(/current receipt could not be verified/);
    expect(screen.getByRole("button", { name: "Submit this form" })).toBeDisabled();
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it("does not send when the browser cannot persist the first attempt", async () => {
    setup();
    const button = await submitButton();
    vi.spyOn(sessionStorage, "setItem").mockImplementation(() => {
      throw new Error("blocked storage");
    });
    await userEvent.click(button);
    await screen.findByText(/recoverable submission request could not be preserved/);
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it("does not mint a different token when a stored attempt already exists", async () => {
    const original = retainBrowserSubmissionAttempt(
      browserSubmissionKey(audience, current),
      current,
    );
    setup();
    await userEvent.click(await submitButton("Retry the same submission"));
    await screen.findByText("Submit action acknowledged");
    expect(vi.mocked(apiClient.post).mock.calls[0]![1]).toEqual(original);
  });
});

describe("private and bounded receipt reads", () => {
  it("does not perform even a manual read without a signed-in audience", async () => {
    useAuthStore.setState({ user: null });
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useBrowserCredentialPlan(ids.run, ids.plan), {
      wrapper: ({ children }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    });
    expect(await result.current.refresh()).toBeUndefined();
    expect(apiClient.get).not.toHaveBeenCalled();
  });
  it.each(["fill", "submit"] as const)(
    "does not publish a %s receipt if the audience changes after acknowledgement before local cache updates",
    async (operation) => {
      if (operation === "submit")
        current = browserPlanFixture({
          state: "filled",
          output_protected: true,
          submission_expires_at: new Date(Date.now() + 60_000).toISOString(),
        });
      setup({}, () => {
        vi.mocked(apiClient.get).mockRejectedValue(new ApiError(403, "forbidden"));
        useOrgStore.setState({ activeOrgId: ids.child });
      });
      await userEvent.click(operation === "fill" ? await confirmButton() : await submitButton());
      await screen.findByText("This credential receipt could not be verified.");
      expect(screen.queryByText("Selected fields filled")).not.toBeInTheDocument();
      expect(screen.queryByText("Submit action acknowledged")).not.toBeInTheDocument();
      expect(apiClient.post).toHaveBeenCalledTimes(1);
    },
  );
  it.each(["account", "organization"] as const)(
    "drops a late confirmation response after an %s change",
    async (scope) => {
      let resolve!: (value: BrowserCredentialPlan) => void;
      vi.mocked(apiClient.post).mockImplementation(
        () =>
          new Promise((done) => {
            resolve = done;
          }),
      );
      setup();
      await userEvent.click(await confirmButton());
      vi.mocked(apiClient.get).mockRejectedValue(new ApiError(403, "forbidden"));
      act(() => {
        if (scope === "account") useAuthStore.setState({ user: { id: ids.child } as never });
        else useOrgStore.setState({ activeOrgId: ids.child });
      });
      await screen.findByText("This credential receipt could not be verified.");
      await act(async () => resolve({ ...current, state: "filled", output_protected: true }));
      expect(screen.queryByText("Synthetic account")).not.toBeInTheDocument();
      expect(screen.queryByText("Selected fields filled")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Submit this form" })).not.toBeInTheDocument();
    },
  );
  it.each(["preparing", "filled"] as const)(
    "bounds %s polling to three minutes and restarts only reads on Check again",
    async (status) => {
      vi.useFakeTimers();
      current =
        status === "preparing"
          ? browserPlanFixture({ state: "preparing", document_id: null, origin: null })
          : browserPlanFixture({
              state: "filled",
              output_protected: true,
              submission_expires_at: new Date(Date.now() + 60_000).toISOString(),
            });
      setup();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1);
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(180_001);
      });
      expect(screen.getByText(/Automatic status checks have stopped/)).toBeVisible();
      const reads = vi.mocked(apiClient.get).mock.calls.length;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(apiClient.get).toHaveBeenCalledTimes(reads);
      fireEvent.click(screen.getByRole("button", { name: "Check again" }));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1);
      });
      expect(vi.mocked(apiClient.get).mock.calls.length).toBeGreaterThan(reads);
      expect(apiClient.post).not.toHaveBeenCalled();
    },
  );
});
