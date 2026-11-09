import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import type { Skill } from "@/types/providers";
import type { SkillFork } from "@/types/skill-versions";
import { EditSkillDialog } from "./edit-skill-dialog";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), info: vi.fn(), error: vi.fn() } }));
vi.mock("./skill-check-dialog", () => ({
  SkillCheckDialog: ({
    change,
    forkId,
    onApplied,
    onOpenChange,
    onLineMoved,
    onEdit,
  }: {
    change: { candidate: { content: string }; baseVersionId: string };
    forkId: string | null;
    onApplied: () => void;
    onOpenChange: (open: boolean) => void;
    onLineMoved: () => void;
    onEdit: () => void;
  }) => (
    <div>
      <p>{`checking ${change.candidate.content} over ${change.baseVersionId} on ${forkId ?? "main"}`}</p>
      <button onClick={onLineMoved}>The line moved</button>
      <button onClick={onApplied}>Apply the checked change</button>
      <button onClick={() => onOpenChange(false)}>Close the check</button>
      <button onClick={onEdit}>Edit the checked text</button>
    </div>
  ),
}));
vi.mock("@/components/sharing/share-resource-button", () => ({
  ShareResourceButton: () => null,
}));

const SKILL: Skill = {
  id: "s1",
  name: "returns-policy",
  description: "How returns are handled.",
  content: "Refund within 30 days.",
  category: null,
  version: 12,
  latest_version_id: "m12",
  can_edit: true,
  visibility: "org",
  owner_user_id: null,
  resources: [{ id: "res1", name: "form.md", description: null, size_bytes: 3 }],
};

const RETURNS: SkillFork = {
  id: "f1",
  skill_id: "s1",
  name: "Returns",
  base: { id: "m7", number: 7 },
  started_from: { id: "m7", number: 7 },
  latest: { id: "r2", number: 2 },
  changes: 2,
  behind_main: 5,
  agents: 1,
  archive_candidate: false,
  archived_at: null,
  created_at: "2026-10-30T10:00:00Z",
};

function mount(
  fork: SkillFork | null = null,
  draft?: { description: string; content: string; baseVersionId: string },
) {
  const onClose = vi.fn();
  const onDelete = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <EditSkillDialog
      skill={SKILL}
      fork={fork}
      followers={3}
      readers={["Support", "Billing"]}
      canCheck
      draft={draft}
      onClose={onClose}
      onDelete={onDelete}
    />,
    {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    },
  );
  return { onClose, onDelete };
}

const description = () => screen.getByLabelText("Description");

/** Save, and save now at the question an unchecked text change asks first. */
async function save() {
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  const now = screen.queryByRole("button", { name: "Save now" });
  if (now) await userEvent.click(now);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
    path.startsWith("/skills/s1/versions/")
      ? {
          id: path.split("/").pop(),
          description: "Returns, fork wording.",
          content: "Refund within 60 days.",
          resources: [],
        }
      : { items: [], total: 0, categories: [], suggested_categories: [] },
  );
});

