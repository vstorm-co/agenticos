import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import type { Project } from "@/types/projects";
import { CreateProjectDialog } from "./create-project-dialog";
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

const projects = {
  create: { mutateAsync: vi.fn(), isPending: false },
  list: vi.fn((): Project[] => []),
  loading: false,
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
vi.mock("@/hooks/use-projects", () => ({
  useProjects: () => ({
    projects: projects.list(),
    isLoading: projects.loading,
    create: projects.create,
  }),
  useProject: () => project,
  useProjectFiles: () => ({
    files: files.listing(),
    isLoading: false,
    error: null,
    upload: files.upload,
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

describe("ProjectChats", () => {
  it("lists the reader's chats with who answered, and starts a new one", () => {
    chats.mockReturnValue({
      chats: [
        {
          id: "c-1",
          title: "Press release",
          created_at: new Date().toISOString(),
          updated_at: null,
          agents: [{ id: "a-1", name: "Writer" }],
        },
        { id: "c-2", title: "", created_at: new Date().toISOString(), updated_at: null },
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
    expect(screen.getByText("Untitled chat")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /New chat/ })).toHaveAttribute(
      "href",
      "/chat?project=p-1",
    );
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

  it("offers no writes to a reader who cannot work in it", () => {
    wrap(<ProjectFiles project={aProject({ can_use: false })} />);
    expect(screen.queryByRole("button", { name: "Upload files" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove brief.md" })).not.toBeInTheDocument();
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

  it("shows a reader who may not change it the instructions, read-only", () => {
    wrap(<ProjectSettings project={aProject({ can_edit: false })} />);
    expect(screen.getByLabelText("Instructions")).toBeDisabled();
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

  it("holds a row while the list loads", () => {
    projects.loading = true;
    wrap(<ProjectPickerDialog open onOpenChange={vi.fn()} selectedId={null} onPick={vi.fn()} />);
    expect(screen.getByRole("button", { name: /No project/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
