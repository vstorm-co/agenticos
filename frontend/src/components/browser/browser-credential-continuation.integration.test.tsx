import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BrowserCredentialContinuationPanel } from "./browser-credential-continuation";
import { BrowserCredentialReview } from "./browser-credential-review";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import {
  browserContinuationAttemptKey,
  readBrowserContinuationAttempt,
  retainBrowserContinuationAttempt,
} from "@/lib/browser-credential-continuation-attempts";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import {
  CONTINUATION_IDS as ids,
  browserContinuationFixture,
  continuationSourceFixture,
} from "@/test-utils/browser-credential-continuation-fixtures";
import { browserPlanFixture } from "@/test-utils/browser-credential-plan-fixtures";
import type {
  BrowserCredentialContinuation,
  BrowserContinuationConfirmation,
} from "@/types/browser-credential-continuation";
import type { BrowserCredentialPlan } from "@/types/browser-credentials";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));
const audience = { actor: ids.owner, organization: ids.org };
const source = continuationSourceFixture();
const path = `/runs/${ids.run}/browser-credential-plans/${ids.child}/continuation`;
const clients: QueryClient[] = [];
let current: BrowserCredentialContinuation | null;
function wrapper(onSuccess?: () => void) {
  const client = new QueryClient({
    mutationCache: new MutationCache({ onSuccess }),
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  return {
    client,
    Wrap: ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  };
}
function setup(
  props: { source?: BrowserCredentialPlan; sourceCurrent?: boolean } = {},
  onSuccess?: () => void,
) {
  const { client, Wrap } = wrapper(onSuccess);
  return {
    client,
    ...render(
      <BrowserCredentialContinuationPanel
        source={props.source ?? source}
        sourceCurrent={props.sourceCurrent ?? true}
      />,
      { wrapper: Wrap },
    ),
  };
}
async function button(name: string) {
  const found = await screen.findByRole("button", { name });
  await waitFor(() => expect(found).toBeEnabled());
  return found;
}
beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  useAuthStore.setState({ user: { id: ids.owner } as never, accessToken: "test-token" });
  useOrgStore.setState({ activeOrgId: ids.org });
  current = null;
  vi.mocked(apiClient.get).mockImplementation(async () => current as never);
  vi.mocked(apiClient.post).mockImplementation(async (url, body) => {
    if (url.endsWith("/confirmation")) {
      const decision = body as BrowserContinuationConfirmation;
      current = browserContinuationFixture({
        state: decision.approve ? "approved" : "declined",
        keep_signed_in: decision.keep_signed_in,
      });
    } else
      current = browserContinuationFixture({
        id: (body as { request_id: string }).request_id,
        state: "requested",
        origin: null,
        document_id: null,
      });
    return current as never;
  });
});
afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  vi.restoreAllMocks();
  vi.useRealTimers();
  sessionStorage.clear();
  useAuthStore.setState({ user: null });
  useOrgStore.setState({ activeOrgId: null });
});

