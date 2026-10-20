import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import type { Project } from "@/types/projects";
import { CreateProjectDialog } from "./create-project-dialog";
import { ProjectApps } from "./project-apps";
import { ProjectCard } from "./project-card";
import { ProjectChats } from "./project-chats";
import { ProjectFiles } from "./project-files";
import { ProjectPickerDialog } from "./project-picker-dialog";
import { ProjectSettings } from "./project-settings";

const push = vi.fn();
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const agents = vi.fn(() => [
  {
    id: "a-1",
    slug: "writer",
    name: "Writer",
    can_run: true,
    current_version_id: "v-1",
    status: "published",
  },
  { id: "a-2", slug: "draft", name: "Draft", can_run: true, current_version_id: null },
]);
vi.mock("@/hooks", async (original) => ({
  ...(await original<typeof import("@/hooks")>()),
  useAgents: () => ({ agents: agents() }),
}));
const assistant = vi.fn((): { status: string; agent_id: string | null } | null => null);
vi.mock("@/hooks/use-assistant", () => ({ useAssistant: () => ({ assistant: assistant() }) }));

const projects = {
  create: { mutateAsync: vi.fn(), isPending: false },
  list: vi.fn((): Project[] => []),
  loading: false,
  query: vi.fn(),
};
const project = {
  update: { mutate: vi.fn(), isPending: false },
  remove: { mutateAsync: vi.fn(), isPending: false },
};
const files = {
  listing: vi.fn(),
  upload: { mutate: vi.fn(), isPending: false },
  addFolder: { mutateAsync: vi.fn(), isPending: false },
  remove: { mutateAsync: vi.fn(), isPending: false },
};
const chats = vi.fn();
const artifacts = vi.fn();
const lastArtifactsQuery = () => artifacts.mock.calls.at(-1)?.[0];
vi.mock("@/hooks/use-artifacts", () => ({
  useArtifacts: (query: unknown) => artifacts(query),
}));
vi.mock("@/components/artifacts/artifact-card", () => ({
  ArtifactCard: ({ artifact }: { artifact: { title: string } }) => <p>{artifact.title}</p>,
}));
vi.mock("@/hooks/use-projects", () => ({
  useProjects: (query: unknown) => {
    projects.query(query);
    return { projects: projects.list(), isLoading: projects.loading, create: projects.create };
  },
  useProject: () => project,
  useProjectFiles: () => ({
    files: files.listing(),
    isLoading: false,
    error: null,
    upload: files.upload,
    uploads: [],
    addFolder: files.addFolder,
    remove: files.remove,
  }),
  useProjectChats: () => chats(),
}));

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

function aProject(overrides: Partial<Project> = {}): Project {
  return {
    id: "p-1",
    name: "Launch",
    description: "The October launch",
    instructions: "Be brief.",
    default_agent_id: null,
    default_agent_name: null,
    owner_user_id: "u-1",
    visibility: "private",
    backend: "service",
    runtime: null,
    chat_count: 2,
    last_active_at: null,
    shared_groups: [],
    can_use: true,
    can_edit: true,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  projects.list.mockReturnValue([]);
  projects.loading = false;
  files.listing.mockReturnValue({
    scope: "project",
    backend: "service",
    owner_label: "This project",
    items: [{ path: "brief.md", size: 66, is_dir: false, modified_at: null }],
    total: 1,
    bytes_total: 0,
    unreadable_reason: null,
    truncated: false,
  });
  chats.mockReturnValue({ chats: [], total: 0, isLoading: false, error: null });
});

