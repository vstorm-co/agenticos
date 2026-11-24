import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import {
  BROWSER_PROCEDURE_TEACHING_IDS as ids,
  browserProcedureTeachingBrowseFixture,
  browserProcedureTeachingFixture,
  browserProcedureTeachingReviewFixture,
  browserProcedureTeachingSummaryFixture,
} from "@/test-utils/browser-procedure-teaching";
import { Perm } from "@/types/permissions";
import type {
  BrowserProcedureTeaching,
  BrowserProcedureTeachingChange,
  BrowserProcedureTeachingPropose,
  BrowserProcedureTeachingStart,
} from "@/types/browser-procedure-teaching";
import { BrowserTeachingReview } from "./browser-teaching-review";
import { BrowserTeachingControls } from "./browser-teaching-controls";
import { BrowserTeachingList } from "./browser-teaching-list";
import { BrowserTeachingPolicy } from "./browser-teaching-policy";
import { BrowserTeachingPreference } from "./browser-teaching-preference";
import TeachingListPage from "@/app/[locale]/(dashboard)/skills/teaching/page";
import TeachingReviewPage from "@/app/[locale]/(dashboard)/skills/teaching/[sessionId]/page";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
const permission = vi.hoisted(() => ({ denied: new Set<string>() }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (name: string) => !permission.denied.has(name), isLoading: false }),
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
let client: QueryClient;
let current: BrowserProcedureTeaching;
let policy: { enabled: boolean; generation: string | null; deployment_enabled: boolean };
let preference: { agent_id: string; enabled: boolean; generation: string | null; allowed: boolean };
function setup(element: ReactNode) {
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{element}</QueryClientProvider>);
}
function reviewPage() {
  return setup(<BrowserTeachingReview sessionId={ids.session} />);
}
function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
async function readyDraft() {
  const button = await screen.findByRole("button", { name: "Create draft from reviewed steps" });
  await waitFor(() => expect(button).toBeEnabled());
  return button;
}
beforeEach(() => {
  vi.clearAllMocks();
  permission.denied.clear();
  sessionStorage.clear();
  useAuthStore.setState({ user: { id: ids.owner } as never, accessToken: "test" });
  useOrgStore.setState({ activeOrgId: ids.org });
  current = browserProcedureTeachingFixture();
  policy = { enabled: true, generation: ids.other, deployment_enabled: true };
  preference = { agent_id: ids.agent, enabled: false, generation: null, allowed: true };
  vi.mocked(apiClient.get).mockImplementation(async (path) => {
    if (path === "/browser-teaching-policy") return policy as never;
    if (path.endsWith("/browser-teaching-preference")) return preference as never;
    if (path.startsWith("/runs/")) return { id: ids.run, agent_id: ids.agent } as never;
    if (path === "/skills") return { items: [], total: 0 } as never;
    if (path === "/browser-procedures/teachings")
      return { items: [browserProcedureTeachingSummaryFixture()], next_cursor: null } as never;
    return current as never;
  });
  vi.mocked(apiClient.patch).mockImplementation(async (_path, body) => {
    const change = body as BrowserProcedureTeachingChange;
    current = {
      ...current,
      revision: current.revision + 1,
      ...(change.action === "review"
        ? { review: change.review }
        : { status: change.action === "pause" ? "paused" : "recording" }),
    };
    return current as never;
  });
  vi.mocked(apiClient.post).mockImplementation(async (path, body) => {
    if (path.endsWith("/propose")) {
      const request = body as BrowserProcedureTeachingPropose;
      current = {
        ...current,
        generation_state: "queued",
        generation_mode: request.mode,
        max_cost_usd: request.mode === "assistant" ? request.max_cost_usd : null,
        revision: current.revision + 1,
      };
    } else if (path.endsWith("/stop"))
      current = { ...current, status: "review", revision: current.revision + 1 };
    else {
      const request = body as BrowserProcedureTeachingStart;
      current = browserProcedureTeachingFixture({
        id: request.request_id,
        run_id: request.run_id,
        call_id: request.call_id,
        tab_id: request.tab_id,
        title: request.title,
        allowed_origins: request.allowed_origins,
        status: "recording",
        revision: 1,
      });
    }
    return current as never;
  });
  vi.mocked(apiClient.delete).mockImplementation(async () => {
    current = {
      ...current,
      status: "discarded",
      events: [],
      review: null,
      revision: current.revision + 1,
    };
    return current as never;
  });
  vi.mocked(apiClient.put).mockImplementation(async (path, body) => {
    const change = body as { enabled: boolean };
    if (path === "/browser-teaching-policy") {
      policy = { ...policy, enabled: change.enabled };
      return policy as never;
    }
    preference = { ...preference, enabled: change.enabled };
    return preference as never;
  });
});
afterEach(() => {
  cleanup();
  client?.clear();
  vi.restoreAllMocks();
  vi.useRealTimers();
  sessionStorage.clear();
});