describe("protected continuation consent", () => {
  it("reads before preparation and retains one request without authorizing cookie use", async () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue(ids.continuation);
    setup();
    await button("Prepare continuation");
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(screen.getByText(/does not export cookies/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Prepare continuation" }));
    await screen.findByText("Preparation requested");
    expect(apiClient.post).toHaveBeenCalledWith(
      path,
      { request_id: ids.continuation },
      expect.objectContaining({ retryAfterRefresh: false }),
    );
    expect(
      readBrowserContinuationAttempt(browserContinuationAttemptKey(audience, source), "prepare")
        .attempt,
    ).toEqual({ kind: "prepare", request_id: ids.continuation });
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(apiClient.post).toHaveBeenCalledTimes(1);
  });
  it("prepares only from a known acknowledged submit and a current source read", async () => {
    const ui = setup({ source: browserPlanFixture() });
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
    expect(apiClient.get).not.toHaveBeenCalled();
    ui.rerender(
      <BrowserCredentialContinuationPanel source={{ ...source, state: "unknown" }} sourceCurrent />,
    );
    expect(apiClient.get).not.toHaveBeenCalled();
    ui.rerender(<BrowserCredentialContinuationPanel source={source} sourceCurrent={false} />);
    await screen.findByText(/current continuation receipt could not be verified/);
    expect(screen.getByRole("button", { name: "Check continuation" })).toBeDisabled();
    expect(apiClient.get).not.toHaveBeenCalled();
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it("shows the exact origin and a separate unchecked seven-day choice", async () => {
    current = browserContinuationFixture();
    setup();
    await button("Continue in protected browser");
    expect(screen.getByText(source.origin!)).toBeVisible();
    expect(screen.getByRole("checkbox", { name: /Keep me signed in/ })).not.toBeChecked();
    expect(screen.getByText(/up to seven days/)).toBeVisible();
    expect(screen.getByText(/No local storage, page text or form values/)).toBeVisible();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(apiClient.post).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Continue in protected browser" }));
    await screen.findByText("Decision recorded");
    expect(apiClient.post).toHaveBeenCalledWith(
      `${path}/${ids.continuation}/confirmation`,
      {
        document_id: ids.continuationDocument,
        authorization_generation: ids.generation,
        approve: true,
        keep_signed_in: false,
      },
      expect.objectContaining({ retryAfterRefresh: false }),
    );
  });
  it("saves only an explicitly checked choice and links to a protected view, without claiming authentication", async () => {
    current = browserContinuationFixture();
    vi.mocked(apiClient.post).mockImplementation(async (_url, body) => {
      current = browserContinuationFixture({
        state: "continued",
        keep_signed_in: true,
        saved_sign_in_id: ids.saved,
        continuation_call_id: ids.continuationCall,
        continuation_tab_id: ids.continuationTab,
      });
      expect((body as BrowserContinuationConfirmation).keep_signed_in).toBe(true);
      return current as never;
    });
    setup();
    await button("Continue in protected browser");
    await userEvent.click(screen.getByRole("checkbox", { name: /Keep me signed in/ }));
    await userEvent.click(screen.getByRole("button", { name: "Continue in protected browser" }));
    await screen.findByText("Protected continuation established");
    expect(screen.getByText(/does not prove that sign-in succeeded/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Open protected view" })).toHaveAttribute(
      "href",
      expect.stringContaining(`/browse/${ids.run}/${ids.continuationCall}`),
    );
    expect(screen.getByRole("link", { name: "Open protected view" })).toHaveAttribute(
      "target",
      "_blank",
    );
    expect(screen.getByRole("link", { name: "Manage saved sign-ins" })).toHaveAttribute(
      "href",
      expect.stringContaining("/settings/sign-ins"),
    );
    expect(screen.getByText(/Both browser views remain protected/)).toBeVisible();
  });
  it("uses cookies only for this continuation when saving was not authorized", async () => {
    current = browserContinuationFixture({
      state: "continued",
      keep_signed_in: false,
      continuation_call_id: ids.continuationCall,
      continuation_tab_id: ids.continuationTab,
    });
    setup();
    await screen.findByText("Protected continuation established");
    expect(screen.getByText(/No reusable sign-in was saved/)).toBeVisible();
    expect(screen.queryByRole("link", { name: "Manage saved sign-ins" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Retry/ })).not.toBeInTheDocument();
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it("declines without saving even if the unchecked default was changed beforehand", async () => {
    current = browserContinuationFixture();
    setup();
    await button("Decline continuation");
    await userEvent.click(screen.getByRole("checkbox", { name: /Keep me signed in/ }));
    await userEvent.click(screen.getByRole("button", { name: "Decline continuation" }));
    await screen.findByText("Continuation declined");
    expect(apiClient.post).toHaveBeenCalledWith(
      expect.stringContaining("/confirmation"),
      expect.objectContaining({ approve: false, keep_signed_in: false }),
      expect.anything(),
    );
  });
  it("never retries a terminal unknown effect, including after read-only checks", async () => {
    current = browserContinuationFixture({
      state: "unknown",
      reason_code: "uncertain_continuation",
    });
    setup();
    await screen.findByText("Continuation outcome unknown");
    expect(screen.getByText(/cannot be repeated/)).toBeVisible();
    await userEvent.click(await button("Check continuation"));
    expect(screen.queryAllByRole("button")).toHaveLength(1);
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it.each(["refused", "expired", "declined"] as const)(
    "offers only a read for terminal %s",
    async (state) => {
      current = browserContinuationFixture({ state, reason_code: "authority_changed" });
      setup();
      await screen.findByText("Access to a contributing credential changed.");
      expect(screen.queryAllByRole("button")).toHaveLength(1);
      expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
      expect(apiClient.post).not.toHaveBeenCalled();
    },
  );
});

describe("recoverable continuation decisions", () => {
  it.each(["continuation_id", "document_id", "authorization_generation"] as const)(
    "refuses a retained decision for another %s without replacing it",
    async (field) => {
      current = browserContinuationFixture();
      const key = browserContinuationAttemptKey(audience, source, current);
      const retained = {
        kind: "confirm" as const,
        continuation_id: ids.continuation,
        document_id: ids.continuationDocument,
        authorization_generation: ids.generation,
        approve: true,
        keep_signed_in: false,
        [field]: ids.other,
      };
      expect(retainBrowserContinuationAttempt(key, retained)).toBe(true);
      const original = sessionStorage.getItem(key);
      setup();
      await screen.findByText("Waiting for your continuation decision");
      expect(screen.queryAllByRole("button", { name: "Retry the same decision" }).length).toBe(0);
      expect(screen.getByRole("button", { name: "Continue in protected browser" })).toBeDisabled();
      expect(screen.getByText(/cannot preserve a recoverable decision/)).toBeVisible();
      expect(sessionStorage.getItem(key)).toBe(original);
      expect(apiClient.post).not.toHaveBeenCalled();
    },
  );
  it("keeps the original preparation ID through a lost acknowledgement, reload and null recovery", async () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue(ids.continuation);
    vi.mocked(apiClient.post).mockRejectedValue(new TypeError("private transport detail"));
    const ui = setup();
    await userEvent.click(await button("Prepare continuation"));
    await screen.findByText(/response could not be verified/);
    expect(screen.queryByText("private transport detail")).not.toBeInTheDocument();
    ui.unmount();
    setup();
    await button("Retry the same preparation");
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Retry the same preparation" }));
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(2));
    expect(vi.mocked(apiClient.post).mock.calls.map((call) => call[1])).toEqual([
      { request_id: ids.continuation },
      { request_id: ids.continuation },
    ]);
    expect(crypto.randomUUID).toHaveBeenCalledTimes(1);
  });
  it("restores the exact cookie decision after an uncertain response and retries only on a separate click", async () => {
    current = browserContinuationFixture();
    vi.mocked(apiClient.post).mockRejectedValue(new ApiError(503, "private"));
    const ui = setup();
    await button("Continue in protected browser");
    await userEvent.click(screen.getByRole("checkbox", { name: /Keep me signed in/ }));
    await userEvent.click(screen.getByRole("button", { name: "Continue in protected browser" }));
    await screen.findByText(/response could not be verified/);
    ui.unmount();
    setup();
    await button("Retry the same decision");
    expect(screen.getByRole("checkbox", { name: /Keep me signed in/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Keep me signed in/ })).toBeDisabled();
    await userEvent.click(await button("Check continuation"));
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    await userEvent.click(await button("Retry the same decision"));
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(2));
    expect(vi.mocked(apiClient.post).mock.calls[1]?.[1]).toEqual(
      vi.mocked(apiClient.post).mock.calls[0]?.[1],
    );
  });
  it("cannot turn a retained decline into consent", async () => {
    current = browserContinuationFixture();
    const key = browserContinuationAttemptKey(audience, source, current);
    retainBrowserContinuationAttempt(key, {
      kind: "confirm",
      continuation_id: current.id,
      document_id: ids.continuationDocument,
      authorization_generation: ids.generation,
      approve: false,
      keep_signed_in: false,
    });
    setup();
    await button("Retry the same decision");
    expect(screen.getByText(/original Decline decision/)).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Continue in protected browser" }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry the same decision" }));
    await screen.findByText("Continuation declined");
    expect(apiClient.post).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ approve: false, keep_signed_in: false }),
      expect.anything(),
    );
  });
  it.each([false, true])(
    "refuses a write if recoverable storage fails (confirmation=%s)",
    async (confirmation) => {
      current = confirmation ? browserContinuationFixture() : null;
      vi.spyOn(sessionStorage, "setItem").mockImplementation(() => {
        throw new Error("unavailable");
      });
      setup();
      await userEvent.click(
        await button(confirmation ? "Continue in protected browser" : "Prepare continuation"),
      );
      await screen.findByText(/cannot preserve a recoverable decision/);
      expect(apiClient.post).not.toHaveBeenCalled();
    },
  );
  it.each([false, true])(
    "refuses malformed retained storage rather than minting another choice (confirmation=%s)",
    async (confirmation) => {
      current = confirmation ? browserContinuationFixture() : null;
      sessionStorage.setItem(
        browserContinuationAttemptKey(audience, source, current ?? undefined),
        "not-json",
      );
      setup();
      await screen.findByText(/cannot preserve a recoverable decision/);
      expect(
        screen.getByRole("button", {
          name: confirmation ? "Continue in protected browser" : "Prepare continuation",
        }),
      ).toBeDisabled();
      expect(apiClient.post).not.toHaveBeenCalled();
    },
  );
  it("does not overwrite another unresolved decision that appears before this click", async () => {
    current = browserContinuationFixture();
    setup();
    await button("Continue in protected browser");
    retainBrowserContinuationAttempt(browserContinuationAttemptKey(audience, source, current), {
      kind: "confirm",
      continuation_id: current.id,
      document_id: ids.continuationDocument,
      authorization_generation: ids.generation,
      approve: false,
      keep_signed_in: false,
    });
    await userEvent.click(screen.getByRole("button", { name: "Continue in protected browser" }));
    await screen.findByText(/cannot preserve a recoverable decision/);
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it.each([false, true])(
    "deduplicates immediate clicks before React renders pending state (confirmation=%s)",
    async (confirmation) => {
      current = confirmation ? browserContinuationFixture() : null;
      vi.spyOn(crypto, "randomUUID").mockReturnValue(ids.continuation);
      let finish!: (value: unknown) => void;
      vi.mocked(apiClient.post).mockImplementation(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }) as never,
      );
      setup();
      const approve = await button(
        confirmation ? "Continue in protected browser" : "Prepare continuation",
      );
      fireEvent.click(approve);
      fireEvent.click(approve);
      await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
      await act(async () =>
        finish(
          confirmation
            ? browserContinuationFixture({ state: "approved", keep_signed_in: false })
            : browserContinuationFixture({ state: "requested", origin: null, document_id: null }),
        ),
      );
      await screen.findByText(confirmation ? "Decision recorded" : "Preparation requested");
      if (!confirmation) {
        expect(crypto.randomUUID).toHaveBeenCalledTimes(1);
        expect(
          readBrowserContinuationAttempt(browserContinuationAttemptKey(audience, source), "prepare")
            .attempt,
        ).toEqual({ kind: "prepare", request_id: ids.continuation });
      }
    },
  );
});

