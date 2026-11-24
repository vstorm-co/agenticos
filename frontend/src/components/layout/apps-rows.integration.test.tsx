/**
 * The sidebar's starred apps, against a mocked API: only what the caller starred
 * is listed, an empty list says how to pin one, a hover unstars a row, and the
 * section is absent without `artifacts:view`.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppsRows } from "./apps-rows";
import { apiClient } from "@/lib/api-client";
import type { Artifact } from "@/types/artifact";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } };
});
const pathname = vi.fn(() => "/en/apps");
vi.mock("next/navigation", () => ({ usePathname: () => pathname() }));
let canView = true;
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (perm: string) => perm === "artifacts:view" && canView }),
}));

function app(overrides: Partial<Artifact> = {}): Artifact {
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
    is_favourite: true,
    ...overrides,
  };
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function listRequests(): string[] {
  return vi
    .mocked(apiClient.get)
    .mock.calls.map(([path]) => String(path))
    .filter((path) => path.startsWith("/apps?"));
}

beforeEach(() => {
  vi.clearAllMocks();
  canView = true;
  pathname.mockReturnValue("/en/apps");
});

describe("sidebar starred apps", () => {
  it("asks only for favourites and lists what comes back, with All apps below", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [app(), app({ id: "a2", title: "Budget" })],
      total: 2,
    });
    const { container } = render(<AppsRows collapsed={false} />, { wrapper });

    expect(await screen.findByRole("link", { name: "Weekly report" })).toHaveAttribute(
      "href",
      "/apps/a1",
    );
    expect(screen.getByRole("link", { name: "Budget" })).toBeInTheDocument();
    expect(container.querySelector('[data-tour="nav-pinned"]')).toBeTruthy();
    expect(screen.getByRole("link", { name: "All apps" })).toHaveAttribute("href", "/apps");
    const [request] = listRequests();
    expect(request).toContain("favourites=true");
    expect(request).toContain("mine_or_shared=true");
  });

  it("says how to pin an app and links to All apps when nothing is starred", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    const { container } = render(<AppsRows collapsed={false} />, { wrapper });

    expect(
      await screen.findByText("Star an app to pin it here.", { exact: false }),
    ).toBeInTheDocument();
    expect(container.querySelector('[data-tour="nav-pinned"]')).toBeNull();
    const links = screen.getAllByRole("link", { name: "All apps" });
    expect(links.length).toBeGreaterThan(0);
    expect(links[0]).toHaveAttribute("href", "/apps");
  });

  it("unstars a row from its hover star", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [app()], total: 1 });
    vi.mocked(apiClient.delete).mockResolvedValue(app({ is_favourite: false }));
    render(<AppsRows collapsed={false} />, { wrapper });

    await screen.findByRole("link", { name: "Weekly report" });
    await userEvent.click(
      screen.getByRole("button", { name: "Remove Weekly report from favourites" }),
    );

    await waitFor(() => expect(apiClient.delete).toHaveBeenCalledWith("/apps/a1/favourite"));
  });

  it("keeps a nested app route active and lets keyboard users unstar it", async () => {
    pathname.mockReturnValue("/en/apps/a1/data");
    vi.mocked(apiClient.get).mockResolvedValue({ items: [app()], total: 1 });
    vi.mocked(apiClient.delete).mockResolvedValue(app({ is_favourite: false }));
    const user = userEvent.setup();
    render(<AppsRows collapsed={false} />, { wrapper });

    const appLink = await screen.findByRole("link", { name: "Weekly report" });
    expect(appLink).toHaveAttribute("aria-current", "page");
    await user.tab();
    await user.tab();
    expect(
      screen.getByRole("button", { name: "Remove Weekly report from favourites" }),
    ).toHaveFocus();
    await user.keyboard("{Enter}");

    await waitFor(() => expect(apiClient.delete).toHaveBeenCalledWith("/apps/a1/favourite"));
  });

  it("draws nothing without artifacts:view and asks for nothing", () => {
    canView = false;
    const { container } = render(<AppsRows collapsed={false} />, { wrapper });

    expect(container).toBeEmptyDOMElement();
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("collapsed, shows the icons only and no unstar control", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [app()], total: 1 });
    render(<AppsRows collapsed />, { wrapper });

    expect(await screen.findByRole("link", { name: "Weekly report" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Remove Weekly report from favourites" }),
    ).not.toBeInTheDocument();
  });
});
