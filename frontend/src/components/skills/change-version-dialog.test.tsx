import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast, type Action } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
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

function renderDialog() {
  const onClose = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <ChangeVersionDialog
      skillId="s1"
      skillName="returns-policy"
      usage={HR}
      forks={[RETURNS]}
      mainLatest={12}
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
      screen.getByText("This version has not been checked on HR bot. Its answers may change."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change and publish" })).toBeDisabled();

    await userEvent.click(screen.getByLabelText("I understand, change it anyway"));
    expect(screen.getByRole("button", { name: "Change and publish" })).toBeEnabled();
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
      "Published. Production now serves the new version of HR bot.",
    );
    expect(onClose).toHaveBeenCalled();
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