describe("current authority and bounded recovery", () => {
  it.each([401, 403, 404])(
    "hides old consent and private receipt details after a fresh %s refusal",
    async (status) => {
      current = browserContinuationFixture();
      setup();
      await button("Continue in protected browser");
      vi.mocked(apiClient.get).mockRejectedValue(new ApiError(status, "provider detail"));
      await userEvent.click(await button("Check continuation"));
      await screen.findByText(/current continuation receipt could not be verified/);
      expect(screen.queryByText(source.origin!)).not.toBeInTheDocument();
      expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
      expect(screen.queryByText("provider detail")).not.toBeInTheDocument();
      expect(apiClient.post).not.toHaveBeenCalled();
      vi.mocked(apiClient.get).mockResolvedValue(current as never);
      await userEvent.click(await button("Check continuation"));
      await button("Continue in protected browser");
      expect(apiClient.post).not.toHaveBeenCalled();
    },
  );
  it("does not display a receipt for another owner or its derived link", async () => {
    current = browserContinuationFixture({ user_id: ids.other });
    setup();
    await screen.findByText(/current continuation receipt could not be verified/);
    expect(screen.queryByText(source.origin!)).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it.each(["actor", "organization"] as const)(
    "does not publish a late write after %s changes",
    async (field) => {
      current = browserContinuationFixture();
      setup({}, () => {
        if (field === "actor") useAuthStore.setState({ user: { id: ids.other } as never });
        else useOrgStore.setState({ activeOrgId: ids.other });
      });
      await userEvent.click(await button("Continue in protected browser"));
      await screen.findByText(/current continuation receipt could not be verified/);
      expect(screen.queryByText("Decision recorded")).not.toBeInTheDocument();
      expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
      expect(apiClient.post).toHaveBeenCalledTimes(1);
    },
  );
  it("keeps expiry advancing after automatic reads end, and status checks cannot revive an expired document", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    current = browserContinuationFixture({
      expires_at: new Date(Date.now() + 240_000).toISOString(),
    });
    setup();
    await button("Continue in protected browser");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(181_000);
    });
    expect(screen.getByText(/Automatic status checks have stopped/)).toBeVisible();
    const reads = vi.mocked(apiClient.get).mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(61_000);
    });
    expect(apiClient.get).toHaveBeenCalledTimes(reads);
    expect(screen.getByText(/confirmation window has expired/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Continue in protected browser" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Check continuation" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(screen.getByRole("button", { name: "Continue in protected browser" })).toBeDisabled();
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it("mounts the continuation from the real exact-plan review's acknowledged submit child", async () => {
    const parent = browserPlanFixture({ state: "filled", output_protected: true });
    vi.mocked(apiClient.get).mockImplementation(async (url) => {
      if (url.endsWith("/continuation")) return null as never;
      if (url.endsWith("/submission")) return source as never;
      if (url.endsWith("/browser-credentials")) return [] as never;
      return parent as never;
    });
    const { Wrap } = wrapper();
    render(<BrowserCredentialReview runId={ids.run} planId={ids.plan} />, { wrapper: Wrap });
    await button("Prepare continuation");
    expect(apiClient.get).toHaveBeenCalledWith(path, expect.anything());
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});
