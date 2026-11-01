import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ArtifactsPage from "./page";
import { apiClient } from "@/lib/api-client";
import type { Artifact } from "@/types/artifact";

/**
 * The artifacts list and its archive filter: archived pages are left out until
 * they are asked for, the choice is kept in the URL, and an archived page says so.
 * A member who may edit pages archives, restores and deletes one from its card.
 */

let params = new URLSearchParams();

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } };
});
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/apps",
  useSearchParams: () => params,
}));
let canEdit = true;
vi.mock("@/hooks", async () => {
  // The real URL state: the archive choice is kept in the address.
  const { useUrlState } =
    await vi.importActual<typeof import("@/hooks/use-url-state")>("@/hooks/use-url-state");
  return {
    useUrlState,
    useGroups: () => ({ groups: [] }),
    usePermissions: () => ({
      can: (perm: string) => perm !== "artifacts:edit" || canEdit,
      isLoading: false,
    }),
  };
});

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function page(overrides: Partial<Artifact> = {}): Artifact {
  return {
    id: "a1",
    name: "weekly-report",
    title: "Weekly report",
    visibility: "private",
    owner_user_id: "u1",
    agent_id: "ag1",
    environment_id: null,
    environment_name: null,
    public_url: null,
    live: false,
    published_at: "2026-09-22T10:00:00Z",
    current_version: null,
    archived_at: null,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

/** Answers the list by whether it asked for archived pages, and the agent filter with none. */
function serve(live: Artifact[], all: Artifact[]) {
  vi.mocked(apiClient.get).mockImplementation((path: string) => {
    if (path === "/apps/agents") return Promise.resolve({ items: [] });
    const items = path.includes("include_archived=true") ? all : live;
    return Promise.resolve({ items, total: items.length });
  });
}

function listRequests(): string[] {
  return vi
    .mocked(apiClient.get)
    .mock.calls.map(([path]) => path as string)
    .filter((path) => path.startsWith("/apps?"));
}

beforeEach(() => {
  canEdit = true;
  params = new URLSearchParams();
  window.history.replaceState({}, "", "/apps");
  vi.mocked(apiClient.get).mockReset();
  vi.mocked(apiClient.post).mockReset();
  vi.mocked(apiClient.delete).mockReset();
});

describe("the artifacts list", () => {
  it("lists archived pages only once asked, marks them, and keeps the choice in the URL", async () => {
    const archived = page({ id: "a2", title: "Old report", archived_at: "2026-10-01T00:00:00Z" });
    serve([page()], [page(), archived]);
    const user = userEvent.setup();
    render(<ArtifactsPage />, { wrapper });

    expect(await screen.findByText("Weekly report")).toBeInTheDocument();
    expect(screen.queryByText("Old report")).toBeNull();
    expect(listRequests().every((path) => !path.includes("include_archived"))).toBe(true);

    await user.click(screen.getByRole("combobox", { name: "Which artifacts" }));
    await user.click(screen.getByRole("option", { name: "Archived included" }));

    expect(await screen.findByText("Old report")).toBeInTheDocument();
    expect(screen.getByText("Archived")).toBeInTheDocument();
    expect(listRequests().at(-1)).toContain("include_archived=true");
    expect(window.location.search).toBe("?show=all");

    await user.click(screen.getByRole("combobox", { name: "Which artifacts" }));
    await user.click(screen.getByRole("option", { name: "Active artifacts" }));
    expect(window.location.search).toBe("");
  });

  it("offers the archive even when every page is archived and the list is empty", async () => {
    serve([], []);
    render(<ArtifactsPage />, { wrapper });

    expect(await screen.findByText("Nothing published yet")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Which artifacts" })).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Search apps…")).toBeNull();
  });

  it("opens on the archive when a link asks for it", async () => {
    params = new URLSearchParams("show=all");
    serve([], []);
    render(<ArtifactsPage />, { wrapper });

    await waitFor(() => expect(listRequests().at(-1)).toContain("include_archived=true"));
    expect(await screen.findByText("No app matches")).toBeInTheDocument();
  });
});

describe("a page's menu on the list", () => {
  function menuFor(title: string) {
    return screen.getByRole("button", { name: `More actions for ${title}` });
  }

  it("is not there for a member who may not edit pages", async () => {
    canEdit = false;
    serve([page()], [page()]);
    render(<ArtifactsPage />, { wrapper });

    expect(await screen.findByText("Weekly report")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /More actions/ })).toBeNull();
  });

  it("archives a page only once the archive is confirmed", async () => {
    serve([page()], [page()]);
    vi.mocked(apiClient.post).mockResolvedValue({ ...page(), archived_at: "2026-10-02T00:00:00Z" });
    const user = userEvent.setup();
    render(<ArtifactsPage />, { wrapper });

    await screen.findByText("Weekly report");
    await user.click(menuFor("Weekly report"));
    await user.click(screen.getByRole("menuitem", { name: "Archive" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Archive Weekly report?")).toBeInTheDocument();
    expect(apiClient.post).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Archive" }));

    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith("/apps/a1/archive"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    // The list is read again, so the page leaves the live list.
    await waitFor(() => expect(listRequests().length).toBeGreaterThan(1));
  });

  it("restores an archived page at once", async () => {
    params = new URLSearchParams("show=all");
    const archived = page({ archived_at: "2026-10-01T00:00:00Z" });
    serve([], [archived]);
    vi.mocked(apiClient.post).mockResolvedValue(page());
    const user = userEvent.setup();
    render(<ArtifactsPage />, { wrapper });

    await screen.findByText("Weekly report");
    await user.click(menuFor("Weekly report"));
    expect(screen.queryByRole("menuitem", { name: "Archive" })).toBeNull();
    await user.click(screen.getByRole("menuitem", { name: "Restore" }));

    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith("/apps/a1/unarchive"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("deletes a page only once the delete is confirmed", async () => {
    serve([page()], [page()]);
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<ArtifactsPage />, { wrapper });

    await screen.findByText("Weekly report");
    await user.click(menuFor("Weekly report"));
    await user.click(screen.getByRole("menuitem", { name: "Delete permanently" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Delete Weekly report?")).toBeInTheDocument();
    expect(
      within(dialog).getByText(/Every version and the public link go with it/),
    ).toBeInTheDocument();
    expect(apiClient.delete).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(apiClient.delete).toHaveBeenCalledWith("/apps/a1"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("keeps the confirm open when the server refuses the delete", async () => {
    serve([page()], [page()]);
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("refused"));
    const user = userEvent.setup();
    render(<ArtifactsPage />, { wrapper });

    await screen.findByText("Weekly report");
    await user.click(menuFor("Weekly report"));
    await user.click(screen.getByRole("menuitem", { name: "Delete permanently" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(apiClient.delete).toHaveBeenCalled());
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
