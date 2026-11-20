import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { Perm } from "@/types/permissions";
import type {
  BrowserProcedureTeaching,
  BrowserProcedureTeachingChange,
  BrowserProcedureTeachingStart,
} from "@/types/browser-procedure-teaching";
import {
  readBrowserProcedureTeachingAttempt,
  clearBrowserProcedureTeachingAttempt,
  retainBrowserProcedureTeachingAttempt,
  browserProcedureTeachingAttemptKey,
  type BrowserProcedureTeachingDraftAttempt,
  type BrowserProcedureTeachingStartAttempt,
} from "@/lib/browser-procedure-teaching-attempts";
import {
  BROWSER_PROCEDURE_TEACHING_IDS as ids,
  browserProcedureTeachingBrowseFixture,
  browserProcedureTeachingFixture,
  browserProcedureTeachingReviewFixture,
} from "@/test-utils/browser-procedure-teaching";
import { BrowserTeachingControls } from "./browser-teaching-controls";
import { BrowserTeachingReview } from "./browser-teaching-review";
import { BrowserTeachingStart } from "./browser-teaching-start";
import { BrowserTeachingDraft } from "./browser-teaching-draft";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
const access = vi.hoisted(() => ({ create: true }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    can: (permission: string) => permission !== Perm.skillsEdit || access.create,
    isLoading: false,
  }),
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
let current: BrowserProcedureTeaching;
let client: QueryClient;
let policy: { enabled: boolean; generation: string | null; deployment_enabled: boolean };
const audience = { actor: ids.owner, organization: ids.org };
const startKey = browserProcedureTeachingAttemptKey(audience, "start", [
  ids.run,
  "teaching-call",
  "main",
]);
const draftKey = browserProcedureTeachingAttemptKey(audience, "propose", [ids.session]);
const draftAttempt = (revision = 2): BrowserProcedureTeachingDraftAttempt => ({
  kind: "propose",
  revision,
  body: { mode: "assistant", max_cost_usd: "1.25" },
});
function setup(node: ReactNode, mutationCache?: MutationCache) {
  client = new QueryClient({
    mutationCache,
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}
function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
async function review() {
  setup(<BrowserTeachingReview sessionId={ids.session} />);
  return screen.findByRole("button", { name: "Save reviewed steps" });
}
async function openControls(
  browse = browserProcedureTeachingBrowseFixture({ teachingSessionId: ids.session }),
) {
  const view = setup(<BrowserTeachingControls browse={browse} canControl />);
  await userEvent.click(screen.getByRole("button", { name: "Teach a browser procedure" }));
  return view;
}
function savedStart(): BrowserProcedureTeachingStartAttempt {
  return {
    kind: "start",
    targetSkillId: null,
    body: {
      request_id: ids.session,
      run_id: ids.run,
      call_id: "teaching-call",
      tab_id: "main",
      takeover_id: ids.takeover,
      title: "Retained review",
      allowed_origins: ["https://reports.example"],
    },
  };
}
function stopReceipt(session: BrowserProcedureTeaching): BrowserProcedureTeaching {
  return {
    ...session,
    revision: session.revision + 1,
    ...(session.source === "manual"
      ? { status: "review" as const }
      : {
          status: "discarded" as const,
          title: "",
          allowed_origins: [],
          events: [],
          review: null,
          procedure: null,
          reason_code: "task_not_completed" as const,
          generation_state:
            session.generation_state === "queued" || session.generation_state === "generating"
              ? ("cancelled" as const)
              : session.generation_state,
        }),
  };
}
beforeEach(() => {
  vi.resetAllMocks();
  access.create = true;
  sessionStorage.clear();
  useAuthStore.setState({ user: { id: ids.owner } as never, accessToken: "test" });
  useOrgStore.setState({ activeOrgId: ids.org });
  current = browserProcedureTeachingFixture({ review: browserProcedureTeachingReviewFixture() });
  policy = { enabled: true, generation: ids.other, deployment_enabled: true };
  vi.mocked(apiClient.get).mockImplementation(async (path) => {
    if (path === "/browser-teaching-policy") return policy as never;
    if (path.endsWith("/browser-teaching-preference"))
      return { agent_id: ids.agent, enabled: false, generation: null, allowed: true } as never;
    if (path.startsWith("/runs/")) return { id: ids.run, agent_id: ids.agent } as never;
    if (path === "/skills") return { items: [], total: 0 } as never;
    return current as never;
  });
  vi.mocked(apiClient.patch).mockImplementation(async (_path, body) => {
    const change = body as BrowserProcedureTeachingChange;
    current = {
      ...current,
      revision: current.revision + 1,
      ...(change.action === "review"
        ? { review: change.review, generation_state: "none" }
        : { status: change.action === "pause" ? "paused" : "recording" }),
    };
    return current as never;
  });
  vi.mocked(apiClient.post).mockImplementation(async (path, body) => {
    if (path.endsWith("/stop")) current = stopReceipt(current);
    else if (path.endsWith("/propose"))
      current = { ...current, generation_state: "queued", revision: current.revision + 1 };
    else {
      const start = body as BrowserProcedureTeachingStart;
      current = browserProcedureTeachingFixture({
        id: start.request_id,
        title: start.title,
        status: "recording",
        revision: 1,
        target_skill_id: path.startsWith("/skills/") ? ids.skill : null,
      });
    }
    return current as never;
  });
});
afterEach(() => {
  cleanup();
  client?.clear();
  vi.restoreAllMocks();
  vi.useRealTimers();
  sessionStorage.clear();
});

describe("review lifecycle uses current complete capture evidence", () => {
  it("fences the unresolved Draft only after an acknowledged newer review, then requires a separate new Draft click", async () => {
    expect(retainBrowserProcedureTeachingAttempt(draftKey, draftAttempt())).toBe(true);
    await review();
    await screen.findByRole("button", { name: "Retry the same Draft request" });
    fill("Skill description", "Explicitly reviewed after the uncertain response");
    await userEvent.click(screen.getByRole("button", { name: "Save reviewed steps" }));
    await waitFor(() =>
      expect(readBrowserProcedureTeachingAttempt(draftKey, "propose").attempt).toBeNull(),
    );
    expect(apiClient.patch).toHaveBeenCalledWith(
      "/browser-procedures/teachings/" + ids.session,
      expect.objectContaining({ action: "review" }),
      expect.objectContaining({ headers: { "X-Organization-Id": ids.org, "If-Match": '"2"' } }),
    );
    expect(apiClient.post).not.toHaveBeenCalled();
    await userEvent.click(
      await screen.findByRole("button", { name: "Create draft from reviewed steps" }),
    );
    expect(apiClient.post).toHaveBeenCalledWith(
      "/browser-procedures/teachings/" + ids.session + "/propose",
      { mode: "reviewed" },
      expect.objectContaining({ headers: { "X-Organization-Id": ids.org, "If-Match": '"3"' } }),
    );
  });

  it("preserves the old attempt when Draft wins the lock until a fresh GET confirms its queued receipt", async () => {
    const saved = draftAttempt();
    expect(retainBrowserProcedureTeachingAttempt(draftKey, saved)).toBe(true);
    const get = vi.mocked(apiClient.get).getMockImplementation()!;
    let awaitingReceipt = false;
    let receipt!: () => void;
    vi.mocked(apiClient.get).mockImplementation(async (path, options) => {
      if (awaitingReceipt && path.startsWith("/browser-procedures/teachings/"))
        return new Promise((resolve) => {
          receipt = () => resolve(current as never);
        });
      return get(path, options);
    });
    vi.mocked(apiClient.patch).mockImplementation(async () => {
      current = {
        ...current,
        revision: 3,
        generation_state: "queued",
        generation_mode: "assistant",
        max_cost_usd: "1.25",
      };
      awaitingReceipt = true;
      throw new ApiError(409, "The old Draft was already admitted");
    });
    await review();
    fill("Skill description", "A later review");
    await userEvent.click(screen.getByRole("button", { name: "Save reviewed steps" }));
    await within(screen.getByRole("region", { name: "Review every step" })).findByText(
      "This request is unavailable. Check again to read the current state.",
    );
    expect(readBrowserProcedureTeachingAttempt(draftKey, "propose").attempt).toEqual(saved);
    await waitFor(() => expect(receipt).toBeDefined());
    await act(async () => receipt());
    await screen.findByText("Draft queued");
    await waitFor(() =>
      expect(readBrowserProcedureTeachingAttempt(draftKey, "propose").attempt).toBeNull(),
    );
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("retains uncertainty after a lost review acknowledgment until a later explicit save is acknowledged", async () => {
    const saved = draftAttempt();
    expect(retainBrowserProcedureTeachingAttempt(draftKey, saved)).toBe(true);
    const patch = vi.mocked(apiClient.patch).getMockImplementation()!;
    vi.mocked(apiClient.patch).mockImplementationOnce(async () => {
      current = { ...current, revision: 3 };
      throw new TypeError("Lost review acknowledgment");
    });
    await review();
    fill("Skill description", "Explicit review");
    await userEvent.click(screen.getByRole("button", { name: "Save reviewed steps" }));
    await screen.findByText(/capture changed after you opened/);
    expect(readBrowserProcedureTeachingAttempt(draftKey, "propose").attempt).toEqual(saved);
    expect(apiClient.post).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Load current review" }));
    vi.mocked(apiClient.patch).mockImplementation(patch);
    await userEvent.click(screen.getByRole("button", { name: "Save reviewed steps" }));
    await waitFor(() =>
      expect(readBrowserProcedureTeachingAttempt(draftKey, "propose").attempt).toBeNull(),
    );
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("does not clear a different retained Draft created while the review acknowledgment was in flight", async () => {
    expect(retainBrowserProcedureTeachingAttempt(draftKey, draftAttempt())).toBe(true);
    let finish!: () => void;
    vi.mocked(apiClient.patch).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = () => {
            current = { ...current, revision: 3 };
            resolve(current as never);
          };
        }),
    );
    await review();
    fill("Skill description", "Review in flight");
    await userEvent.click(screen.getByRole("button", { name: "Save reviewed steps" }));
    await waitFor(() => expect(finish).toBeDefined());
    const newer = draftAttempt(9);
    expect(clearBrowserProcedureTeachingAttempt(draftKey)).toBe(true);
    expect(retainBrowserProcedureTeachingAttempt(draftKey, newer)).toBe(true);
    await act(async () => finish());
    await screen.findByRole("button", { name: "Retry the same Draft request" });
    expect(readBrowserProcedureTeachingAttempt(draftKey, "propose").attempt).toEqual(newer);
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("does not settle a retained Draft whose revision is newer than this acknowledged review", async () => {
    const newer = draftAttempt(9);
    expect(retainBrowserProcedureTeachingAttempt(draftKey, newer)).toBe(true);
    await review();
    fill("Skill description", "Older review");
    await userEvent.click(screen.getByRole("button", { name: "Save reviewed steps" }));
    await screen.findByRole("button", { name: "Retry the same Draft request" });
    expect(readBrowserProcedureTeachingAttempt(draftKey, "propose").attempt).toEqual(newer);
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("keeps the old audience's retry tuple when organization changes at the review acknowledgment", async () => {
    expect(retainBrowserProcedureTeachingAttempt(draftKey, draftAttempt())).toBe(true);
    setup(
      <BrowserTeachingReview sessionId={ids.session} />,
      new MutationCache({
        onSuccess: () => useOrgStore.setState({ activeOrgId: ids.other }),
      }),
    );
    await screen.findByRole("button", { name: "Save reviewed steps" });
    fill("Skill description", "Review before switching workspace");
    await userEvent.click(screen.getByRole("button", { name: "Save reviewed steps" }));
    await waitFor(() => expect(useOrgStore.getState().activeOrgId).toBe(ids.other));
    expect(readBrowserProcedureTeachingAttempt(draftKey, "propose").attempt).toEqual(
      draftAttempt(),
    );
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("reports unavailable storage when a known review cannot clear its obsolete attempt", async () => {
    expect(retainBrowserProcedureTeachingAttempt(draftKey, draftAttempt())).toBe(true);
    await review();
    fill("Skill description", "Review with unavailable storage");
    vi.spyOn(sessionStorage, "removeItem").mockImplementation(() => {
      throw new Error("Storage unavailable");
    });
    await userEvent.click(screen.getByRole("button", { name: "Save reviewed steps" }));
    await screen.findByText(/cannot safely retain this attempt/);
    expect(readBrowserProcedureTeachingAttempt(draftKey, "propose").attempt).toEqual(
      draftAttempt(),
    );
    expect(
      screen.queryByRole("button", { name: "Create draft from reviewed steps" }),
    ).not.toBeInTheDocument();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("does not read private attempt storage or expose consent before client hydration", () => {
    const read = vi.spyOn(sessionStorage, "getItem");
    expect(
      renderToString(
        <BrowserTeachingStart
          browse={browserProcedureTeachingBrowseFixture()}
          canStart
          onStarted={vi.fn()}
        />,
      ),
    ).toBe("");
    expect(
      renderToString(<BrowserTeachingDraft session={current} state={{ audience } as never} />),
    ).toBe("");
    expect(read).not.toHaveBeenCalled();
    expect(apiClient.get).not.toHaveBeenCalled();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("requires loading a newer complete review before saving over a stale form", async () => {
    await review();
    fill("Skill description", "Unsaved description");
    const remote = browserProcedureTeachingReviewFixture();
    remote.description = "Reviewed on another device";
    current = { ...current, review: remote, revision: 4 };
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    await screen.findByText(/capture changed after you opened/);
    expect(screen.getByLabelText("Skill description")).toHaveValue("Unsaved description");
    expect(screen.getByRole("button", { name: "Save reviewed steps" })).toBeDisabled();
    expect(apiClient.patch).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Load current review" }));
    expect(screen.getByLabelText("Skill description")).toHaveValue("Reviewed on another device");
    fill("Skill description", "Confirmed current description");
    await userEvent.click(screen.getByRole("button", { name: "Save reviewed steps" }));
    await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(1));
    expect(apiClient.patch).toHaveBeenCalledWith(
      "/browser-procedures/teachings/" + ids.session,
      expect.objectContaining({ action: "review" }),
      expect.objectContaining({ headers: { "X-Organization-Id": ids.org, "If-Match": '"4"' } }),
    );
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("keeps parameter definitions separate, requires cleared paths and inputs again, and permits empty prerequisites", async () => {
    current.events[1]!.action = "select";
    current.events[2]!.human_step = true;
    await review();
    expect(screen.getByText(/A person must handle this step/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Add parameter" }));
    fill("Parameter 2 name", "report");
    fill("Parameter 2 description", "Which report");
    fill("Parameter 1 name", "month");
    fill("Parameter 1 description", "Month requested by the person");
    await userEvent.click(screen.getAllByRole("button", { name: "Remove parameter" })[1]!);
    expect(screen.queryByLabelText("Parameter 2 name")).not.toBeInTheDocument();
    fill("Step 1 path template", "");
    fill("Step 2 parameter name", "");
    fill("Prerequisites", "");
    await userEvent.click(screen.getByRole("button", { name: "Save reviewed steps" }));
    expect(apiClient.patch).not.toHaveBeenCalled();
    fill("Step 1 path template", "/reports");
    fill("Step 2 parameter name", "month");
    await userEvent.click(screen.getByRole("button", { name: "Save reviewed steps" }));
    await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(1));
    expect(current.review?.prerequisites).toEqual([]);
    expect(current.review?.parameters).toEqual([
      { name: "month", description: "Month requested by the person" },
    ]);
    expect(current.review?.actions.map((step) => step.sequence)).toEqual([1, 2, 3]);
  });

  it.each(["manual", "refinement"] as const)(
    "explicitly stops a %s capture once despite a second quick click",
    async (source) => {
      current = browserProcedureTeachingFixture({ status: "recording", source });
      let complete!: () => void;
      vi.mocked(apiClient.post).mockImplementation(
        () =>
          new Promise((resolve) => {
            complete = () => {
              current = stopReceipt(current);
              resolve(current as never);
            };
          }),
      );
      setup(<BrowserTeachingReview sessionId={ids.session} />);
      const stop = await screen.findByRole("button", {
        name: source === "manual" ? "Stop and review" : "Stop this suggestion",
      });
      act(() => {
        fireEvent.click(stop);
        fireEvent.click(stop);
      });
      await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
      await act(async () => complete());
      await waitFor(() =>
        expect(
          screen.queryByRole("button", {
            name: source === "manual" ? "Stop and review" : "Stop this suggestion",
          }),
        ).not.toBeInTheDocument(),
      );
      expect(apiClient.post).toHaveBeenCalledWith(
        "/browser-procedures/teachings/" + ids.session + "/stop",
        {},
        expect.any(Object),
      );
      if (source === "refinement") {
        expect(screen.queryByText("Monthly report demonstration")).not.toBeInTheDocument();
        expect(current).toMatchObject({
          title: "",
          events: [],
          review: null,
          reason_code: "task_not_completed",
        });
      } else expect(current.title).toBe("Monthly report demonstration");
    },
  );

  it("keeps an authoritative Stop refusal visible without erasing the capture", async () => {
    current = browserProcedureTeachingFixture({ status: "paused" });
    vi.mocked(apiClient.post).mockRejectedValue(new ApiError(409, "PRIVATE REFUSAL"));
    setup(<BrowserTeachingReview sessionId={ids.session} />);
    await userEvent.click(await screen.findByRole("button", { name: "Stop and review" }));
    await screen.findByText("This request is unavailable. Check again to read the current state.");
    expect(screen.getByRole("heading", { name: current.title })).toBeVisible();
    expect(apiClient.delete).not.toHaveBeenCalled();
  });

  it("switching back from assistant drafting preserves an explicit no-model request", async () => {
    await review();
    await userEvent.click(
      screen.getByRole("radio", { name: "Ask the assistant to draft — optional paid model call" }),
    );
    fill("Maximum drafting cost (USD)", "1.25");
    await userEvent.click(
      screen.getByRole("radio", { name: "Use my reviewed steps — no model call" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Create draft from reviewed steps" }));
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    expect(apiClient.post).toHaveBeenCalledWith(
      expect.stringContaining("/propose"),
      { mode: "reviewed" },
      expect.any(Object),
    );
  });

  it.each(["Start", "Draft"] as const)(
    "blocks a fresh %s whose definite refusal cannot be safely removed from storage",
    async (kind) => {
      if (kind === "Draft") await review();
      else {
        setup(
          <BrowserTeachingStart
            browse={browserProcedureTeachingBrowseFixture()}
            canStart
            onStarted={vi.fn()}
          />,
        );
        fill("Demonstration title", "Synthetic review");
      }
      const button = await screen.findByRole("button", {
        name: kind === "Start" ? "Start recording" : "Create draft from reviewed steps",
      });
      await waitFor(() => expect(button).toBeEnabled());
      vi.spyOn(sessionStorage, "removeItem").mockImplementation(() => {
        throw new Error("Unavailable storage");
      });
      vi.mocked(apiClient.post).mockRejectedValue(new ApiError(409, "PRIVATE REFUSAL"));
      await userEvent.click(button);
      await screen.findByText(/cannot safely retain this attempt/);
      expect(apiClient.post).toHaveBeenCalledTimes(1);
      expect(
        screen.queryByRole("button", {
          name: kind === "Start" ? "Retry the same Start request" : "Retry the same Draft request",
        }),
      ).not.toBeInTheDocument();
    },
  );
});

describe("start destinations and current live control", () => {
  it("follows a fresh teaching notification without reviving an older local New capture choice", async () => {
    const initial = browserProcedureTeachingBrowseFixture({ teachingSessionId: ids.session });
    const view = await openControls(initial);
    await userEvent.click(
      await screen.findByRole("button", { name: "Record another demonstration" }),
    );
    expect(await screen.findByLabelText("Demonstration title")).toHaveValue("");
    current = browserProcedureTeachingFixture({
      id: ids.other,
      title: "Another current capture",
      status: "paused",
    });
    view.rerender(
      <QueryClientProvider client={client}>
        <BrowserTeachingControls browse={{ ...initial, teachingSessionId: ids.other }} canControl />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("button", { name: "Resume recording" })).toBeEnabled();
    expect(screen.queryByLabelText("Demonstration title")).not.toBeInTheDocument();
    current = browserProcedureTeachingFixture();
    view.rerender(
      <QueryClientProvider client={client}>
        <BrowserTeachingControls browse={initial} canControl />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("link", { name: "Review capture" })).toHaveAttribute(
      "href",
      "/en/skills/teaching/" + ids.session,
    );
    expect(screen.queryByLabelText("Demonstration title")).not.toBeInTheDocument();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("uses a paginated per-skill edit grant without requiring global skill creation", async () => {
    access.create = false;
    vi.mocked(apiClient.get).mockImplementation(async (path, options) => {
      if (path !== "/skills") return current as never;
      return Number(new URLSearchParams(options?.params).get("skip") ?? 0) === 0
        ? ({
            items: [{ id: ids.other, name: "Read-only skill", can_edit: false }],
            total: 2,
          } as never)
        : ({
            items: [{ id: ids.skill, name: "Editable procedure", can_edit: true }],
            total: 2,
          } as never);
    });
    const started = vi.fn();
    setup(
      <BrowserTeachingStart
        browse={browserProcedureTeachingBrowseFixture({ url: null })}
        canStart
        onStarted={started}
      />,
    );
    fill("Demonstration title", "Granted skill review");
    fill("Allowed HTTPS origins", "https://reports.example/private");
    expect(screen.getByText("Enter one to ten distinct, exact HTTPS origins.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Start recording" })).toBeDisabled();
    fill("Allowed HTTPS origins", "https://reports.example\nhttps://admin.example");
    await userEvent.click(await screen.findByRole("button", { name: "Load more skills" }));
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    await userEvent.click(screen.getByRole("combobox", { name: "Draft destination" }));
    expect(screen.queryByRole("option", { name: "Read-only skill" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Create a new skill" })).not.toBeInTheDocument();
    await userEvent.click(await screen.findByRole("option", { name: "Editable procedure" }));
    await userEvent.click(screen.getByRole("button", { name: "Start recording" }));
    await waitFor(() => expect(started).toHaveBeenCalledTimes(1));
    expect(apiClient.post).toHaveBeenCalledWith(
      "/skills/" + ids.skill + "/browser-procedures/teachings",
      expect.objectContaining({
        allowed_origins: ["https://reports.example", "https://admin.example"],
      }),
      expect.any(Object),
    );
  });

  it("withholds a destination when the grant read fails and an unsafe initial location supplies no origin", async () => {
    access.create = false;
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(403, "PRIVATE SKILL NAMES"));
    setup(
      <BrowserTeachingStart
        browse={browserProcedureTeachingBrowseFixture({ url: "not an origin" })}
        canStart
        onStarted={vi.fn()}
      />,
    );
    await screen.findByText("This request is unavailable. Check again to read the current state.");
    expect(screen.getByLabelText("Allowed HTTPS origins")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Start recording" })).toBeDisabled();
    expect(screen.queryByText("PRIVATE SKILL NAMES")).not.toBeInTheDocument();
  });

  it("coalesces repeated Check again clicks into one pure recovery read", async () => {
    expect(retainBrowserProcedureTeachingAttempt(startKey, savedStart())).toBe(true);
    let finish!: (value: BrowserProcedureTeaching) => void;
    vi.mocked(apiClient.get).mockImplementation(async (path) =>
      path === "/skills"
        ? ({ items: [], total: 0 } as never)
        : new Promise((resolve) => {
            finish = (value) => resolve(value as never);
          }),
    );
    const started = vi.fn();
    setup(
      <BrowserTeachingStart
        browse={browserProcedureTeachingBrowseFixture()}
        canStart
        onStarted={started}
      />,
    );
    const check = await screen.findByRole("button", { name: "Check again" });
    act(() => {
      fireEvent.click(check);
      fireEvent.click(check);
    });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    await act(async () => finish(current));
    expect(started).toHaveBeenCalledTimes(1);
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("does not deliver an acknowledged Start after the audience changes before mutation settlement", async () => {
    const mutationCache = new MutationCache({
      onSuccess: () => useOrgStore.setState({ activeOrgId: ids.other }),
    });
    setup(
      <BrowserTeachingControls browse={browserProcedureTeachingBrowseFixture()} canControl />,
      mutationCache,
    );
    await userEvent.click(screen.getByRole("button", { name: "Teach a browser procedure" }));
    fill("Demonstration title", "Private initial organization");
    const start = screen.getByRole("button", { name: "Start recording" });
    await waitFor(() => expect(start).toBeEnabled());
    await userEvent.click(start);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(readBrowserProcedureTeachingAttempt(startKey, "start").attempt).not.toBeNull();
    expect(screen.queryByText("Private initial organization")).not.toBeInTheDocument();
    expect(apiClient.post).toHaveBeenCalledTimes(1);
  });

  it("can start a separate demonstration after an ended capture while retaining its review link", async () => {
    current = browserProcedureTeachingFixture({ title: "", status: "expired" });
    await openControls();
    await screen.findByRole("link", { name: "Review capture" });
    await userEvent.click(screen.getByRole("button", { name: "Record another demonstration" }));
    expect(await screen.findByLabelText("Demonstration title")).toHaveValue("");
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("keeps a paused capture readable without borrowing another person's takeover", async () => {
    current = browserProcedureTeachingFixture({ status: "paused" });
    const browse = browserProcedureTeachingBrowseFixture({
      teachingSessionId: ids.session,
      heldById: ids.other,
    });
    const view = await openControls(browse);
    expect(await screen.findByRole("button", { name: "Resume recording" })).toBeDisabled();
    expect(screen.getByText(/Take over this live browser/)).toBeVisible();
    expect(apiClient.patch).not.toHaveBeenCalled();
    view.rerender(
      <QueryClientProvider client={client}>
        <BrowserTeachingControls
          browse={{ ...browse, heldById: ids.owner, takeoverId: ids.takeover }}
          canControl
        />
      </QueryClientProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Resume recording" }));
    await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(1));
    expect(apiClient.patch).toHaveBeenCalledWith(
      expect.any(String),
      { action: "resume", takeover_id: ids.takeover },
      expect.any(Object),
    );
  });

  it("recovers an unavailable addressed capture by GET without replaying consent", async () => {
    const get = vi.mocked(apiClient.get).getMockImplementation()!;
    let missing = true;
    vi.mocked(apiClient.get).mockImplementation(async (path, options) => {
      if (missing && path.startsWith("/browser-procedures/teachings/"))
        throw new ApiError(404, "PRIVATE");
      return get(path, options);
    });
    await openControls();
    await screen.findByText("This capture is unavailable to the current person and organization.");
    missing = false;
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    expect(await screen.findByRole("link", { name: "Review capture" })).toBeVisible();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("offers a GET-only refresh after its live capture polling window ends", async () => {
    vi.useFakeTimers();
    current = browserProcedureTeachingFixture({ status: "recording" });
    setup(
      <BrowserTeachingControls
        browse={browserProcedureTeachingBrowseFixture({
          teachingSessionId: ids.session,
          teachingStatus: "recording",
        })}
        canControl
      />,
    );
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Teach a browser procedure" }));
      await vi.advanceTimersByTimeAsync(5);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(181_000);
    });
    const reads = vi.mocked(apiClient.get).mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(apiClient.get).toHaveBeenCalledTimes(reads);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Check again" }));
      await vi.advanceTimersByTimeAsync(5);
    });
    expect(apiClient.get).toHaveBeenCalledTimes(reads + 1);
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it.each(["deployment", "organization", "run", "policy"] as const)(
    "explains %s admission refusal before recording",
    async (kind) => {
      if (kind === "deployment") policy.deployment_enabled = false;
      if (kind === "organization") policy.enabled = false;
      const get = vi.mocked(apiClient.get).getMockImplementation()!;
      if (kind === "run" || kind === "policy")
        vi.mocked(apiClient.get).mockImplementation(async (path, options) => {
          if (
            (kind === "run" && path.startsWith("/runs/")) ||
            (kind === "policy" && path === "/browser-teaching-policy")
          )
            throw new ApiError(403, "PRIVATE");
          return get(path, options);
        });
      await openControls(browserProcedureTeachingBrowseFixture());
      const expected =
        kind === "deployment"
          ? "Browser teaching is unavailable on this deployment."
          : kind === "organization"
            ? /Browser teaching is off for this organization/
            : "This request is unavailable. Check again to read the current state.";
      await screen.findByText(expected);
      expect(screen.getByRole("button", { name: "Start recording" })).toBeDisabled();
      expect(apiClient.post).not.toHaveBeenCalled();
    },
  );

  it("can stop an unfinished refinement through the current panel", async () => {
    current = browserProcedureTeachingFixture({ source: "refinement", status: "recording" });
    await openControls();
    await userEvent.click(await screen.findByRole("button", { name: "Stop this suggestion" }));
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Discarded")).toBeVisible();
  });

  it("coalesces immediate Pause clicks and displays a refused transition", async () => {
    current = browserProcedureTeachingFixture({ status: "recording" });
    let refuse!: () => void;
    vi.mocked(apiClient.patch).mockImplementation(
      () =>
        new Promise((_resolve, reject) => {
          refuse = () => reject(new ApiError(409, "PRIVATE"));
        }),
    );
    await openControls();
    const pause = await screen.findByRole("button", { name: "Pause recording" });
    act(() => {
      fireEvent.click(pause);
      fireEvent.click(pause);
    });
    await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(1));
    await act(async () => refuse());
    expect(
      await screen.findByText(
        "This request is unavailable. Check again to read the current state.",
      ),
    ).toBeVisible();
  });
});
