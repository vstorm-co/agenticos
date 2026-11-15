import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast, type Action } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { checkAgent, finishedCheck } from "@/test-utils/skill-checks";
import type { SkillAgentUsage, SkillFork } from "@/types/skill-versions";
import { ChangeVersionDialog } from "./change-version-dialog";

const push = vi.fn();
vi.mock("next/navigation", async (original) => ({
  ...(await original<typeof import("next/navigation")>()),
  useRouter: () => ({ push }),
}));
vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), info: vi.fn(), error: vi.fn() } }));

const RETURNS: SkillFork = {
  id: "f1",
  skill_id: "s1",
  name: "Returns",
  base: { id: "m7", number: 7 },
  started_from: { id: "m7", number: 7 },
  latest: { id: "r2", number: 2 },
  changes: 2,
  behind_main: 5,
  agents: 0,
  archive_candidate: false,
  archived_at: null,
  created_at: "2026-10-30T10:00:00Z",
};

const HR: SkillAgentUsage = {
  agent: { id: "a1", name: "HR bot", slug: "hr-bot" },
  via_specialist: null,
  draft_only: false,
  binding: {
    state: "pinned",
    version: { id: "m9", number: 9, fork_id: null },
    fork: null,
    behind_main: 3,
  },
  agent_version: 4,
  environments: [],
  draft_differs: false,
  can_change: true,
  can_publish: true,
};

function renderDialog(usage: SkillAgentUsage = HR) {
  const onClose = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <ChangeVersionDialog
      skillId="s1"
      skillName="returns-policy"
      usage={usage}
      forks={[RETURNS]}
      mainLatest={12}
      seesChecks
      onClose={onClose}
    />,
    {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    },
  );
  return { onClose };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
});