describe("ProjectCard", () => {
  it("names the project, its chats, the agent it starts with and who it reaches", () => {
    wrap(
      <ProjectCard
        project={aProject({
          default_agent_name: "Writer",
          last_active_at: new Date().toISOString(),
        })}
      />,
    );
    expect(screen.getByRole("link")).toHaveAttribute("href", "/projects/p-1");
    expect(screen.getByText("2 chats")).toBeInTheDocument();
    expect(screen.getByText("Starts with Writer")).toBeInTheDocument();
    expect(screen.getByText(/Active/)).toBeInTheDocument();
  });

  it("leaves out what a bare project does not have", () => {
    wrap(<ProjectCard project={aProject({ description: null, created_at: null })} />);
    expect(screen.queryByText(/Active/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Starts with/)).not.toBeInTheDocument();
  });
});

describe("CreateProjectDialog", () => {
  it("creates a private project with the agent chosen, and hands it back", async () => {
    const created = aProject();
    projects.create.mutateAsync.mockResolvedValue(created);
    const onCreated = vi.fn();
    wrap(<CreateProjectDialog open onOpenChange={vi.fn()} onCreated={onCreated} />);

    await userEvent.type(screen.getByLabelText("Name"), " Launch ");
    await userEvent.type(screen.getByLabelText("Description"), "Q3");
    await userEvent.type(screen.getByLabelText("Instructions"), "Be brief.");
    await userEvent.click(screen.getByLabelText("Default agent"));
    // Only a published agent the reader may run is offered.
    expect(screen.queryByRole("option", { name: /Draft/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("option", { name: /Writer/ }));
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(projects.create.mutateAsync).toHaveBeenCalledWith({
      name: "Launch",
      description: "Q3",
      instructions: "Be brief.",
      default_agent_id: "a-1",
      visibility: "private",
      group_ids: [],
      user_ids: [],
    });
    expect(onCreated).toHaveBeenCalledWith(created);
  });

  it("marks the field a refusal names, and toasts one that names none", async () => {
    projects.create.mutateAsync.mockRejectedValueOnce(
      new ApiError(422, "Bad", {
        error: {
          code: "VALIDATION_ERROR",
          message: "Bad",
          details: { fields: [{ field: "default_agent_id", message: "You cannot run it" }] },
        },
      }),
    );
    wrap(<CreateProjectDialog open onOpenChange={vi.fn()} onCreated={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("Name"), "Launch");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(await screen.findByText("You cannot run it")).toBeInTheDocument();

    projects.create.mutateAsync.mockRejectedValueOnce(new Error("down"));
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(toast.error).toHaveBeenCalled();
  });

  it("offers no assistant the organization switched off as a default", async () => {
    // Saving it is refused: a chat started with it would get no answer.
    assistant.mockReturnValue({ status: "disabled", agent_id: "a-1" });
    wrap(<CreateProjectDialog open onOpenChange={vi.fn()} onCreated={vi.fn()} />);
    await userEvent.click(screen.getByLabelText("Default agent"));
    expect(screen.queryByRole("option", { name: /Writer/ })).toBeNull();
    assistant.mockReturnValue(null);
  });

  it("closes on cancel, and choosing no default agent sends none", async () => {
    const onOpenChange = vi.fn();
    wrap(<CreateProjectDialog open onOpenChange={onOpenChange} onCreated={vi.fn()} />);
    await userEvent.click(screen.getByLabelText("Default agent"));
    await userEvent.click(screen.getByRole("option", { name: /Writer/ }));
    await userEvent.click(screen.getByLabelText("Default agent"));
    await userEvent.click(screen.getByRole("option", { name: /No default/ }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

const KACPER = { user_id: "u-1", name: "Kacper", has_avatar: false, avatar_color: null };

describe("ProjectChats", () => {
  it("lists everybody's chats with whose each is, and starts a new one", () => {
    chats.mockReturnValue({
      chats: [
        {
          id: "c-1",
          title: "Press release",
          created_at: new Date().toISOString(),
          updated_at: null,
          agents: [{ id: "a-1", slug: "writer", name: "Writer", has_avatar: false }],
          owner: KACPER,
          seen_by: [],
          working: null,
          here: [],
        },
        {
          id: "c-2",
          title: "",
          created_at: new Date().toISOString(),
          updated_at: null,
          owner: null,
          seen_by: [],
          working: null,
          here: [],
        },
      ],
      total: 2,
      isLoading: false,
      error: null,
    });
    wrap(<ProjectChats project={aProject()} />);
    expect(screen.getByRole("link", { name: /Press release/ })).toHaveAttribute(
      "href",
      "/chat?id=c-1",
    );
    // A table: whose each chat is has a column of its own.
    expect(screen.getByRole("columnheader", { name: "Started by" })).toBeInTheDocument();
    const row = screen.getByRole("row", { name: /Press release/ });
    expect(row).toHaveTextContent("Kacper");
    expect(screen.getByText("Untitled chat")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /New chat/ })).toHaveAttribute(
      "href",
      "/chat?project=p-1",
    );
  });

  it("opens a chat from its row, sorts by any column and marks one unread", async () => {
    const anna = { ...KACPER, user_id: "u-2", name: "Anna" };
    const chat = (id: string, title: string, owner: typeof KACPER | null, at: string) => ({
      id,
      title,
      created_at: at,
      updated_at: null,
      owner,
      seen_by: [],
      working: null,
      here: [],
    });
    chats.mockReturnValue({
      chats: [
        { ...chat("c-1", "Budget", KACPER, "2026-10-01T00:00:00Z"), unread: true },
        chat("c-2", "", null, "2026-10-03T00:00:00Z"),
        chat("c-3", "Agenda", anna, "2026-10-02T00:00:00Z"),
      ],
      total: 3,
      isLoading: false,
      error: null,
    });
    wrap(<ProjectChats project={aProject()} />);
    const order = () =>
      screen
        .getAllByRole("row")
        .slice(1)
        .map((row) => row.textContent ?? "");

    expect(screen.getByRole("status", { name: "New answer" })).toBeInTheDocument();
    // The title is a link of its own, so following it is not also a row click.
    await userEvent.click(screen.getByRole("link", { name: /Agenda/ }));
    expect(push).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("row", { name: /Budget/ }));
    expect(push).toHaveBeenCalledWith("/chat?id=c-1");

    for (const column of ["Chat", "Started by", "Last activity"]) {
      await userEvent.click(screen.getByRole("button", { name: column }));
      const once = order();
      await userEvent.click(screen.getByRole("button", { name: column }));
      // Turned around - a chat with no starter stays last either way.
      expect(order()).not.toEqual(once);
    }
  });

  it("offers the next page while there is one", async () => {
    const loadMore = vi.fn();
    chats.mockReturnValue({
      chats: [
        {
          id: "c-1",
          title: "Budget",
          created_at: new Date().toISOString(),
          updated_at: null,
          owner: KACPER,
          seen_by: [],
          working: null,
          here: [],
        },
      ],
      total: 120,
      isLoading: false,
      error: null,
      hasMore: true,
      loadingMore: false,
      loadMore,
    });
    wrap(<ProjectChats project={aProject()} />);
    await userEvent.click(screen.getByRole("button", { name: "Show more chats" }));
    expect(loadMore).toHaveBeenCalled();
  });

  it("says who is at work in a chat, and who has seen it", () => {
    const reader = (name: string, id: string) => ({
      ...KACPER,
      user_id: id,
      name,
      read_at: new Date().toISOString(),
    });
    chats.mockReturnValue({
      chats: [
        {
          id: "c-1",
          title: "Budget",
          created_at: new Date().toISOString(),
          updated_at: null,
          running_since: new Date().toISOString(),
          owner: KACPER,
          working: { ...KACPER, user_id: "u-2", name: "Anna" },
          seen_by: ["Anna", "Kacper", "Ola", "Piotr", "Ewa"].map((name, i) =>
            reader(name, `r-${i}`),
          ),
          here: [],
        },
      ],
      total: 1,
      isLoading: false,
      error: null,
    });
    wrap(<ProjectChats project={aProject()} />);
    expect(screen.getByText("Anna is working")).toBeInTheDocument();
    // Three faces and a count, with every name in the label.
    expect(
      screen.getByRole("img", { name: "Seen by Anna, Kacper, Ola, Piotr, Ewa" }),
    ).toBeInTheDocument();
    expect(screen.getByText("+2")).toBeInTheDocument();
  });

  it("puts who is in a chat now first, with a live dot", () => {
    const ola = { ...KACPER, user_id: "r-2", name: "Ola" };
    chats.mockReturnValue({
      chats: [
        {
          id: "c-1",
          title: "Budget",
          created_at: new Date().toISOString(),
          updated_at: null,
          owner: KACPER,
          working: null,
          seen_by: [
            { ...KACPER, user_id: "r-0", name: "Anna", read_at: new Date().toISOString() },
            { ...ola, read_at: new Date().toISOString() },
          ],
          // Ola is in it now; Zofia opened it so recently it has not counted yet.
          here: [ola, { ...KACPER, user_id: "u-9", name: "Zofia" }],
        },
      ],
      total: 1,
      isLoading: false,
      error: null,
    });
    wrap(<ProjectChats project={aProject()} />);
    const people = screen.getByRole("img", { name: /Here now: Ola, Zofia/ });
    expect(people).toHaveAccessibleName("Here now: Ola, Zofia\nSeen by Anna, Ola");
    // Three faces - Ola and Zofia, then Anna - and two of them live.
    expect(people.querySelectorAll(".bg-success")).toHaveLength(2);
    expect(screen.queryByText(/^\+/)).not.toBeInTheDocument();
  });

  it("tells a reader who cannot chat that they can read, and offers no new chat", () => {
    wrap(<ProjectChats project={aProject({ can_use: false })} />);
    expect(screen.getByText(/but not chat in it/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /New chat/ })).not.toBeInTheDocument();
  });

  it("invites a first chat, and says when the list failed", () => {
    const { unmount } = wrap(<ProjectChats project={aProject()} />);
    expect(screen.getByText(/Start one/)).toBeInTheDocument();
    unmount();

    chats.mockReturnValue({ chats: [], total: 0, isLoading: false, error: new Error("down") });
    wrap(<ProjectChats project={aProject()} />);
    expect(screen.queryByText(/Start one/)).not.toBeInTheDocument();
  });

  it("holds its place while loading", () => {
    chats.mockReturnValue({ chats: [], total: 0, isLoading: true, error: null });
    wrap(<ProjectChats project={aProject()} />);
    expect(screen.queryByText(/Start one/)).not.toBeInTheDocument();
  });
});

describe("ProjectFiles", () => {
  it("uploads picked files and folders, and clears the picker for the next pick", async () => {
    const { container } = wrap(<ProjectFiles project={aProject()} />);
    const [filesInput, folderInput] =
      container.querySelectorAll<HTMLInputElement>("input[type=file]");
    const file = new File(["a"], "a.md");
    await userEvent.upload(filesInput as HTMLInputElement, file);
    expect(files.upload.mutate).toHaveBeenCalledWith({ files: [file], folder: "" });
    await userEvent.upload(folderInput as HTMLInputElement, file);
    expect(files.upload.mutate).toHaveBeenCalledTimes(2);

    await userEvent.click(screen.getByRole("button", { name: "Upload files" }));
    await userEvent.click(screen.getByRole("button", { name: "Upload folder" }));
  });

  it("ignores a picker closed with nothing chosen", async () => {
    const { container } = wrap(<ProjectFiles project={aProject()} />);
    const input = container.querySelector<HTMLInputElement>("input[type=file]") as HTMLInputElement;
    input.dispatchEvent(new Event("change", { bubbles: true }));
    fireEvent.change(input, { target: { files: null } });
    expect(files.upload.mutate).not.toHaveBeenCalled();
  });

  it("makes a folder by name", async () => {
    files.addFolder.mutateAsync.mockResolvedValue({ path: "docs" });
    wrap(<ProjectFiles project={aProject()} />);
    await userEvent.click(screen.getByRole("button", { name: "New folder" }));
    await userEvent.type(screen.getByLabelText("Folder name"), " docs ");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(files.addFolder.mutateAsync).toHaveBeenCalledWith("docs");
    await waitFor(() => expect(screen.queryByLabelText("Folder name")).not.toBeInTheDocument());
  });

  it("closes the folder dialog on cancel", async () => {
    wrap(<ProjectFiles project={aProject()} />);
    await userEvent.click(screen.getByRole("button", { name: "New folder" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(files.addFolder.mutateAsync).not.toHaveBeenCalled();
  });

  it("removes a file once confirmed, and not before", async () => {
    files.remove.mutateAsync.mockResolvedValue(undefined);
    wrap(<ProjectFiles project={aProject()} />);
    await userEvent.click(screen.getByRole("button", { name: "Remove brief.md" }));
    expect(screen.getByText("Remove brief.md?")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(files.remove.mutateAsync).toHaveBeenCalledWith("brief.md");

    await userEvent.click(screen.getByRole("button", { name: "Remove brief.md" }));
    await userEvent.keyboard("{Escape}");
    expect(files.remove.mutateAsync).toHaveBeenCalledTimes(1);
  });

  it("opens an empty project on a place to drop its first files", async () => {
    files.listing.mockReturnValue({ ...files.listing(), items: [], total: 0 });
    wrap(<ProjectFiles project={aProject()} />);
    expect(screen.getByText("Nothing in this project yet")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Search every folder")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Upload files" }));
  });

  it("tells a reader of an empty project that files will appear", () => {
    files.listing.mockReturnValue({ ...files.listing(), items: [], total: 0 });
    wrap(<ProjectFiles project={aProject({ can_use: false })} />);
    expect(screen.getByText("Files added to the project will appear here.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Upload files" })).not.toBeInTheDocument();
  });

  it("offers no writes to a reader who cannot work in it", () => {
    wrap(<ProjectFiles project={aProject({ can_use: false })} />);
    expect(screen.queryByRole("button", { name: "Upload files" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove brief.md" })).not.toBeInTheDocument();
  });
});

describe("ProjectApps", () => {
  it("lists the apps the project's chats published, and says when there are none", () => {
    artifacts.mockReturnValue({
      artifacts: [{ id: "art-1", title: "Q3 cash report", current_version: null }],
      isLoading: false,
      error: null,
    });
    const { unmount } = wrap(<ProjectApps project={aProject()} />);
    expect(screen.getByText("Q3 cash report")).toBeInTheDocument();
    expect(lastArtifactsQuery()).toMatchObject({ projectId: "p-1" });
    unmount();

    artifacts.mockReturnValue({ artifacts: [], isLoading: false, error: null });
    wrap(<ProjectApps project={aProject()} />);
    expect(screen.getByText("No apps made in this project yet")).toBeInTheDocument();
  });

  it("pages a project with more apps than one page holds", async () => {
    artifacts.mockReturnValue({
      artifacts: [{ id: "art-1", title: "Q3 cash report", current_version: null }],
      total: 120,
      isLoading: false,
      error: null,
    });
    wrap(<ProjectApps project={aProject()} />);
    expect(lastArtifactsQuery()).toMatchObject({ skip: 0, limit: 50 });

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(lastArtifactsQuery()).toMatchObject({ skip: 50, limit: 50 });
  });

  it("holds its place while loading, and says when the list failed", () => {
    artifacts.mockReturnValue({ artifacts: [], isLoading: true, error: null });
    const { container, unmount } = wrap(<ProjectApps project={aProject()} />);
    expect(container.querySelector(".animate-pulse")).not.toBeNull();
    unmount();

    artifacts.mockReturnValue({ artifacts: [], isLoading: false, error: new Error("down") });
    wrap(<ProjectApps project={aProject()} />);
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
  });
});

describe("ProjectSettings", () => {
  it("saves what changed, trimmed", async () => {
    wrap(<ProjectSettings project={aProject()} />);
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();

    await userEvent.clear(screen.getByLabelText("Description"));
    await userEvent.type(screen.getByLabelText("Name"), " v2");
    await userEvent.type(screen.getByLabelText("Instructions"), " Cite.");
    await userEvent.click(screen.getByLabelText("Default agent"));
    await userEvent.click(screen.getByRole("option", { name: /Writer/ }));
    await userEvent.click(save);

    expect(project.update.mutate).toHaveBeenCalledWith({
      name: "Launch v2",
      description: null,
      instructions: "Be brief. Cite.",
      default_agent_id: "a-1",
    });
  });

  it("leaves a default agent it did not change alone, even one it cannot see", async () => {
    wrap(<ProjectSettings project={aProject()} />);
    await userEvent.type(screen.getByLabelText("Instructions"), " Cite.");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(project.update.mutate).toHaveBeenCalledWith({
      name: "Launch",
      description: expect.anything(),
      instructions: "Be brief. Cite.",
    });
  });

  it("deletes after the name is typed, and goes back to the list", async () => {
    project.remove.mutateAsync.mockResolvedValue(undefined);
    wrap(<ProjectSettings project={aProject({ description: null })} />);
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await userEvent.type(screen.getByRole("textbox", { name: /Launch/ }), "Launch");
    const confirms = screen.getAllByRole("button", { name: "Delete" });
    await userEvent.click(confirms[confirms.length - 1] as HTMLElement);
    expect(project.remove.mutateAsync).toHaveBeenCalled();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/projects"));
  });

  it("shows a reader who may not change it the instructions, rendered and read-only", async () => {
    wrap(<ProjectSettings project={aProject({ can_edit: false })} />);
    // Opened on the preview, as somebody who may only read them reads them.
    expect(screen.getByRole("button", { name: "Preview" })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByText(/Be brief/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Instructions" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });
});

describe("ProjectPickerDialog", () => {
  it("offers the projects the reader may work in, and no project", async () => {
    projects.list.mockReturnValue([
      aProject(),
      aProject({ id: "p-2", name: "Archive", can_use: false }),
      aProject({ id: "p-3", name: "Treasury", description: null, chat_count: 0 }),
    ]);
    const onPick = vi.fn();
    const onOpenChange = vi.fn();
    wrap(<ProjectPickerDialog open onOpenChange={onOpenChange} selectedId="p-1" onPick={onPick} />);
    expect(screen.queryByText("Archive")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Launch/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("No chats yet")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Treasury/ }));
    expect(onPick).toHaveBeenLastCalledWith(expect.objectContaining({ id: "p-3" }));
    await userEvent.click(screen.getByRole("button", { name: /No project/ }));
    expect(onPick).toHaveBeenLastCalledWith(null);
    expect(onOpenChange).toHaveBeenCalledWith(false);
    await userEvent.type(screen.getByPlaceholderText("Search projects"), "treasury");
  });

  it("asks for the projects only once it is open", () => {
    const { rerender } = wrap(
      <ProjectPickerDialog
        open={false}
        onOpenChange={vi.fn()}
        selectedId={null}
        onPick={vi.fn()}
      />,
    );
    expect(projects.query).toHaveBeenLastCalledWith(expect.objectContaining({ enabled: false }));

    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <ProjectPickerDialog open onOpenChange={vi.fn()} selectedId={null} onPick={vi.fn()} />
      </QueryClientProvider>,
    );
    expect(projects.query).toHaveBeenLastCalledWith(expect.objectContaining({ enabled: true }));
  });

  it("holds a row while the list loads", () => {
    projects.loading = true;
    wrap(<ProjectPickerDialog open onOpenChange={vi.fn()} selectedId={null} onPick={vi.fn()} />);
    expect(screen.getByRole("button", { name: /No project/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