describe("reviewed browser procedure", () => {
  it("resolves the addressed page's params before reading that owner's capture", async () => {
    const params = Promise.resolve({ sessionId: ids.session });
    await act(async () => {
      setup(
        <Suspense fallback={<p>Loading route</p>}>
          <TeachingReviewPage params={params} />
        </Suspense>,
      );
    });
    expect(
      await screen.findByRole("heading", { name: "Monthly report demonstration" }),
    ).toBeVisible();
    expect(apiClient.get).toHaveBeenCalledWith(
      "/browser-procedures/teachings/" + ids.session,
      expect.any(Object),
    );
  });

  it("requires a complete ordered review, then drafts without a model only after a separate click", async () => {
    reviewPage();
    await screen.findByRole("button", { name: "Save reviewed steps" });
    await userEvent.click(screen.getByRole("button", { name: "Save reviewed steps" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("valid skill name");
    expect(apiClient.patch).not.toHaveBeenCalled();
    fill("Skill name", "monthly-report");
    fill("Skill description", "Find the requested monthly report.");
    fill("Step 1 instruction", "Open reports");
    fill("Step 1 path template", "/reports");
    fill("Step 2 instruction", "Enter the requested month");
    fill("Step 3 instruction", "Open the report");
    await userEvent.click(screen.getByRole("button", { name: "Add parameter" }));
    fill("Parameter 1 name", "month");
    fill("Parameter 1 description", "The month to review");
    fill("Step 2 parameter name", "month");
    fill("Prerequisites", "A person has signed in");
    fill("Success checks", "Confirm the requested report is visible");
    await userEvent.click(screen.getByRole("button", { name: "Save reviewed steps" }));
    const draft = await readyDraft();
    expect(apiClient.patch).toHaveBeenCalledWith(
      `/browser-procedures/teachings/${ids.session}`,
      expect.objectContaining({
        action: "review",
        review: expect.objectContaining({
          actions: [
            {
              sequence: 1,
              label: "Open reports",
              parameter: null,
              path_template: "/reports",
              omit: false,
            },
            {
              sequence: 2,
              label: "Enter the requested month",
              parameter: "month",
              path_template: null,
              omit: false,
            },
            {
              sequence: 3,
              label: "Open the report",
              parameter: null,
              path_template: null,
              omit: false,
            },
          ],
        }),
      }),
      expect.objectContaining({
        headers: { "X-Organization-Id": ids.org, "If-Match": '"2"' },
        retryAfterRefresh: false,
      }),
    );
    expect(apiClient.post).not.toHaveBeenCalled();
    await userEvent.click(draft);
    await screen.findByText("Draft queued");
    expect(apiClient.post).toHaveBeenCalledWith(
      `/browser-procedures/teachings/${ids.session}/propose`,
      { mode: "reviewed" },
      expect.objectContaining({ headers: { "X-Organization-Id": ids.org, "If-Match": '"3"' } }),
    );
    expect(screen.queryByRole("button", { name: "Create draft from reviewed steps" })).toBeNull();
  });
  it("clears hidden invalid parameter/path values only when a step is explicitly omitted", async () => {
    current = browserProcedureTeachingFixture({ review: browserProcedureTeachingReviewFixture() });
    reviewPage();
    await readyDraft();
    fill("Step 2 parameter name", "not valid");
    await userEvent.click(screen.getByRole("checkbox", { name: "Omit step 2" }));
    expect(screen.queryByLabelText("Step 2 parameter name")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Save reviewed steps" }));
    await waitFor(() =>
      expect(current.review?.actions[1]).toMatchObject({
        sequence: 2,
        omit: true,
        parameter: null,
        path_template: null,
      }),
    );
    await userEvent.click(screen.getByRole("checkbox", { name: "Omit step 2" }));
    expect(screen.getByLabelText("Step 2 parameter name")).toHaveValue("");
  });
  it("requires an explicit bounded assistant budget and preserves the exact choice", async () => {
    current = browserProcedureTeachingFixture({ review: browserProcedureTeachingReviewFixture() });
    reviewPage();
    await readyDraft();
    await userEvent.click(
      screen.getByRole("radio", { name: "Ask the assistant to draft — optional paid model call" }),
    );
    const draft = screen.getByRole("button", { name: "Draft with the assistant" });
    expect(draft).toBeDisabled();
    fill("Maximum drafting cost (USD)", "11");
    expect(draft).toBeDisabled();
    fill("Maximum drafting cost (USD)", "0.250000");
    expect(draft).toBeEnabled();
    await userEvent.click(draft);
    await screen.findByText("Draft queued");
    expect(apiClient.post).toHaveBeenCalledWith(
      expect.stringContaining("/propose"),
      { mode: "assistant", max_cost_usd: "0.250000" },
      expect.anything(),
    );
  });
  it("retains a lost Draft response across reload and Check again performs no write", async () => {
    current = browserProcedureTeachingFixture({ review: browserProcedureTeachingReviewFixture() });
    vi.mocked(apiClient.post).mockRejectedValue(new TypeError("lost acknowledgement"));
    const first = reviewPage();
    await userEvent.click(await readyDraft());
    await screen.findByText(/Draft response is unresolved/);
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    first.unmount();
    client.clear();
    reviewPage();
    await screen.findByRole("button", { name: "Retry the same Draft request" });
    const checks = screen.getAllByRole("button", { name: "Check again" });
    await userEvent.click(checks[checks.length - 1]!);
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    vi.mocked(apiClient.post).mockImplementation(async () => {
      current = {
        ...current,
        generation_state: "queued",
        generation_mode: "reviewed",
        revision: 3,
      };
      return current as never;
    });
    await userEvent.click(screen.getByRole("button", { name: "Retry the same Draft request" }));
    await screen.findByText("Draft queued");
    const requests = vi.mocked(apiClient.post).mock.calls;
    expect(requests[1]![1]).toEqual(requests[0]![1]);
    expect(requests[1]![2]?.headers).toEqual(requests[0]![2]?.headers);
  });
  it("never offers another draft for an unknown outcome and preserves proposal authority", async () => {
    current = browserProcedureTeachingFixture({
      review: browserProcedureTeachingReviewFixture(),
      generation_state: "unknown",
    });
    reviewPage();
    await screen.findByText(/drafting outcome is uncertain/i);
    expect(screen.queryByRole("button", { name: /Create draft/ })).toBeNull();
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it.each([true, false])(
    "uses the existing proposal handoff when proposal authority is %s",
    async (allowed) => {
      current = browserProcedureTeachingFixture({
        status: "proposed",
        generation_state: "succeeded",
        proposal_id: ids.proposal,
      });
      if (!allowed) permission.denied.add(Perm.runsView);
      reviewPage();
      await screen.findByText("Skill draft ready for review");
      if (allowed)
        expect(screen.getByRole("link", { name: "Review proposals in Skills" })).toHaveAttribute(
          "href",
          "/en/skills",
        );
      else expect(screen.getByText(/permissions do not allow/)).toBeVisible();
      expect(screen.queryByRole("button", { name: "Discard capture" })).toBeNull();
      expect(apiClient.post).not.toHaveBeenCalled();
    },
  );
  it("holds a refinement until both completion states are recorded", async () => {
    current = browserProcedureTeachingFixture({
      source: "refinement",
      reason_code: "task_not_completed",
      verified_success: false,
    });
    reviewPage();
    await screen.findByText(/not reviewable until/);
    expect(screen.queryByRole("button", { name: "Save reviewed steps" })).toBeNull();
    current = { ...current, verified_success: true, reason_code: null, revision: 3 };
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    await screen.findByRole("button", { name: "Save reviewed steps" });
    expect(screen.getByText(/does not independently verify/)).toBeVisible();
  });
  it("hides all capture metadata when a fresh owner read is refused", async () => {
    reviewPage();
    await screen.findByRole("heading", { name: "Monthly report demonstration" });
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(403, "PRIVATE ERROR"));
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    await screen.findByText(/unavailable to the current person/);
    expect(screen.queryByText("Monthly report demonstration")).toBeNull();
    expect(screen.queryByText("PRIVATE ERROR")).toBeNull();
  });
  it("requires a separate destructive decision before erasing a capture", async () => {
    reviewPage();
    await screen.findByRole("button", { name: "Discard capture" });
    await userEvent.click(screen.getByRole("button", { name: "Discard capture" }));
    expect(apiClient.delete).not.toHaveBeenCalled();
    await userEvent.click(screen.getAllByRole("button", { name: "Discard capture" }).at(-1)!);
    await screen.findByText("Discarded");
    expect(apiClient.delete).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Save reviewed steps" })).toBeNull();
  });
});

describe("live teaching control and recovery", () => {
  it("reads teaching metadata only after opening the controls and starts with the server token", async () => {
    setup(<BrowserTeachingControls browse={browserProcedureTeachingBrowseFixture()} canControl />);
    expect(apiClient.get).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Teach a browser procedure" }));
    await screen.findByLabelText("Demonstration title");
    fill("Demonstration title", "A synthetic demonstration");
    const start = screen.getByRole("button", { name: "Start recording" });
    await waitFor(() => expect(start).toBeEnabled());
    await userEvent.click(start);
    await screen.findByRole("button", { name: "Pause recording" });
    const request = vi.mocked(apiClient.post).mock.calls[0]![1] as BrowserProcedureTeachingStart;
    expect(request).toMatchObject({
      run_id: ids.run,
      call_id: "teaching-call",
      tab_id: "main",
      takeover_id: ids.takeover,
      allowed_origins: ["https://reports.example"],
    });
    expect(request).not.toHaveProperty("control_connection_id");
    await userEvent.click(screen.getByRole("button", { name: "Pause recording" }));
    await screen.findByRole("button", { name: "Resume recording" });
    await userEvent.click(screen.getByRole("button", { name: "Resume recording" }));
    await screen.findByRole("button", { name: "Pause recording" });
    expect(apiClient.patch).toHaveBeenLastCalledWith(
      expect.any(String),
      { action: "resume", takeover_id: ids.takeover },
      expect.anything(),
    );
    await userEvent.click(screen.getByRole("button", { name: "Stop and review" }));
    await screen.findByRole("link", { name: "Review capture" });
  });
  it("does not admit Start without the exact current holder lease", async () => {
    setup(
      <BrowserTeachingControls
        browse={browserProcedureTeachingBrowseFixture({ heldById: ids.other })}
        canControl
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Teach a browser procedure" }));
    await screen.findByLabelText("Demonstration title");
    fill("Demonstration title", "Cannot record");
    expect(screen.getByRole("button", { name: "Start recording" })).toBeDisabled();
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it("preserves an uncertain Start across reload and recovers it with only GET", async () => {
    vi.mocked(apiClient.post).mockImplementation(async (_path, value) => {
      const body = value as BrowserProcedureTeachingStart;
      current = browserProcedureTeachingFixture({
        id: body.request_id,
        status: "recording",
        title: body.title,
      });
      throw new TypeError("lost acknowledgement");
    });
    const first = setup(
      <BrowserTeachingControls browse={browserProcedureTeachingBrowseFixture()} canControl />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Teach a browser procedure" }));
    await screen.findByLabelText("Demonstration title");
    fill("Demonstration title", "Recover this capture");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Start recording" })).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole("button", { name: "Start recording" }));
    await screen.findByText(/Start response is unresolved/);
    first.unmount();
    client.clear();
    setup(
      <BrowserTeachingControls
        browse={browserProcedureTeachingBrowseFixture({ takeoverId: null })}
        canControl={false}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Teach a browser procedure" }));
    await screen.findByRole("button", { name: "Retry the same Start request" });
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    await screen.findByRole("heading", { name: "Recover this capture" });
    expect(apiClient.post).toHaveBeenCalledTimes(1);
  });
  it("mounts no teaching controls for protected output or an unidentified view", () => {
    const view = setup(
      <BrowserTeachingControls
        browse={browserProcedureTeachingBrowseFixture({ outputProtected: true })}
        canControl
      />,
    );
    expect(screen.queryByRole("button")).toBeNull();
    view.rerender(
      <QueryClientProvider client={client}>
        <BrowserTeachingControls
          browse={browserProcedureTeachingBrowseFixture({ runId: null })}
          canControl
        />
      </QueryClientProvider>,
    );
    expect(screen.queryByRole("button")).toBeNull();
    expect(apiClient.get).not.toHaveBeenCalled();
  });
});

describe("discovery and default-off controls", () => {
  it("opens an owner capture through the durable list rather than a private chat URL", async () => {
    setup(<TeachingListPage />);
    await screen.findByRole("heading", { name: "Monthly report demonstration" });
    expect(screen.getByRole("link", { name: "Open capture" })).toHaveAttribute(
      "href",
      `/en/skills/teaching/${ids.session}`,
    );
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it("shows a redacted expired entry without inventing its old title", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [
        browserProcedureTeachingSummaryFixture({
          status: "expired",
          title: "",
          allowed_origins: [],
        }),
      ],
      next_cursor: null,
    } as never);
    setup(<BrowserTeachingList />);
    await screen.findByRole("heading", { name: "Expired capture" });
    expect(screen.queryByText("Monthly report demonstration")).toBeNull();
  });
  it("gates organization policy by org:settings and requires an explicit confirmation", async () => {
    permission.denied.add(Perm.orgSettings);
    const hidden = setup(<BrowserTeachingPolicy />);
    expect(apiClient.get).not.toHaveBeenCalled();
    hidden.unmount();
    client.clear();
    permission.denied.clear();
    policy.enabled = false;
    setup(<BrowserTeachingPolicy />);
    const toggle = await screen.findByRole("switch", { name: "Allow browser teaching" });
    expect(toggle).not.toBeChecked();
    await userEvent.click(toggle);
    expect(apiClient.put).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(toggle).toBeChecked());
    expect(apiClient.put).toHaveBeenCalledWith(
      "/browser-teaching-policy",
      { generation: ids.other, enabled: true },
      expect.anything(),
    );
  });
  it("allows a member to revoke learning after agent access is lost", async () => {
    preference = { ...preference, enabled: true, allowed: false };
    setup(<BrowserTeachingPreference agentId={ids.agent} />);
    const toggle = await screen.findByRole("switch", {
      name: "Suggest procedures from my completed work",
    });
    expect(toggle).toBeEnabled();
    await userEvent.click(toggle);
    await waitFor(() => expect(toggle).not.toBeChecked());
    expect(toggle).toBeDisabled();
  });
});
