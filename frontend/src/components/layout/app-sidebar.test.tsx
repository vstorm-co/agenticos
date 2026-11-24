import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { scrollWithin } from "@/lib/scroll-within";
import { NAV_GROUPS, SidebarNav, isActive } from "./app-sidebar";

vi.mock("@/lib/scroll-within", () => ({ scrollWithin: vi.fn() }));

const can = vi.fn<(permission: string) => boolean>();
const currentPath = vi.fn<() => string>(() => "/dashboard");
const currentUser = vi.fn<() => { is_app_admin?: boolean } | null>(() => ({}));
const navigation = { hiddenItems: [] as string[], isLoaded: true };
const pins = { ids: [] as string[], toggle: vi.fn<(id: string) => void>() };

vi.mock("next/navigation", () => ({
  usePathname: () => currentPath(),
  // next-intl's createNavigation wraps these at module scope; see `vitest.setup.ts`.
  redirect: vi.fn(),
  permanentRedirect: vi.fn(),
}));
vi.mock("next-intl", async () => ({
  useTranslations: (await import("@/test-utils/intl")).keyTranslations(),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    can,
    hiddenNavigationItems: navigation.hiddenItems,
    isLoaded: navigation.isLoaded,
  }),
}));
vi.mock("@/hooks/use-nav-pins", () => ({
  useNavPins: () => ({ pinnedIds: pins.ids, toggle: pins.toggle }),
}));
const waiting = vi.fn<() => { id: string }[]>(() => []);
vi.mock("@/hooks/use-suggestions", () => ({ useSuggestions: () => ({ suggestions: waiting() }) }));
const connectionHealth = vi.fn<() => { total: number }>(() => ({ total: 0 }));
vi.mock("@/hooks/use-connection-health", () => ({
  useConnectionHealth: () => connectionHealth(),
}));
const approvals = vi.fn<() => number>(() => 0);
vi.mock("@/hooks/use-pending-approvals", () => ({
  usePendingApprovals: () => ({ count: approvals() }),
}));
const questions = vi.fn<() => number>(() => 0);
vi.mock("@/hooks/use-waiting-chat-questions", () => ({
  useWaitingChatQuestions: () => ({ count: questions() }),
}));
vi.mock("@/stores", () => ({
  useAuthStore: () => ({ user: currentUser() }),
  useSidebarStore: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  can.mockReturnValue(true);
  currentPath.mockReturnValue("/dashboard");
  currentUser.mockReturnValue({});
  approvals.mockReturnValue(0);
  waiting.mockReturnValue([]);
  navigation.hiddenItems = [];
  navigation.isLoaded = true;
  pins.ids = [];
  questions.mockReturnValue(0);
});

const navLabels = () =>
  within(screen.getByRole("navigation", { name: "primary" }))
    .getAllByRole("link")
    .map((link) => link.textContent);

const openMore = () => fireEvent.click(screen.getByRole("button", { name: "more" }));
const panel = () => screen.getByRole("dialog", { name: "more" });

describe("isActive", () => {
  it("lights the entry for the page you are on", () => {
    expect(isActive("/agents", "/agents")).toBe(true);
  });

  it("keeps a section lit on its detail pages", () => {
    // Otherwise opening one agent makes the sidebar claim you are nowhere.
    expect(isActive("/agents/abc-123", "/agents")).toBe(true);
  });

  it("keeps a two-letter section lit on its detail pages", () => {
    // The reported bug: the locale prefix used to be stripped by shape rather
    // than by name, so `/kb` was mistaken for a locale and eaten - leaving
    // `/5eacffcc-…`, which is inside nothing. Both the list and the detail page
    // showed a sidebar with no entry lit at all.
    expect(isActive("/kb", "/kb")).toBe(true);
    expect(isActive("/kb/5eacffcc-873e-42fe-a73a-32cd19322d00", "/kb")).toBe(true);
  });

  it("ignores the locale prefix", () => {
    // `/en/agents` and `/agents` are the same page; without this every entry
    // goes dark for anyone whose URL carries the prefix.
    expect(isActive("/en/agents", "/agents")).toBe(true);
    expect(isActive("/en/agents/abc", "/agents")).toBe(true);
    expect(isActive("/en/kb/abc", "/kb")).toBe(true);
  });

  it("does not light a section on a route that merely starts the same way", () => {
    expect(isActive("/agents-archive", "/agents")).toBe(false);
  });

  it("gives a sub-route to the entry that owns it, not to the one above it", () => {
    // The one case a prefix gets wrong, and the reason the rule is stated once
    // here rather than as a flag every future entry has to remember.
    const hrefs = ["/settings", "/settings/providers"];

    expect(isActive("/settings/providers", "/settings/providers", hrefs)).toBe(true);
    expect(isActive("/settings/providers", "/settings", hrefs)).toBe(false);
    expect(isActive("/settings/providers/openai", "/settings", hrefs)).toBe(false);
  });

  it("returns a sub-route to the entry above once nothing more specific claims it", () => {
    // Deleting the more specific entry must be enough; no second edit.
    expect(isActive("/settings/providers", "/settings", ["/settings"])).toBe(true);
    expect(isActive("/settings/profile", "/settings", ["/settings", "/settings/providers"])).toBe(
      true,
    );
  });
});

describe("SidebarNav", () => {
  it("starts with only the four fixed entries and More", () => {
    render(<SidebarNav />);

    expect(navLabels()).toEqual(["dashboard", "chat", "inbox", "agentMessages"]);
    expect(screen.getByRole("button", { name: "more" })).toBeInTheDocument();
  });

  it("shows the pinned entries in the order they were pinned, without headings", () => {
    pins.ids = ["workflows", "agents"];
    render(<SidebarNav />);

    expect(navLabels()).toEqual([
      "dashboard",
      "chat",
      "inbox",
      "agentMessages",
      "workflows",
      "agents",
    ]);
    expect(screen.queryByText("build")).toBeNull();
  });

  it("ignores pins for entries the caller may not see, unknown ids and the fixed four", () => {
    can.mockImplementation((permission) => permission !== "workflows:view");
    navigation.hiddenItems = ["skills"];
    pins.ids = ["workflows", "skills", "goneInThisBuild", "chat", "agents", "agents"];
    render(<SidebarNav />);

    expect(navLabels()).toEqual(["dashboard", "chat", "inbox", "agentMessages", "agents"]);
  });

  it("keeps the fixed entries behind the permission they need", () => {
    can.mockReturnValue(false);
    render(<SidebarNav />);

    expect(navLabels()).toEqual(["dashboard", "chat", "inbox"]);
  });

  it("keeps only recovery navigation until the role policy is known", () => {
    navigation.isLoaded = false;
    pins.ids = ["agents"];
    render(<SidebarNav />);

    expect(navLabels()).toEqual(["dashboard"]);
  });

  it("marks the current page for assistive technology", () => {
    currentPath.mockReturnValue("/en/chat");
    render(<SidebarNav />);

    expect(screen.getByRole("link", { name: "chat" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "dashboard" })).not.toHaveAttribute("aria-current");
  });

  it("scrolls the active entry into view when collapsing", () => {
    currentPath.mockReturnValue("/chat");
    render(<SidebarNav collapsed />);

    expect(scrollWithin).toHaveBeenCalledWith(
      screen.getByRole("link", { name: "chat" }),
      "nearest",
      "instant",
    );
  });

  it("shows an unpinned current page below the pins, marked, with a quick pin", () => {
    pins.ids = ["agents"];
    currentPath.mockReturnValue("/skills/abc");
    const { container } = render(<SidebarNav />);

    expect(navLabels().slice(-2)).toEqual(["agents", "skills"]);
    expect(container.querySelector("[data-unpinned]")).toContainElement(
      screen.getByRole("link", { name: "skills" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "pinItem" }));
    expect(pins.toggle).toHaveBeenCalledWith("skills");
  });

  it.each([
    ["a fixed page", "/chat", []],
    ["a pinned page", "/agents", ["agents"]],
    ["a page no entry owns", "/settings/profile", []],
  ])("shows no extra entry on %s", (_name, path, saved) => {
    pins.ids = saved;
    currentPath.mockReturnValue(path);
    const { container } = render(<SidebarNav />);

    expect(container.querySelector("[data-unpinned]")).toBeNull();
    expect(screen.queryByRole("button", { name: "pinItem" })).toBeNull();
  });

  it("does not show the current page when the caller may not see it", () => {
    can.mockReturnValue(false);
    currentPath.mockReturnValue("/agents");
    const { container } = render(<SidebarNav />);

    expect(container.querySelector("[data-unpinned]")).toBeNull();
  });

  it("draws the unpinned current page and its pin on the rail", () => {
    currentPath.mockReturnValue("/skills");
    render(<SidebarNav collapsed />);

    expect(screen.getByRole("link", { name: "skills" })).toHaveAttribute("title", "skills");
    expect(screen.getByRole("button", { name: "pinItem" })).toBeInTheDocument();
  });

  it("draws the rail as the same list without its words", () => {
    render(<SidebarNav collapsed />);

    const more = screen.getByRole("button", { name: "more" });
    expect(more).toHaveAttribute("title", "more");
    expect(more).toHaveTextContent("");
    expect(screen.getByRole("link", { name: "dashboard" })).toHaveTextContent("");
  });

  it("runs the caller's callback on navigation, so the drawer can close", () => {
    const onNavigate = vi.fn();
    render(<SidebarNav onNavigate={onNavigate} />);

    fireEvent.click(screen.getByRole("link", { name: "chat" }));
    expect(onNavigate).toHaveBeenCalledTimes(1);
  });
});

describe("the More panel", () => {
  it("lists what the caller may see, grouped as the navigation table groups it", () => {
    render(<SidebarNav />);
    openMore();

    const headings = ["apps", "build", "projects", "knowledge", "connections", "organization"];
    for (const heading of headings) expect(within(panel()).getByText(heading)).toBeInTheDocument();
    expect(within(panel()).queryByText("monitoring")).toBeNull();
    for (const entry of ["activity", "failureLearning", "backgroundWork", "skills", "groups"]) {
      expect(within(panel()).getByRole("link", { name: entry })).toBeInTheDocument();
    }
    // The fixed four are in the column, not the panel.
    expect(within(panel()).queryByRole("link", { name: "chat" })).toBeNull();
  });

  it("leaves out what permissions or the role's navigation choices hide", () => {
    can.mockImplementation((permission) => permission !== "skills:view");
    navigation.hiddenItems = ["datasets"];
    render(<SidebarNav />);
    openMore();

    expect(within(panel()).queryByRole("link", { name: "skills" })).toBeNull();
    expect(within(panel()).queryByRole("link", { name: "datasets" })).toBeNull();
    expect(within(panel()).getByRole("link", { name: "agents" })).toBeInTheDocument();
  });

  it("shows Admin last and without a heading, for platform admins only", () => {
    currentUser.mockReturnValue({ is_app_admin: true });
    const { unmount } = render(<SidebarNav />);
    openMore();

    const links = within(panel()).getAllByRole("link");
    expect(links.at(-1)).toHaveTextContent("adminOverview");
    expect(within(panel()).queryByText("admin")).toBeNull();
    unmount();

    currentUser.mockReturnValue({ is_app_admin: false });
    render(<SidebarNav />);
    openMore();
    expect(within(panel()).queryByRole("link", { name: "adminOverview" })).toBeNull();
  });

  it("pins and unpins without navigating or closing", () => {
    pins.ids = ["agents"];
    render(<SidebarNav />);
    openMore();

    fireEvent.click(within(panel()).getByRole("button", { name: "unpinItem" }));
    expect(pins.toggle).toHaveBeenLastCalledWith("agents");
    const pin = within(panel()).getAllByRole("button", { name: "pinItem" })[0]!;
    expect(pin).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(pin);
    expect(pins.toggle).toHaveBeenCalledTimes(2);
    expect(panel()).toBeInTheDocument();
  });

  it("closes on following a link and runs the callback", () => {
    const onNavigate = vi.fn();
    render(<SidebarNav onNavigate={onNavigate} />);
    openMore();

    fireEvent.click(within(panel()).getByRole("link", { name: "agents" }));
    expect(onNavigate).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes on Escape", () => {
    render(<SidebarNav />);
    openMore();

    fireEvent.keyDown(panel(), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("moves focus between entries with the arrow keys, Home and End", () => {
    render(<SidebarNav />);
    openMore();
    const links = within(panel()).getAllByRole("link");

    links[0]!.focus();
    fireEvent.keyDown(panel(), { key: "ArrowDown" });
    expect(links[1]).toHaveFocus();
    fireEvent.keyDown(panel(), { key: "ArrowUp" });
    expect(links[0]).toHaveFocus();
    fireEvent.keyDown(panel(), { key: "ArrowUp" });
    expect(links[0]).toHaveFocus();
    fireEvent.keyDown(panel(), { key: "End" });
    expect(links.at(-1)).toHaveFocus();
    fireEvent.keyDown(panel(), { key: "ArrowDown" });
    expect(links.at(-1)).toHaveFocus();
    fireEvent.keyDown(panel(), { key: "Home" });
    expect(links[0]).toHaveFocus();

    // From a pin button the row's own link is the starting point.
    within(panel()).getAllByRole("button", { name: "pinItem" })[1]!.focus();
    fireEvent.keyDown(panel(), { key: "ArrowDown" });
    expect(links[2]).toHaveFocus();
    fireEvent.keyDown(panel(), { key: "a" });
    expect(links[2]).toHaveFocus();
  });

  it("marks the current page inside the panel", () => {
    currentPath.mockReturnValue("/projects");
    render(<SidebarNav />);
    openMore();

    expect(within(panel()).getByRole("link", { name: "allProjects" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});

describe("the navigation definition", () => {
  const hrefs = NAV_GROUPS.flatMap((group) => group.items.map((item) => item.href));
  const lit = (path: string) => hrefs.filter((href) => isActive(path, href));

  it("lights exactly one entry on every destination it declares", () => {
    // Guards the real table, not a hypothetical one: a new entry that shadows an
    // existing section, or is shadowed by it, fails here rather than in a
    // browser.
    for (const href of hrefs) expect(lit(href), href).toEqual([href]);
  });

  it("lights exactly one entry on a sub-page of every destination", () => {
    for (const href of hrefs) expect(lit(`${href}/1e0a`), href).toEqual([href]);
  });

  it("lights nothing on a page no entry owns", () => {
    // /profile and /billing are reached from the account menu; claiming a
    // section for them would be a lie, not a nicety.
    expect(lit("/profile")).toEqual([]);
    expect(lit("/agents-archive")).toEqual([]);
  });

  it("has no duplicate destinations", () => {
    // Two entries pointing at one page means two of them light up at once.
    const hrefs = NAV_GROUPS.flatMap((group) => group.items.map((item) => item.href));

    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it("gives every platform destination a permission to hide behind", () => {
    // Dashboard, Chat and Organizations are open to any member by design, and so
    // is Documents: it lists the files an agent kept *for the person looking*,
    // and the backend narrows it to what they are part of - a permission here
    // would hide somebody's own files behind an operator's authority. Groups too:
    // any member reads them, because a group is what somebody shares with (#2072).
    // The inbox holds only what was brought to the person looking (#2301).
    // Everything else must state what it needs, or a Viewer is shown pages that
    // will refuse them.
    const open = new Set([
      "dashboard",
      "chat",
      "inbox",
      "backgroundWork",
      "organizations",
      "groups",
      "documents",
    ]);
    const unguarded = NAV_GROUPS.filter((group) => !group.adminOnly)
      .flatMap((group) => group.items)
      .filter((item) => !item.permission && !item.permissions && !open.has(item.labelKey));

    expect(unguarded).toEqual([]);
  });
});

describe("the inbox count (#2301)", () => {
  it("says how many wait, as a number in the column and a dot on the rail", () => {
    can.mockReturnValue(true);
    waiting.mockReturnValue([{ id: "s1" }, { id: "s2" }]);
    const { unmount } = render(<SidebarNav />);
    expect(screen.getByLabelText("inboxCount")).toHaveTextContent("2");
    unmount();

    render(<SidebarNav collapsed />);
    expect(screen.getByLabelText("inboxCount")).toBeEmptyDOMElement();
  });

  it("counts questions and approvals waiting on the reader with everything else", () => {
    can.mockReturnValue(true);
    waiting.mockReturnValue([{ id: "s1" }]);
    approvals.mockReturnValue(2);
    questions.mockReturnValue(1);
    const { unmount } = render(<SidebarNav />);
    expect(screen.getByLabelText("inboxCount")).toHaveTextContent("4");
    unmount();

    waiting.mockReturnValue([]);
    render(<SidebarNav collapsed />);
    expect(screen.getByLabelText("inboxCount")).toBeInTheDocument();
  });

  it("shows nothing when nothing waits", () => {
    can.mockReturnValue(true);
    waiting.mockReturnValue([]);
    render(<SidebarNav />);
    expect(screen.queryByLabelText("inboxCount")).toBeNull();
  });
});

describe("the connection-health badge", () => {
  it("says how many connections need attention, as a number in the column and a dot on the rail", () => {
    can.mockReturnValue(true);
    pins.ids = ["connectors"];
    connectionHealth.mockReturnValue({ total: 2 });
    const { unmount } = render(<SidebarNav />);
    expect(screen.getByLabelText("connectionHealthCount")).toHaveTextContent("2");
    unmount();

    render(<SidebarNav collapsed />);
    expect(screen.getByLabelText("connectionHealthCount")).toBeEmptyDOMElement();
  });

  it("shows nothing when every connection is healthy", () => {
    can.mockReturnValue(true);
    pins.ids = ["connectors"];
    connectionHealth.mockReturnValue({ total: 0 });
    render(<SidebarNav />);
    expect(screen.queryByLabelText("connectionHealthCount")).toBeNull();
  });
});