describe("ChangeVersionDialog", () => {
  it("starts on the agent's current version, with nothing to change", () => {
    renderDialog();

    expect(screen.getByText("Now: v9 · pinned · 3 behind main")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Pin a main version/ })).toBeChecked();
    expect(screen.getByRole("button", { name: "Change and publish" })).toBeDisabled();
  });

  it("asks the person to accept a version never checked on the agent", async () => {
    renderDialog();

    await userEvent.click(screen.getByRole("radio", { name: "Fork “Returns”, latest" }));
    expect(
      screen.getByText("Returns v2 has not been checked on HR bot. Its answers may change."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change and publish" })).toBeDisabled();

    await userEvent.click(screen.getByLabelText("I understand, change it anyway"));
    expect(screen.getByRole("button", { name: "Change and publish" })).toBeEnabled();
  });

  it("asks nothing about a version the agent has answered with before", async () => {
    renderDialog({ ...HR, answered_with: ["r2", "m9"] });

    await userEvent.click(screen.getByRole("radio", { name: "Fork “Returns”, latest" }));

    expect(screen.queryByText(/has not been checked/)).toBeNull();
    expect(screen.getByText("HR bot has answered with Returns v2 before.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change and publish" })).toBeEnabled();
  });

  it("claims nothing about main's newest version, and changes nothing, until its page is read", async () => {
    let answer: (value: unknown) => void = () => {};
    vi.mocked(apiClient.get).mockReturnValue(new Promise((resolve) => (answer = resolve)));
    renderDialog({ ...HR, answered_with: ["m12"] });

    await userEvent.click(screen.getByRole("radio", { name: /Main, latest/ }));
    expect(screen.queryByText(/has not been checked/)).toBeNull();
    expect(screen.getByRole("button", { name: "Change and publish" })).toBeDisabled();

    answer({ items: [{ id: "m12", number: 12 }], total: 12 });
    expect(await screen.findByText("HR bot has answered with v12 before.")).toBeInTheDocument();
    expect(screen.queryByText(/has not been checked/)).toBeNull();
    expect(screen.getByRole("button", { name: "Change and publish" })).toBeEnabled();
  });

  it("says main's versions could not be read, holds the change, and reads them again", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(
      new ApiError(500, "Versions offline", {
        error: { code: "INTERNAL", message: "Versions offline" },
      }),
    );
    renderDialog({ ...HR, answered_with: ["m12"] });

    await userEvent.click(screen.getByRole("radio", { name: /Main, latest/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Versions offline");
    expect(screen.queryByText(/has not been checked/)).toBeNull();
    expect(screen.getByRole("button", { name: "Change and publish" })).toBeDisabled();

    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "m12", number: 12 }], total: 12 });
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("HR bot has answered with v12 before.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Change and publish" })).toBeEnabled();
  });

  it("reads the first page when the agent is pinned past the main version the page knows", async () => {
    renderDialog({
      ...HR,
      binding: { ...HR.binding, version: { id: "m13", number: 13, fork_id: null } },
    });

    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    const asked = vi.mocked(apiClient.get).mock.calls.map(([url]) => String(url));
    expect(asked.some((url) => url.includes("skip=-"))).toBe(false);
  });

  it("moves the agent and says which environments now serve it", async () => {
    vi.mocked(apiClient.put).mockResolvedValue({
      published: true,
      agent_version: 5,
      environments: ["Production"],
      usage: HR,
    });
    const { onClose } = renderDialog();

    await userEvent.click(screen.getByRole("radio", { name: /Main, latest/ }));
    await userEvent.click(screen.getByLabelText("I understand, change it anyway"));
    await userEvent.click(screen.getByRole("button", { name: "Change and publish" }));

    expect(apiClient.put).toHaveBeenCalledWith("/skills/s1/agents/a1/binding", { state: "main" });
    expect(toast.success).toHaveBeenCalledWith(
      "Published. The new version of HR bot now runs in “Production”.",
    );
    expect(onClose).toHaveBeenCalled();
  });

  it("moves a pinned agent to main past a check already decided, without deciding it again", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "m12", number: 12 }], total: 12 });
    vi.mocked(apiClient.put).mockResolvedValue({
      published: true,
      agent_version: 5,
      environments: ["Production"],
      usage: HR,
    });
    renderDialog({
      ...HR,
      checked_versions: [
        {
          check_id: "c7",
          version_id: "m12",
          state: "worse",
          sample: null,
          at: "2026-11-02T10:00:00Z",
        },
      ],
    });

    await userEvent.click(screen.getByRole("radio", { name: /Main, latest/ }));
    expect(await screen.findByText(/v12 was checked on HR bot .*: Worse/)).toHaveClass(
      "text-warning",
    );
    expect(screen.queryByText(/so it stays pinned/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Check first" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Change and publish" }));
    expect(apiClient.put).toHaveBeenLastCalledWith("/skills/s1/agents/a1/binding", {
      state: "main",
    });
  });

  it("returns an agent on a fork to main only once its answers changing is accepted", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "m12", number: 12 }], total: 12 });
    vi.mocked(apiClient.put).mockResolvedValue({
      published: true,
      agent_version: 5,
      environments: ["Production"],
      usage: HR,
    });
    renderDialog({
      ...HR,
      binding: {
        state: "fork",
        version: { id: "r2", number: 2, fork_id: "f1" },
        fork: { id: "f1", name: "Returns", base_number: 7, changes: 2 },
        behind_main: 5,
      },
    });

    expect(screen.getByRole("radio", { name: "Fork “Returns”, latest" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Change and publish" })).toBeDisabled();
    await userEvent.click(screen.getByRole("radio", { name: /Main, latest/ }));
    expect(
      screen.getByText("v12 has not been checked on HR bot. Its answers may change."),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Check first" })).toBeNull();
    await userEvent.click(screen.getByLabelText("I understand, change it anyway"));
    await userEvent.click(screen.getByRole("button", { name: "Change and publish" }));

    expect(apiClient.put).toHaveBeenLastCalledWith("/skills/s1/agents/a1/binding", {
      state: "main",
    });
  });

  it("keeps a pinned agent pinned when the check found main's newest version worse on it", async () => {
    const done = finishedCheck({
      id: "c9",
      source: "catch_up",
      agents: [checkAgent({ name: "HR bot", agent: { id: "a1", name: "HR bot" }, state: "worse" })],
    });
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path === "/skills/s1/checks/c9" ? done : { items: [{ id: "m12", number: 12 }], total: 12 },
    );
    vi.mocked(apiClient.post).mockImplementation(async (path: string) =>
      path.endsWith("/update-check/estimate") ? { ...done, status: undefined } : done,
    );
    renderDialog();

    await userEvent.click(screen.getByRole("radio", { name: /Main, latest/ }));
    await userEvent.click(screen.getByRole("button", { name: "Check first" }));
    await userEvent.click(await screen.findByRole("button", { name: "Start the check" }));
    await userEvent.click(await screen.findByRole("button", { name: "Back to Change version" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The check found v12 made HR bot worse, so it stays pinned.",
    );
    expect(screen.getByRole("button", { name: "Change and publish" })).toBeDisabled();
    expect(apiClient.put).not.toHaveBeenCalled();
  });

  it("checks main's newest version on a pinned agent first, then moves it with that check", async () => {
    const done = finishedCheck({
      id: "c9",
      source: "catch_up",
      agents: [
        checkAgent({ name: "HR bot", agent: { id: "a1", name: "HR bot" }, state: "better" }),
      ],
    });
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path === "/skills/s1/checks/c9" ? done : { items: [{ id: "m12", number: 12 }], total: 12 },
    );
    vi.mocked(apiClient.post).mockImplementation(async (path: string) =>
      path.endsWith("/update-check/estimate") ? { ...done, status: undefined } : done,
    );
    vi.mocked(apiClient.put).mockResolvedValue({
      published: true,
      agent_version: 5,
      environments: ["Production"],
      usage: HR,
    });
    renderDialog();

    await userEvent.click(screen.getByRole("radio", { name: /Main, latest/ }));
    await userEvent.click(screen.getByRole("button", { name: "Check first" }));
    expect(apiClient.post).toHaveBeenCalledWith("/skills/s1/agents/a1/update-check/estimate", {});
    await userEvent.click(await screen.findByRole("button", { name: "Start the check" }));
    expect(apiClient.post).toHaveBeenLastCalledWith("/skills/s1/agents/a1/update-check", {});
    await userEvent.click(await screen.findByRole("button", { name: "Back to Change version" }));

    expect(await screen.findByText(/v12 was checked on HR bot .*: Better/)).toBeVisible();
    expect(screen.queryByLabelText("I understand, change it anyway")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Change and publish" }));
    expect(apiClient.put).toHaveBeenLastCalledWith("/skills/s1/agents/a1/binding", {
      state: "main",
      check_id: "c9",
      acknowledge_unknown: false,
    });
  });

  it("still asks for the acknowledgement when the check could not measure the agent", async () => {
    const done = finishedCheck({ id: "c9", source: "catch_up", agents: [] });
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path === "/skills/s1/checks/c9" ? done : { items: [{ id: "m12", number: 12 }], total: 12 },
    );
    vi.mocked(apiClient.post).mockImplementation(async (path: string) =>
      path.endsWith("/estimate") ? finishedCheck() : done,
    );
    renderDialog();

    await userEvent.click(screen.getByRole("radio", { name: /Main, latest/ }));
    await userEvent.click(screen.getByRole("button", { name: "Check first" }));
    await userEvent.click(await screen.findByRole("button", { name: "Start the check" }));
    await userEvent.click(await screen.findByRole("button", { name: "Back to Change version" }));

    expect(await screen.findByText(/v12 was checked on HR bot .*: Unknown/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Change and publish" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Check first" })).toBeNull();
  });

  it("goes back to Change version when the check is closed before it starts", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "m12", number: 12 }], total: 12 });
    vi.mocked(apiClient.post).mockResolvedValue(finishedCheck());
    renderDialog();

    await userEvent.click(screen.getByRole("radio", { name: /Main, latest/ }));
    await userEvent.click(screen.getByRole("button", { name: "Check first" }));
    await userEvent.keyboard("{Escape}");

    expect(await screen.findByRole("button", { name: "Check first" })).toBeVisible();
  });

  it("offers no check first where only a whole line can be checked", async () => {
    renderDialog();

    await userEvent.click(screen.getByRole("radio", { name: "Fork “Returns”, latest" }));

    expect(screen.queryByRole("button", { name: "Check first" })).toBeNull();
  });

  it("asks before deciding a check run here that could not measure the agent", async () => {
    const done = finishedCheck({ id: "c8", source: "catch_up", agents: [] });
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path === "/skills/s1/checks/c8" ? done : { items: [{ id: "m12", number: 12 }], total: 12 },
    );
    vi.mocked(apiClient.post).mockImplementation(async (path: string) =>
      path.endsWith("/estimate") ? finishedCheck() : done,
    );
    vi.mocked(apiClient.put).mockResolvedValue({
      published: true,
      agent_version: 5,
      environments: ["Production"],
      usage: HR,
    });
    renderDialog();

    await userEvent.click(screen.getByRole("radio", { name: /Main, latest/ }));
    await userEvent.click(screen.getByRole("button", { name: "Check first" }));
    await userEvent.click(await screen.findByRole("button", { name: "Start the check" }));
    await userEvent.click(await screen.findByRole("button", { name: "Back to Change version" }));
    expect(await screen.findByRole("button", { name: "Change and publish" })).toBeDisabled();
    await userEvent.click(screen.getByLabelText("I understand, change it anyway"));
    await userEvent.click(screen.getByRole("button", { name: "Change and publish" }));
    expect(apiClient.put).toHaveBeenLastCalledWith("/skills/s1/agents/a1/binding", {
      state: "main",
      check_id: "c8",
      acknowledge_unknown: true,
    });
  });

  it("points to the Builder when the change could only go into the draft", async () => {
    vi.mocked(apiClient.put).mockResolvedValue({
      published: false,
      agent_version: null,
      environments: [],
      usage: HR,
    });
    renderDialog();

    await userEvent.click(screen.getByRole("radio", { name: "Fork “Returns”, latest" }));
    await userEvent.click(screen.getByLabelText("I understand, change it anyway"));
    await userEvent.click(screen.getByRole("button", { name: "Change and publish" }));

    expect(apiClient.put).toHaveBeenCalledWith("/skills/s1/agents/a1/binding", {
      state: "fork",
      fork_id: "f1",
    });
    expect(toast.info).toHaveBeenCalledWith(
      "Saved in the draft of HR bot. Publish it in the Builder.",
      expect.objectContaining({ action: expect.objectContaining({ label: "Open the Builder" }) }),
    );
  });

  it("keeps the dialog open with the refusal when the change is refused", async () => {
    vi.mocked(apiClient.put).mockRejectedValue(
      new ApiError(400, "That fork is archived", {
        error: { code: "VALIDATION", message: "That fork is archived" },
      }),
    );
    const { onClose } = renderDialog();

    await userEvent.click(screen.getByRole("radio", { name: /Main, latest/ }));
    await userEvent.click(screen.getByLabelText("I understand, change it anyway"));
    await userEvent.click(screen.getByRole("button", { name: "Change and publish" }));

    expect(await screen.findByText("That fork is archived")).toHaveAttribute("role", "alert");
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("ChangeVersionDialog's pin", () => {
  it("offers every main version, however old, newest first", async () => {
    vi.mocked(apiClient.put).mockResolvedValue({
      published: true,
      agent_version: 5,
      environments: [],
      usage: HR,
    });
    renderDialog();

    await userEvent.click(screen.getByRole("combobox", { name: "Version to pin" }));
    const options = screen.getAllByRole("option").map((option) => option.textContent);
    expect(options).toHaveLength(12);
    expect(options[0]).toBe("v12");
    expect(options.at(-1)).toBe("v1");
    await userEvent.click(screen.getByRole("option", { name: "v1" }));
    await userEvent.click(screen.getByLabelText("I understand, change it anyway"));
    await userEvent.click(screen.getByRole("button", { name: "Change and publish" }));

    expect(apiClient.put).toHaveBeenCalledWith("/skills/s1/agents/a1/binding", {
      state: "pinned",
      version: 1,
    });
    expect(toast.success).toHaveBeenCalledWith("Published. HR bot has a new version.");
  });

  it("offers no pin before main has a version", () => {
    const client = new QueryClient();
    render(
      <ChangeVersionDialog
        skillId="s1"
        skillName="returns-policy"
        usage={{ ...HR, binding: { ...HR.binding, state: "main" } }}
        forks={[]}
        mainLatest={0}
        seesChecks
        onClose={vi.fn()}
      />,
      {
        wrapper: ({ children }: { children: ReactNode }) => (
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        ),
      },
    );

    expect(screen.queryByRole("radio", { name: /Pin a main version/ })).toBeNull();
  });

  it("opens the Builder from the draft notice", async () => {
    vi.mocked(apiClient.put).mockResolvedValue({
      published: false,
      agent_version: null,
      environments: [],
      usage: HR,
    });
    renderDialog();

    await userEvent.click(screen.getByRole("radio", { name: /Main, latest/ }));
    await userEvent.click(screen.getByLabelText("I understand, change it anyway"));
    await userEvent.click(screen.getByRole("button", { name: "Change and publish" }));
    const action = vi.mocked(toast.info).mock.calls[0]?.[1]?.action as Action;
    action.onClick({} as React.MouseEvent<HTMLButtonElement>);

    expect(push).toHaveBeenCalledWith("/agents/a1");
  });

  it("closes on Escape", async () => {
    const { onClose } = renderDialog();
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
});

describe("ChangeVersionDialog without publish", () => {
  it("says the change goes into the draft, and saves it there", async () => {
    vi.mocked(apiClient.put).mockResolvedValue({
      published: false,
      agent_version: null,
      environments: [],
      usage: HR,
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <ChangeVersionDialog
        skillId="s1"
        skillName="returns-policy"
        usage={{ ...HR, can_publish: false }}
        forks={[RETURNS]}
        mainLatest={12}
        seesChecks
        onClose={vi.fn()}
      />,
      {
        wrapper: ({ children }: { children: ReactNode }) => (
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        ),
      },
    );

    expect(screen.getByText(/You may edit HR bot but not publish it/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: /Main, latest/ }));
    await userEvent.click(screen.getByLabelText("I understand, change it anyway"));
    await userEvent.click(screen.getByRole("button", { name: "Save to the draft" }));

    expect(apiClient.put).toHaveBeenCalledWith("/skills/s1/agents/a1/binding", { state: "main" });
  });
});

describe("ChangeVersionDialog's warnings", () => {
  const ON_MAIN: SkillAgentUsage = {
    ...HR,
    binding: {
      state: "main",
      version: { id: "m12", number: 12, fork_id: null },
      fork: null,
      behind_main: 0,
    },
  };

  function renderOnMain(usage = ON_MAIN, forks = [RETURNS]) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <ChangeVersionDialog
        skillId="s1"
        skillName="returns-policy"
        usage={usage}
        forks={forks}
        mainLatest={12}
        seesChecks
        onClose={vi.fn()}
      />,
      {
        wrapper: ({ children }: { children: ReactNode }) => (
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        ),
      },
    );
  }

  it("asks nothing about checks when the agent already serves the version picked", async () => {
    renderOnMain();

    await userEvent.click(screen.getByRole("radio", { name: /Pin a main version/ }));

    expect(screen.queryByText(/has not been checked/)).toBeNull();
    expect(
      screen.getByText(/HR bot stays on this version and stops getting new main/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change and publish" })).toBeEnabled();
  });

  it("says a fork lacks the main versions after its base", async () => {
    renderOnMain();

    await userEvent.click(screen.getByRole("radio", { name: "Fork “Returns”, latest" }));

    expect(
      screen.getByText(/Fork “Returns” is 5 versions behind main, so it lacks their changes/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Returns v2 has not been checked/)).toBeInTheDocument();
  });

  it("reads a fork with no version of its own as the main version it started from", async () => {
    renderOnMain(
      {
        ...ON_MAIN,
        binding: { ...ON_MAIN.binding, version: { id: "m7", number: 7, fork_id: null } },
      },
      [{ ...RETURNS, latest: null, behind_main: 1 }],
    );

    await userEvent.click(screen.getByRole("radio", { name: "Fork “Returns”, latest" }));

    expect(screen.queryByText(/has not been checked/)).toBeNull();
    expect(
      screen.getByText(/Fork “Returns” is 1 version behind main, so it lacks that change/),
    ).toBeInTheDocument();
  });

  it("dates the versions it knows and shows what one changed", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path.startsWith("/skills/s1/versions?")
        ? {
            items: [
              {
                id: "m11",
                number: 11,
                fork_id: null,
                source: "edit",
                restored_from: null,
                previous: { id: "m10", number: 10, fork_id: null },
                created_by: { id: "u1", name: "Anna" },
                created_at: "2026-11-01T10:00:00Z",
                agents: 0,
              },
              {
                id: "m10",
                number: 10,
                fork_id: null,
                source: "restore",
                restored_from: { id: "m4", number: 4, fork_id: null },
                previous: null,
                created_by: null,
                created_at: "2026-10-30T10:00:00Z",
                agents: 0,
              },
            ],
            total: 12,
          }
        : {
            id: path.split("/").pop(),
            description: "Returns.",
            content: "Refund within 30 days.",
            resources: [],
          },
    );
    renderOnMain();

    await userEvent.click(screen.getByRole("radio", { name: /Pin a main version/ }));
    await userEvent.click(screen.getByRole("combobox", { name: "Version to pin" }));
    expect(await screen.findByRole("option", { name: /^v11 · / })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "v12" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("option", { name: /^v10 · / }));
    expect(screen.getByText(/Restored from v4 · Unknown ·/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("combobox", { name: "Version to pin" }));
    await userEvent.click(screen.getByRole("option", { name: /^v11 · / }));

    expect(screen.getByText(/Edited · Anna ·/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show changes" }));
    expect(await screen.findByRole("button", { name: "Hide changes" })).toBeInTheDocument();
  });

  it("shows a version with no earlier one whole, as what it changed", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path.startsWith("/skills/s1/versions?")
        ? {
            items: [
              {
                id: "m1",
                number: 1,
                fork_id: null,
                source: "created",
                restored_from: null,
                previous: null,
                created_by: null,
                created_at: "2026-10-01T10:00:00Z",
                agents: 0,
              },
            ],
            total: 12,
          }
        : { id: "m1", description: "Returns.", content: "Refund within 30 days.", resources: [] },
    );
    renderOnMain();

    await userEvent.click(screen.getByRole("radio", { name: /Pin a main version/ }));
    await userEvent.click(screen.getByRole("combobox", { name: "Version to pin" }));
    await userEvent.click(await screen.findByRole("option", { name: /^v1 · / }));
    expect(screen.getByText(/^Created · Unknown ·/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show changes" }));

    expect(await screen.findByRole("heading", { name: "Instructions" })).toBeInTheDocument();
    expect(apiClient.get).toHaveBeenCalledWith("/skills/s1/versions/m1");
    expect(
      vi.mocked(apiClient.get).mock.calls.filter(([path]) => /\/versions\/m\d+$/.test(path)),
    ).toHaveLength(1);
  });

  it("asks again for a version picked after the last one was accepted", async () => {
    renderOnMain();

    await userEvent.click(screen.getByRole("radio", { name: /Pin a main version/ }));
    await userEvent.click(screen.getByRole("combobox", { name: "Version to pin" }));
    await userEvent.click(screen.getByRole("option", { name: "v2" }));
    await userEvent.click(screen.getByLabelText("I understand, change it anyway"));
    expect(screen.getByRole("button", { name: "Change and publish" })).toBeEnabled();
    await userEvent.click(screen.getByRole("combobox", { name: "Version to pin" }));
    await userEvent.click(screen.getByRole("option", { name: "v1" }));

    expect(screen.getByLabelText("I understand, change it anyway")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Change and publish" })).toBeDisabled();
  });

  it("reads the details of a version older than the newest page", async () => {
    const summary = (number: number) => ({
      id: `m${number}`,
      number,
      fork_id: null,
      source: "edit",
      restored_from: null,
      previous: null,
      created_by: { id: "u1", name: "Anna" },
      created_at: "2026-01-01T10:00:00Z",
      agents: 0,
    });
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path.includes("skip=100")
        ? { items: [summary(1)], total: 120 }
        : { items: [summary(120)], total: 120 },
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <ChangeVersionDialog
        skillId="s1"
        skillName="returns-policy"
        usage={ON_MAIN}
        forks={[]}
        mainLatest={120}
        seesChecks
        onClose={vi.fn()}
      />,
      {
        wrapper: ({ children }: { children: ReactNode }) => (
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        ),
      },
    );

    await userEvent.click(screen.getByRole("radio", { name: /Pin a main version/ }));
    await userEvent.click(screen.getByRole("combobox", { name: "Version to pin" }));
    await userEvent.click(screen.getByRole("option", { name: "v1" }));

    expect(await screen.findByText(/Edited · Anna ·/)).toBeInTheDocument();
  });

  it("asks nothing about a version a check already measured on the agent", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [
        {
          id: "m11",
          number: 11,
          fork_id: null,
          source: "edit",
          restored_from: null,
          previous: null,
          created_by: null,
          created_at: "2026-11-01T10:00:00Z",
          agents: 0,
        },
      ],
      total: 12,
    });
    const checked = {
      check_id: "c1",
      version_id: "m11",
      state: "better" as const,
      sample: null,
      at: "2026-11-02T10:00:00Z",
    };
    renderOnMain({ ...ON_MAIN, checked_versions: [checked] });

    await userEvent.click(screen.getByRole("radio", { name: /Pin a main version/ }));
    await userEvent.click(screen.getByRole("combobox", { name: "Version to pin" }));
    await userEvent.click(await screen.findByRole("option", { name: /^v11 · / }));

    expect(screen.getByText(/v11 was checked on HR bot .*: Better/)).toBeInTheDocument();
    expect(screen.queryByText(/has not been checked/)).toBeNull();
    expect(screen.getByRole("button", { name: "Change and publish" })).toBeEnabled();
  });

  it("does not claim a version unchecked to a reader who cannot see checks", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <ChangeVersionDialog
        skillId="s1"
        skillName="returns-policy"
        usage={ON_MAIN}
        forks={[RETURNS]}
        mainLatest={12}
        seesChecks={false}
        onClose={vi.fn()}
      />,
      {
        wrapper: ({ children }: { children: ReactNode }) => (
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        ),
      },
    );

    await userEvent.click(screen.getByRole("radio", { name: "Fork “Returns”, latest" }));

    expect(screen.queryByText(/has not been checked/)).toBeNull();
    expect(
      screen.getByText(/Whether Returns v2 was checked on HR bot is not shown to you/),
    ).toBeInTheDocument();
  });

  it("warns when a check found the version worse on the agent", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [
        {
          id: "m11",
          number: 11,
          fork_id: null,
          source: "edit",
          restored_from: null,
          previous: null,
          created_by: null,
          created_at: "2026-11-01T10:00:00Z",
          agents: 0,
        },
      ],
      total: 12,
    });
    renderOnMain({
      ...ON_MAIN,
      checked_versions: [
        {
          check_id: "c1",
          version_id: "m11",
          state: "worse",
          sample: null,
          at: "2026-11-02T10:00:00Z",
        },
      ],
    });

    await userEvent.click(screen.getByRole("radio", { name: /Pin a main version/ }));
    await userEvent.click(screen.getByRole("combobox", { name: "Version to pin" }));
    await userEvent.click(await screen.findByRole("option", { name: /^v11 · / }));

    expect(screen.getByText(/v11 was checked on HR bot .*: Worse/)).toHaveClass("text-warning");
  });
});