describe("EditSkillDialog", () => {
  it("saves a text edit as a new main version over the one it opened on", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "m13", number: 13 });
    const { onClose } = mount();

    await userEvent.clear(description());
    await userEvent.type(description(), "When a customer returns an order.");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Saving makes v13 on main. 3 agents following main get it at once.",
    );
    await save();

    expect(apiClient.post).toHaveBeenCalledWith("/skills/s1/versions", {
      fork_id: null,
      base_version_id: "m12",
      description: "When a customer returns an order.",
      content: SKILL.content,
    });
    expect(apiClient.patch).not.toHaveBeenCalled();
    expect(toast.success).toHaveBeenCalledWith("Saved as v13.");
    expect(onClose).toHaveBeenCalled();
  });

  it("saves a category alone beside the versions, since no version holds it", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue(SKILL);
    mount();

    await userEvent.click(screen.getByLabelText("Category"));
    await userEvent.click(screen.getByRole("option", { name: "New category…" }));
    await userEvent.type(screen.getByLabelText("Category"), "support");
    await save();

    expect(apiClient.post).not.toHaveBeenCalled();
    expect(apiClient.patch).toHaveBeenCalledWith("/skills/s1", { category: "support" });
    expect(toast.success).toHaveBeenCalledWith("Saved.");
  });

  it("keeps the text when the line moved, and says why", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(409, "Concurrent change", { error: { code: "CONCURRENT_CHANGE" } }),
    );
    const { onClose } = mount();

    await userEvent.clear(description());
    await userEvent.type(description(), "Mine.");
    await save();

    expect(await screen.findByText(/Somebody saved a newer version/)).toBeInTheDocument();
    expect(description()).toHaveValue("Mine.");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("says what refused any other save", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(400, "Description too long", {
        error: { code: "VALIDATION", message: "Description too long" },
      }),
    );
    mount();

    await userEvent.clear(description());
    await userEvent.type(description(), "Mine.");
    await save();

    expect(await screen.findByText("Description too long")).toBeInTheDocument();
  });

  it("edits a fork's own text only, over the fork's newest version", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "r3", number: 3 });
    mount(RETURNS);

    expect(await screen.findByDisplayValue("Returns, fork wording.")).toBeInTheDocument();
    expect(apiClient.get).toHaveBeenCalledWith("/skills/s1/versions/r2");
    expect(screen.queryByText("form.md")).toBeNull();
    expect(screen.queryByRole("button", { name: /More actions/ })).toBeNull();
    expect(screen.getByLabelText("Category")).toHaveAttribute("readonly");

    await userEvent.clear(description());
    await userEvent.type(description(), "Fork words.");
    await save();

    expect(apiClient.post).toHaveBeenCalledWith("/skills/s1/versions", {
      fork_id: "f1",
      base_version_id: "r2",
      description: "Fork words.",
      content: "Refund within 60 days.",
    });
    expect(toast.success).toHaveBeenCalledWith("Saved as Returns v3.");
  });

  it("says when a fork's text cannot be loaded, and loads it again on request", async () => {
    let fail = true;
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path === "/skills/s1/versions/r2") {
        if (fail) throw new ApiError(500, "Versions are down");
        return { id: "r2", description: "Returns, fork wording.", content: "x", resources: [] };
      }
      return { items: [], total: 0, categories: [], suggested_categories: [] };
    });
    mount(RETURNS);

    expect(await screen.findByText("Versions are down")).toBeInTheDocument();
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Load the fork again" }));

    expect(await screen.findByDisplayValue("Returns, fork wording.")).toBeInTheDocument();
  });

  it("writes a fork's first version over the main version it serves", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "r1", number: 1 });
    mount({ ...RETURNS, latest: null, changes: 0 });

    await screen.findByDisplayValue("Returns, fork wording.");
    expect(apiClient.get).toHaveBeenCalledWith("/skills/s1/versions/m7");
    await userEvent.clear(description());
    await userEvent.type(description(), "First fork words.");
    await save();

    expect(apiClient.post).toHaveBeenCalledWith(
      "/skills/s1/versions",
      expect.objectContaining({ fork_id: "f1", base_version_id: "m7" }),
    );
  });

  it("refuses a text save when the skill has no version to write over", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <EditSkillDialog
        skill={{ ...SKILL, latest_version_id: null }}
        fork={null}
        followers={0}
        readers={[]}
        canCheck={false}
        onClose={vi.fn()}
        onDelete={vi.fn()}
      />,
      {
        wrapper: ({ children }: { children: ReactNode }) => (
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        ),
      },
    );

    await userEvent.clear(description());
    await userEvent.type(description(), "Mine.");
    await save();

    expect(screen.getByText(/no saved version to write over yet/)).toBeInTheDocument();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("closes when cancelled", async () => {
    const { onClose } = mount();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("closes on Escape", async () => {
    const { onClose } = mount();
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });

  it("saves text over the version a file written in the dialog made", async () => {
    let written = false;
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path === "/skills/s1"
        ? written
          ? { ...SKILL, version: 13, latest_version_id: "m13" }
          : SKILL
        : { items: [], total: 0, categories: [], suggested_categories: [] },
    );
    vi.mocked(apiClient.post).mockImplementation(async (path: string) => {
      if (path === "/skills/s1/resources") {
        written = true;
        return { id: "res2", name: "notes.md", description: null, size_bytes: 1 };
      }
      return { id: "m14", number: 14 };
    });
    mount();

    await userEvent.click(screen.getByRole("button", { name: "New" }));
    await userEvent.type(screen.getByLabelText("Path"), "notes.md");
    await userEvent.type(screen.getByLabelText("File contents"), "n");
    await userEvent.click(screen.getByRole("button", { name: "Add file" }));
    await screen.findByLabelText("Description");
    await userEvent.clear(description());
    await userEvent.type(description(), "With notes.");
    await save();

    expect(apiClient.post).toHaveBeenLastCalledWith(
      "/skills/s1/versions",
      expect.objectContaining({ base_version_id: "m13" }),
    );
    expect(toast.success).toHaveBeenLastCalledWith("Saved as v14.");
  });

  it("keeps its base when the written skill could not be read back", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path === "/skills/s1") throw new ApiError(500, "Down");
      return { items: [], total: 0, categories: [], suggested_categories: [] };
    });
    vi.mocked(apiClient.post).mockImplementation(async (path: string) =>
      path === "/skills/s1/resources"
        ? { id: "res2", name: "notes.md", description: null, size_bytes: 1 }
        : { id: "m13", number: 13 },
    );
    mount();

    await userEvent.click(screen.getByRole("button", { name: "New" }));
    await userEvent.type(screen.getByLabelText("Path"), "notes.md");
    await userEvent.type(screen.getByLabelText("File contents"), "n");
    await userEvent.click(screen.getByRole("button", { name: "Add file" }));
    await screen.findByLabelText("Description");
    await userEvent.clear(description());
    await userEvent.type(description(), "With notes.");
    await save();

    expect(apiClient.post).toHaveBeenLastCalledWith(
      "/skills/s1/versions",
      expect.objectContaining({ base_version_id: "m12" }),
    );
  });

  it("names the agents a text save reaches before it goes live, and goes back to editing", async () => {
    mount();

    await userEvent.clear(description());
    await userEvent.type(description(), "When a customer returns an order.");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(
      screen.getByText("It reaches 3 agents on their next run, among them Support and Billing."),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Back to editing" }));
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(description()).toHaveValue("When a customer returns an order.");
  });

  it("checks the change on the line's agents instead, and closes once it is applied", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue(SKILL);
    const { onClose } = mount();

    await userEvent.clear(description());
    await userEvent.type(description(), "When a customer returns an order.");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await userEvent.click(screen.getByRole("button", { name: "Check on agents first" }));

    expect(screen.getByText(`checking ${SKILL.content} over m12 on main`)).toBeInTheDocument();
    // The mock stands outside the editor's modal, which Radix keeps from the pointer.
    fireEvent.click(screen.getByRole("button", { name: "Close the check", hidden: true }));
    expect(screen.queryByText(/^checking/)).toBeNull();
    expect(description()).toHaveValue("When a customer returns an order.");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await userEvent.click(screen.getByRole("button", { name: "Check on agents first" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply the checked change", hidden: true }));

    expect(apiClient.post).not.toHaveBeenCalled();
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("goes back to the text it checked, still in the editor", async () => {
    mount();

    await userEvent.clear(description());
    await userEvent.type(description(), "When a customer returns an order.");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await userEvent.click(screen.getByRole("button", { name: "Check on agents first" }));
    fireEvent.click(screen.getByRole("button", { name: "Edit the checked text", hidden: true }));

    expect(screen.queryByText(/^checking/)).toBeNull();
    expect(description()).toHaveValue("When a customer returns an order.");
  });

  it("opens on a text a check brought back, saved over the version it was checked on", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "m13", number: 13 });
    mount(null, {
      description: "Returns, as checked.",
      content: "Refund within 45 days.",
      baseVersionId: "m11",
    });

    expect(description()).toHaveValue("Returns, as checked.");
    await userEvent.type(description(), " Again.");
    await save();

    expect(apiClient.post).toHaveBeenCalledWith(
      "/skills/s1/versions",
      expect.objectContaining({
        base_version_id: "m11",
        description: "Returns, as checked. Again.",
        content: "Refund within 45 days.",
      }),
    );
  });

  it("says when the category could not follow a change its check applied", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("Category refused"));
    const { onClose } = mount();

    await userEvent.click(screen.getByLabelText("Category"));
    await userEvent.click(screen.getByRole("option", { name: "New category…" }));
    await userEvent.type(screen.getByLabelText("Category"), "support");
    await userEvent.clear(description());
    await userEvent.type(description(), "When a customer returns an order.");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await userEvent.click(screen.getByRole("button", { name: "Check on agents first" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply the checked change", hidden: true }));

    expect(await screen.findByText("Category refused")).toBeInTheDocument();
    expect(apiClient.patch).toHaveBeenCalledWith("/skills/s1", { category: "support" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("says the line moved when a check refuses the text's base, and keeps the text", async () => {
    mount();

    await userEvent.clear(description());
    await userEvent.type(description(), "When a customer returns an order.");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await userEvent.click(screen.getByRole("button", { name: "Check on agents first" }));
    fireEvent.click(screen.getByRole("button", { name: "The line moved", hidden: true }));

    expect(await screen.findByText(/Somebody saved a newer version/)).toBeInTheDocument();
    expect(description()).toHaveValue("When a customer returns an order.");
  });

  it("refuses to check a text when the skill has no version to write over", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <EditSkillDialog
        skill={{ ...SKILL, latest_version_id: null }}
        fork={null}
        followers={3}
        readers={["Support"]}
        canCheck
        onClose={vi.fn()}
        onDelete={vi.fn()}
      />,
      {
        wrapper: ({ children }: { children: ReactNode }) => (
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        ),
      },
    );

    await userEvent.clear(description());
    await userEvent.type(description(), "When a customer returns an order.");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await userEvent.click(screen.getByRole("button", { name: "Check on agents first" }));

    expect(screen.getByText(/no saved version to write over/)).toBeInTheDocument();
    expect(screen.queryByText(/^checking/)).toBeNull();
  });
});
