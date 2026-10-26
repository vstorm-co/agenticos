import { Suspense, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Project } from "@/types/projects";
import ProjectPage from "./page";

let project: Project | null = null;
let tab = "files";
vi.mock("@/hooks/use-url-state", () => ({ useUrlState: () => [tab, vi.fn()] }));
vi.mock("@/hooks/use-projects", async () => {
  const actual =
    await vi.importActual<typeof import("@/hooks/use-projects")>("@/hooks/use-projects");
  return {
    ...actual,
    useProject: () => ({ project, isLoading: project === null, error: null }),
    useProjectFiles: () => ({
      files: null,
      isLoading: true,
      error: null,
      uploads: [],
      upload: { isPending: false },
      addFolder: {},
      remove: {},
    }),
  };
});
function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <Suspense fallback={null}>{children}</Suspense>
    </QueryClientProvider>
  );
}
type MountedPage = Pick<ReturnType<typeof render>, "container" | "rerender">;

async function mount(page: ReactNode): Promise<MountedPage> {
  let view: MountedPage | undefined;
  await act(async () => {
    view = render(page, { wrapper });
  });
  if (view === undefined) throw new Error("Project page did not mount");
  return view;
}

beforeEach(() => {
  project = null;
  tab = "files";
});

describe("project loading layout", () => {
  it.each(["files", "chats", "apps", "instructions"])(
    "keeps the selected %s tab while the project loads",
    async (selected) => {
      tab = selected;
      await mount(<ProjectPage params={Promise.resolve({ id: "p-1" })} />);
      const active = await screen.findByRole("tab", { selected: true });
      expect(active).toBeDisabled();
      expect(active).toHaveAttribute("data-state", "active");
      expect(screen.getAllByRole("tab")).toHaveLength(4);
    },
  );

  it("preserves the header and tabs while the files fill the same two-pane grid", async () => {
    const params = Promise.resolve({ id: "p-1" });
    const { container, rerender } = await mount(<ProjectPage params={params} />);
    const tabs = await screen.findByRole("tablist");
    const header = container.querySelector("h1");
    const gridClasses = Array.from(container.querySelectorAll(".grid")).map(
      (node) => node.className,
    );
    project = {
      id: "p-1",
      name: "Launch",
      description: null,
      instructions: "",
      default_agent_id: null,
      default_agent_name: null,
      owner_user_id: "me",
      visibility: "private",
      backend: "state",
      runtime: null,
      chat_count: 0,
      last_active_at: null,
      shared_groups: [],
      can_use: false,
      can_edit: false,
      created_at: null,
      updated_at: null,
    };
    rerender(<ProjectPage params={params} />);
    expect(await screen.findByRole("heading", { name: "Launch" })).toBe(header);
    expect(screen.getByRole("tablist")).toBe(tabs);
    expect(Array.from(container.querySelectorAll(".grid")).map((node) => node.className)).toEqual(
      gridClasses,
    );
  });
});
