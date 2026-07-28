import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ADMIN_TABS } from "@/app/[locale]/(dashboard)/admin/admin-tabs";
import { SETTINGS_TABS } from "@/app/[locale]/(dashboard)/settings/settings-tabs";
import { NAV_GROUPS } from "./app-sidebar";
import { CommandPalette, SECTION_LABEL_KEYS } from "./command-palette";
import { apiClient } from "@/lib/api-client";

const can = vi.fn<(permission: string) => boolean>();
const currentUser = vi.fn<() => { role?: string } | null>(() => ({ role: "member" }));
const push = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can }) }));
vi.mock("@/hooks", () => ({ useAuth: () => ({ user: currentUser(), logout: vi.fn() }) }));
vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));

const ANSWERS: Record<string, unknown> = {
  "/agents": { items: [{ id: "a1", name: "Getting Started" }], total: 1 },
  "/kb": { items: [{ id: "k1", name: "E2E Handbook" }], total: 1 },
  "/conversations": { items: [{ id: "c1", title: "Refund policy" }] },
};

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** Mounted closed, then opened the way the sidebar button opens it. */
async function openPalette() {
  render(<CommandPalette />, { wrapper });
  act(() => window.dispatchEvent(new CustomEvent("command-palette:open")));
  await screen.findByRole("dialog", { name: "Command palette" });
}

beforeEach(() => {
  vi.clearAllMocks();
  can.mockReturnValue(true);
  currentUser.mockReturnValue({ role: "member" });
  vi.mocked(apiClient.get).mockImplementation((endpoint: string) =>
    endpoint in ANSWERS
      ? Promise.resolve(ANSWERS[endpoint])
      : Promise.reject(new Error(`no such endpoint in this platform: ${endpoint}`)),
  );
});

describe("the palette's destinations", () => {
  /**
   * The bug this suite exists for.
   *
   * The palette used to restate the navigation, and the restatement fell
   * behind: Agents, Skills, Activity, Vault and MCP servers were reachable from
   * the sidebar and not from ⌘K. Deriving the list is the fix; this is what
   * keeps it derived, because the next person to add a destination will add it
   * to `NAV_GROUPS` and nowhere else.
   */
  it("offers every destination the sidebar offers", async () => {
    // An admin holding everything, so the assertion covers the whole table
    // rather than the part today's default caller happens to be shown.
    currentUser.mockReturnValue({ role: "admin" });

    await openPalette();

    for (const item of NAV_GROUPS.flatMap((group) => group.items)) {
      expect(await screen.findByRole("option", { name: item.labelKey })).toBeInTheDocument();
    }
  });

  it("hides a destination the caller's role does not allow", async () => {
    // The sidebar filters these out; a palette that did not would hand a Viewer
    // the page the sidebar just declined to offer them.
    can.mockImplementation((permission) => permission !== "skills:view");

    await openPalette();

    expect(screen.queryByRole("option", { name: "skills" })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: "agents" })).toBeInTheDocument();
  });

  it("keeps the admin section for platform admins only", async () => {
    await openPalette();
    expect(screen.queryByRole("option", { name: "adminOverview" })).not.toBeInTheDocument();

    currentUser.mockReturnValue({ role: "admin" });
    await openPalette();
    expect(await screen.findByRole("option", { name: "adminOverview" })).toBeInTheDocument();
  });

  it("offers each section page exactly once", async () => {
    // `/admin` is both a primary destination and the admin section's own index.
    // Listed from both tables it appears twice, and the second one is dead
    // weight the reader has to tell apart from the first.
    currentUser.mockReturnValue({ role: "admin" });

    await openPalette();

    expect(await screen.findAllByRole("option", { name: "adminOverview" })).toHaveLength(1);
    expect(screen.getAllByRole("option", { name: "profile" })).toHaveLength(1);
  });

  it("sends the API docs to the backend that serves them", async () => {
    // The frontend has no /docs route. The old entry opened its 404 page.
    const openWindow = vi.spyOn(window, "open").mockReturnValue(null);
    await openPalette();

    act(() => screen.getByRole("option", { name: "apiDocs" }).click());

    expect(openWindow).toHaveBeenCalledWith(
      expect.stringMatching(/^https?:\/\/.+\/docs$/),
      "_blank",
      "noopener,noreferrer",
    );
  });
});

describe("the palette's named entities", () => {
  it("finds an agent by name and opens that agent", async () => {
    await openPalette();

    const agent = await screen.findByRole("option", { name: "Getting Started" });
    act(() => agent.click());

    expect(push).toHaveBeenCalledWith("/agents/a1");
  });

  it("finds a knowledge base and a conversation", async () => {
    await openPalette();

    expect(await screen.findByRole("option", { name: "E2E Handbook" })).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "Refund policy" })).toBeInTheDocument();
  });

  it("asks for nothing at all until it is opened", () => {
    // It is mounted on every page. Three requests per navigation to fill a
    // dialog nobody opened is the cost of getting this wrong.
    render(<CommandPalette />, { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("does not ask for entities the caller may not see", async () => {
    can.mockImplementation((permission) => permission !== "collections:view");

    await openPalette();

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/agents"));
    expect(vi.mocked(apiClient.get).mock.calls.map(([endpoint]) => endpoint)).not.toContain("/kb");
  });
});

describe("the section label table", () => {
  it("has a translation key for every settings and admin page", () => {
    // Without one the palette falls back to the tab's English label, which is
    // invisible until someone reads the product in Polish.
    const untranslated = [...SETTINGS_TABS, ...ADMIN_TABS]
      .map((tab) => tab.href)
      .filter((href) => !SECTION_LABEL_KEYS[href]);

    expect(untranslated).toEqual([]);
  });

  it("annotates only pages those tables actually lead to", () => {
    // A key left behind after a page moves is a row nothing reads.
    const tabbed = new Set([...SETTINGS_TABS, ...ADMIN_TABS].map((tab) => tab.href));

    expect(Object.keys(SECTION_LABEL_KEYS).filter((href) => !tabbed.has(href))).toEqual([]);
  });
});
