/**
 * The conversation sidebar's filters, against a mocked API.
 *
 * What is worth pinning here is the half a unit test cannot see: that typing in
 * the box produces a *request* rather than a slice of the rows already on
 * screen, that the choice survives a reload because it is written to the URL,
 * and that an empty list says which of three things happened.
 *
 * The tab counts are gone rather than fixed, and one test says so. The pair that
 * used to sit there counted the pages fetched so far, so "Active 8 · Archived 2"
 * was what a deployment holding hundreds reported.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConversationSidebar } from "./conversation-sidebar";
import { apiClient } from "@/lib/api-client";
import {
  useAgentSelectionStore,
  useChatBandsStore,
  useConversationStore,
  useWorkingStore,
} from "@/stores";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
// The trigger split menu gates on whether any agent is runnable (`can_run`), not
// on the role - so a runnable one in this list is what makes the menu render. A
// gating suite below flips it to prove the menu tracks that signal.
let mockAgents: Array<{ id: string; name: string; status: string; can_run: boolean }> = [];
vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({ agents: mockAgents }),
}));
vi.mock("@/components/agents/agent-avatar", () => ({
  AgentAvatar: ({ name }: { name: string }) => <span>{name}</span>,
}));
vi.mock("@/components/agents/conversation-agents", () => ({
  ConversationAgents: ({ agents }: { agents: Array<{ name: string }> }) => (
    <span data-testid="row-agents">{agents.map((agent) => agent.name).join(", ")}</span>
  ),
}));
// The event path is the portal grid, covered by the portal tests; stubbed here so
// the sidebar menu's own job - opening it - is what this suite checks.
vi.mock("@/components/triggers/new-event-trigger-dialog", () => ({
  NewEventTriggerDialog: ({ open }: { open: boolean }) =>
    open ? <div role="dialog" aria-label="New event trigger" /> : null,
}));

let urlParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useSearchParams: () => urlParams,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/chat",
}));

function conversation(id: string, title: string, favourite = false) {
  return {
    id,
    title,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    is_archived: false,
    is_favourite: favourite,
    agents: [],
  };
}

/** Whatever the list route should answer with next. */
function serve(items: ReturnType<typeof conversation>[], total = items.length) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path.includes("/messages")) return { items: [], total: 0 };
    // The trigger-menu gate sweeps /agents itself for a runnable one.
    if (path === "/agents") return { items: mockAgents, total: mockAgents.length };
    return { items, total };
  });
}

/** Every conversation-list request made so far, newest last. */
function listRequests(): string[] {
  return vi
    .mocked(apiClient.get)
    .mock.calls.map(([path]) => path as string)
    .filter((path) => !path.includes("/messages") && path !== "/agents");
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(<ConversationSidebar />, { wrapper });
}

/** The desktop list. `ConversationSidebar` also renders a mobile sheet. */
function list(): HTMLElement {
  return screen.getAllByRole("complementary")[0] as HTMLElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  urlParams = new URLSearchParams();
  window.history.replaceState({}, "", "/chat");
  useConversationStore.getState().reset();
  useWorkingStore.getState().reset();
  useChatBandsStore.setState({ folded: [], opened: [] });
  mockAgents = [{ id: "a-1", name: "Analyst", status: "published", can_run: true }];
  serve([conversation("c-1", "Quarterly numbers")]);
});

describe("the list the URL asks for", () => {
  it("starts from the URL it was given", async () => {
    urlParams = new URLSearchParams("agent=a-1&sort=title:asc&view=archived");
    mount();

    await waitFor(() => {
      const request = listRequests().at(-1) ?? "";
      expect(request).toContain("agent_id=a-1");
      expect(request).toContain("sort_by=title&sort_dir=asc");
      expect(request).toContain("archived_only=true");
    });
  });

  it("ignores a sort the route would refuse", async () => {
    // `owner` sorts the admin listing and is the plausible hand-typed guess.
    // Passed through it would answer 422 and the sidebar would show nothing.
    urlParams = new URLSearchParams("sort=owner");
    mount();

    await waitFor(() => expect(listRequests().at(-1)).toContain("sort_by=updated_at"));
  });
});

describe("a link to another thread followed from this page", () => {
  it("opens the thread the address now names", async () => {
    // A notification's link is a same-page navigation: nothing remounts (#2108).
    urlParams = new URLSearchParams("id=c-1");
    window.history.replaceState({}, "", "/chat?id=c-1");
    serve([conversation("c-1", "First one"), conversation("c-2", "Answered while away")]);
    const { rerender } = mount();
    await screen.findAllByText("First one");
    await waitFor(() => expect(useConversationStore.getState().currentConversationId).toBe("c-1"));

    urlParams = new URLSearchParams("id=c-2");
    rerender(<ConversationSidebar />);

    await waitFor(() => expect(useConversationStore.getState().currentConversationId).toBe("c-2"));
  });
});

describe("what the sidebar says about the list", () => {
  it("says a thread is at work, in place of when it last moved", async () => {
    serve([
      {
        ...conversation("c-1", "Busy one"),
        running_since: new Date(Date.now() - 12_000).toISOString(),
      },
      conversation("c-2", "Quiet one"),
    ] as unknown as ReturnType<typeof conversation>[]);
    mount();
    await screen.findAllByText("Busy one");

    const busy = within(list()).getByText("Busy one").closest("[class*='group']") as HTMLElement;
    expect(within(busy).getByText(/Working/)).toBeInTheDocument();
    const quiet = within(list()).getByText("Quiet one").closest("[class*='group']") as HTMLElement;
    expect(within(quiet).queryByText(/Working/)).toBeNull();
  });

  it("says a thread is at work the moment this tab asks in it, before the server does", async () => {
    // A turn of a few seconds can start and end between two listings, or while
    // the live-update socket reconnects; the tab that asked knows (#2108).
    useWorkingStore.getState().start("c-2", new Date(Date.now() - 3_000).toISOString());
    serve([conversation("c-1", "Other one"), conversation("c-2", "Just asked")]);
    mount();
    await screen.findAllByText("Just asked");

    const asked = within(list()).getByText("Just asked").closest("[class*='group']") as HTMLElement;
    expect(within(asked).getByText(/Working/)).toBeInTheDocument();
    const other = within(list()).getByText("Other one").closest("[class*='group']") as HTMLElement;
    expect(within(other).queryByText(/Working/)).toBeNull();

    act(() => useWorkingStore.getState().stop("c-2"));
    expect(within(asked).queryByText(/Working/)).toBeNull();
  });

  it("hands a thread this tab left mid-answer to the listing once it has the run", async () => {
    useWorkingStore.getState().start("c-2", new Date(Date.now() - 3_000).toISOString());
    useWorkingStore.getState().handOff("c-2");
    serve([
      {
        ...conversation("c-2", "Left mid-answer"),
        running_since: new Date(Date.now() - 3_000).toISOString(),
      },
    ] as unknown as ReturnType<typeof conversation>[]);
    mount();
    await screen.findAllByText("Left mid-answer");

    await waitFor(() => expect(useWorkingStore.getState().handedOff).toEqual({}));
    expect(useWorkingStore.getState().since).toEqual({});
    const row = within(list())
      .getByText("Left mid-answer")
      .closest("[class*='group']") as HTMLElement;
    expect(within(row).getByText(/Working/)).toBeInTheDocument();
  });

  it("lets a handed-off mark go when the listing never shows the run", async () => {
    // A turn short enough to end between two listings: after the grace, the
    // listing that says nothing is running is right.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      useWorkingStore.getState().start("c-2", new Date(Date.now() - 3_000).toISOString());
      useWorkingStore.getState().handOff("c-2");
      serve([conversation("c-2", "Quick one")]);
      mount();
      await screen.findAllByText("Quick one");
      const row = within(list()).getByText("Quick one").closest("[class*='group']") as HTMLElement;
      expect(within(row).getByText(/Working/)).toBeInTheDocument();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(20_000);
      });

      expect(within(row).queryByText(/Working/)).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("marks a thread with an answer the reader has not seen, but not the open one", async () => {
    useConversationStore.getState().setCurrentConversationId("c-2");
    serve([
      { ...conversation("c-1", "New answer here"), unread: true },
      { ...conversation("c-2", "Open one"), unread: true },
      conversation("c-3", "Seen one"),
    ] as unknown as ReturnType<typeof conversation>[]);
    mount();
    await screen.findAllByText("New answer here");

    const row = (title: string) =>
      within(list()).getByText(title).closest("[class*='group']") as HTMLElement;
    expect(within(row("New answer here")).getByRole("status", { name: "New answer" })).toBeTruthy();
    expect(within(row("Open one")).queryByRole("status", { name: "New answer" })).toBeNull();
    expect(within(row("Seen one")).queryByRole("status", { name: "New answer" })).toBeNull();
  });

  it("reads the plain list by day, with no count over it", async () => {
    serve(
      [
        { ...conversation("c-1", "This morning"), updated_at: new Date().toISOString() },
        conversation("c-2", "Back in July"),
      ] as unknown as ReturnType<typeof conversation>[],
      214,
    );
    mount();
    await screen.findAllByText("This morning");

    expect(within(list()).getByText("Today")).toBeInTheDocument();
    expect(within(list()).getByText("Older")).toBeInTheDocument();
    expect(within(list()).queryByText("214 conversations")).toBeNull();
  });

  it("files the threads started in a project under it, above the days", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path.includes("/messages")) return { items: [], total: 0 };
      if (path === "/agents") return { items: [], total: 0 };
      if (path.startsWith("/projects"))
        return { items: [{ id: "p-1", name: "Q3 launch" }], total: 1 };
      return {
        items: [
          { ...conversation("c-1", "Press release"), project_id: "p-1" },
          { ...conversation("c-2", "Old brief"), project_id: "p-gone" },
          { ...conversation("c-3", "Lunch ideas"), updated_at: new Date().toISOString() },
        ],
        total: 3,
      };
    });
    mount();
    await screen.findAllByText("Press release");

    const headings = within(list())
      .getAllByRole("button", { expanded: true })
      .map((heading) => heading.textContent);
    // Each project heading carries its initial's tile before the name.
    expect(headings.slice(0, 3)).toEqual(["QQ3 launch", "AA project", "Today"]);
  });

  it("keeps one run, without days, in an order that is not by date", async () => {
    urlParams = new URLSearchParams("sort=title:asc");
    serve([
      { ...conversation("c-1", "Alpha"), updated_at: new Date().toISOString() },
    ] as unknown as ReturnType<typeof conversation>[]);
    mount();
    await screen.findAllByText("Alpha");

    expect(within(list()).queryByText("Today")).toBeNull();
  });

  it("distinguishes an empty deployment from an empty filter", async () => {
    serve([]);
    mount();

    expect(await screen.findAllByText("No conversations yet")).not.toHaveLength(0);
    expect(screen.queryByText("Nothing matches")).not.toBeInTheDocument();
  });

  it("offers a way out of a filter that matches nothing", async () => {
    urlParams = new URLSearchParams("agent=a-1");
    serve([]);
    mount();
    await screen.findAllByText("Nothing matches");

    serve([conversation("c-1", "Quarterly numbers")]);
    await userEvent.click(within(list()).getAllByRole("button", { name: "Clear filters" })[0]!);

    expect((await screen.findAllByText("Quarterly numbers"))[0]).toBeVisible();
    await waitFor(() => expect(window.location.search).not.toContain("agent="));
  });

  it("says the archive is empty rather than that nothing matched", async () => {
    serve([]);
    mount();

    await userEvent.click(within(list()).getByRole("button", { name: "Filter and sort" }));
    await userEvent.click(screen.getByRole("button", { name: "Archived" }));

    expect((await screen.findAllByText("No archived conversations"))[0]).toBeVisible();
    await waitFor(() => expect(listRequests().at(-1)).toContain("archived_only=true"));
  });
});

/**
 * The sidebar as a 48px rail.
 *
 * It used to hold expand and new-chat and nothing else, so collapsing it gave up
 * everything except the width - reaching yesterday's thread meant expanding,
 * clicking and collapsing again, which is why nobody collapsed it. What it holds
 * now has to actually work from the rail, and that is what these pin.
 */
describe("the collapsed rail", () => {
  /** Mount, collapse the desktop sidebar, and hand back the rail. */
  async function collapse(): Promise<HTMLElement> {
    mount();
    await screen.findAllByRole("button", { name: "Collapse conversations sidebar" });
    await userEvent.click(
      within(list()).getByRole("button", { name: "Collapse conversations sidebar" }),
    );
    // The chevron sits in the rail's header, one level under the rail itself.
    return screen.getByRole("button", { name: "Expand conversations sidebar" }).parentElement!
      .parentElement as HTMLElement;
  }

  it("offers the recent threads, named, without expanding", async () => {
    serve([conversation("c-1", "Quarterly numbers"), conversation("c-2", "Refund policy")]);

    const rail = await collapse();

    expect(within(rail).getByRole("button", { name: "Quarterly numbers" })).toBeVisible();
    expect(within(rail).getByRole("button", { name: "Refund policy" })).toBeVisible();
  });

  it("opens a thread from the rail", async () => {
    serve([conversation("c-1", "Quarterly numbers"), conversation("c-2", "Refund policy")]);
    const rail = await collapse();

    await userEvent.click(within(rail).getByRole("button", { name: "Refund policy" }));

    await waitFor(() => expect(useConversationStore.getState().currentConversationId).toBe("c-2"));
  });

  it("marks the thread that is open", async () => {
    serve([conversation("c-1", "Quarterly numbers")]);
    const rail = await collapse();

    await userEvent.click(within(rail).getByRole("button", { name: "Quarterly numbers" }));

    await waitFor(() =>
      expect(within(rail).getByRole("button", { name: "Quarterly numbers" })).toHaveAttribute(
        "aria-current",
        "true",
      ),
    );
  });

  it("names an untitled thread rather than showing a blank button", async () => {
    serve([{ ...conversation("c-1", ""), title: undefined } as never]);

    const rail = await collapse();

    expect(await within(rail).findByRole("button", { name: "New conversation" })).toBeVisible();
  });

  it("switches to the archive through the same filters the list has", async () => {
    const rail = await collapse();

    await userEvent.click(within(rail).getByRole("button", { name: "Filter and sort" }));
    await userEvent.click(await screen.findByRole("button", { name: "Archived" }));

    await waitFor(() => expect(listRequests().at(-1)).toContain("archived_only=true"));
    expect(await within(rail).findByRole("img", { name: "Archived" })).toBeVisible();
  });

  it("keeps the list's bands, its order and its unread dot", async () => {
    serve([
      conversation("c-1", "Quarterly numbers", true),
      { ...conversation("c-2", "Refund policy"), unread: true } as never,
    ]);
    const rail = await collapse();

    const unread = await within(rail).findByRole("button", { name: "Unread" });
    const favourites = within(rail).getByRole("button", { name: "Favourites" });
    const refund = within(rail).getByRole("button", { name: "Refund policy" });
    const numbers = within(rail).getByRole("button", { name: "Quarterly numbers" });
    // Unread leads, as it does in the list, then the starred run.
    expect(unread.compareDocumentPosition(refund) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(
      refund.compareDocumentPosition(favourites) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      favourites.compareDocumentPosition(numbers) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(within(refund).getByRole("status", { name: "New answer" })).toBeInTheDocument();
  });

  it("folds a band from the rail, the same setting the list keeps", async () => {
    serve([conversation("c-1", "Quarterly numbers", true)]);
    const rail = await collapse();

    await userEvent.click(await within(rail).findByRole("button", { name: "Favourites" }));

    expect(within(rail).queryByRole("button", { name: "Quarterly numbers" })).toBeNull();
    expect(useChatBandsStore.getState().folded).toContain("favourites");
  });

  it("searches from the rail in the same window", async () => {
    const rail = await collapse();

    await userEvent.click(within(rail).getByRole("button", { name: "Search conversations" }));

    expect(await screen.findByRole("dialog", { name: "Search conversations" })).toBeVisible();
  });
});

describe("the three icons over the list", () => {
  it("starts a chat from the first, with no menu under it", async () => {
    mount();
    await screen.findAllByText("Quarterly numbers");

    await userEvent.click(within(list()).getByRole("button", { name: "New chat" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("searches the server from a window, and opens the pick", async () => {
    mount();
    await screen.findAllByText("Quarterly numbers");

    await userEvent.click(within(list()).getByRole("button", { name: "Search conversations" }));
    const dialog = await screen.findByRole("dialog", { name: "Search conversations" });
    expect(within(dialog).getByText("Type to search your conversations by title.")).toBeVisible();

    serve([conversation("c-9", "Refund policy")]);
    await userEvent.type(within(dialog).getByRole("textbox"), "refund");
    await waitFor(() => expect(listRequests().at(-1)).toContain("search=refund"));
    await userEvent.click(await within(dialog).findByRole("button", { name: /Refund policy/ }));

    await waitFor(() => expect(useConversationStore.getState().currentConversationId).toBe("c-9"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("says when nothing matches the search", async () => {
    mount();
    await screen.findAllByText("Quarterly numbers");
    await userEvent.click(within(list()).getByRole("button", { name: "Search conversations" }));
    const dialog = await screen.findByRole("dialog", { name: "Search conversations" });

    serve([]);
    await userEvent.type(within(dialog).getByRole("textbox"), "nothing");

    expect(await within(dialog).findByText("No conversation matches.")).toBeVisible();
  });
});

describe("the favourites band", () => {
  /**
   * The server puts the starred threads first - it has to, because the list is
   * paged - so what the sidebar owns is reading that run off the front and
   * heading it. A filter over the page would be a different feature: it would
   * find only the favourites that happened to be on the page already (#929).
   */
  it("heads the starred run and leaves the rest unheaded", async () => {
    serve([
      conversation("c-1", "Rota cover", true),
      conversation("c-2", "Refund policy"),
      conversation("c-3", "Quarterly numbers"),
    ]);
    mount();

    const heading = await within(list()).findByText("Favourites");
    expect(heading).toBeVisible();
    // One band heading, not two: the rest of the list keeps the count it always
    // had, and "Everything else" would be a label on the absence of a label.
    expect(within(list()).getAllByText("Favourites")).toHaveLength(1);
  });

  it("says nothing about favourites when there are none", async () => {
    serve([conversation("c-1", "Refund policy")]);
    mount();

    expect(await within(list()).findByText("Refund policy")).toBeVisible();
    expect(within(list()).queryByText("Favourites")).toBeNull();
  });

  it("stars a thread from the menu, which is the only place it is offered", async () => {
    // There is no star button on an unstarred row any more. It was a second
    // control for what this menu already does, and an `opacity-0` button still
    // takes its width - so every title in the list was eight characters
    // shorter to show a duplicate nobody was looking at.
    serve([conversation("c-1", "Refund policy")]);
    vi.mocked(apiClient.post).mockResolvedValue({});
    mount();
    await within(list()).findByText("Refund policy");

    expect(within(list()).queryByRole("button", { name: "Favourite" })).toBeNull();

    await userEvent.click(within(list()).getByRole("button", { name: "Conversation actions" }));
    await userEvent.click(within(list()).getByRole("button", { name: "Favourite" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/conversations/c-1/favourite", {}),
    );
  });

  it("offers no share on a project's chat - the project decides who reads it", async () => {
    serve([
      { ...conversation("c-1", "Launch plan"), project_id: "p-1" },
      conversation("c-2", "My notes"),
    ] as ReturnType<typeof conversation>[]);
    mount();
    await within(list()).findByText("Launch plan");

    const [inProject, ownChat] = within(list()).getAllByRole("button", {
      name: "Conversation actions",
    });
    await userEvent.click(inProject!);
    expect(within(list()).queryByRole("button", { name: "Share" })).toBeNull();
    await userEvent.click(ownChat!);
    expect(within(list()).getByRole("button", { name: "Share" })).toBeInTheDocument();
  });

  it("draws no star on a starred row, since the band it sits in says so", async () => {
    serve([conversation("c-1", "Rota cover", true)]);
    mount();
    await within(list()).findByText("Rota cover");

    expect(within(list()).getByText("Favourites")).toBeInTheDocument();
    expect(within(list()).queryByRole("button", { name: "Remove from favourites" })).toBeNull();
  });

  it("removes a favourite from the row's menu", async () => {
    serve([conversation("c-1", "Rota cover", true)]);
    vi.mocked(apiClient.delete).mockResolvedValue({});
    mount();
    await within(list()).findByText("Rota cover");

    await userEvent.click(within(list()).getByRole("button", { name: "Conversation actions" }));
    await userEvent.click(within(list()).getByRole("button", { name: /Remove from favourites/ }));

    await waitFor(() =>
      expect(apiClient.delete).toHaveBeenCalledWith("/conversations/c-1/favourite"),
    );
  });

  it("folds a band to its heading, saying how many it holds", async () => {
    serve([conversation("c-1", "Rota cover", true), conversation("c-2", "Shift swap", true)]);
    mount();
    await within(list()).findByText("Rota cover");

    await userEvent.click(within(list()).getByRole("button", { name: /Favourites/ }));
    expect(within(list()).queryByText("Rota cover")).toBeNull();
    expect(within(list()).getByRole("button", { name: /Favourites/ })).toHaveTextContent("2");

    await userEvent.click(within(list()).getByRole("button", { name: /Favourites/ }));
    expect(within(list()).getByText("Rota cover")).toBeInTheDocument();
  });

  it("asks for the next page while the list does not fill the column", async () => {
    // Folded bands leave nothing to scroll, and scrolling was the only thing
    // that asked for more - so Yesterday never arrived.
    serve(Array.from({ length: 30 }, (_, i) => conversation(`c-${i}`, `Thread ${i}`)));
    mount();
    await within(list()).findByText("Thread 0");

    await waitFor(() => expect(listRequests().some((path) => path.includes("skip=30"))).toBe(true));
  });

  it("keeps a short list open, older bands and all", async () => {
    // Nothing from the last two days and eight older threads: the list used to
    // open onto "Previous 30 days" and "Older", both folded, and no thread.
    const old = (id: string, days: number) => ({
      ...conversation(id, `Thread ${id}`),
      updated_at: new Date(Date.now() - days * 86_400_000).toISOString(),
    });
    serve([old("a", 10), old("b", 12), old("c", 90)] as unknown as ReturnType<
      typeof conversation
    >[]);
    mount();

    expect(await within(list()).findByText("Thread a")).toBeVisible();
    expect(within(list()).getByText("Thread c")).toBeVisible();
  });

  it("folds the older bands on a long list, but never the newest band", async () => {
    const old = (id: string, days: number) => ({
      ...conversation(id, `Thread ${id}`),
      updated_at: new Date(Date.now() - days * 86_400_000).toISOString(),
    });
    serve(
      Array.from({ length: 25 }, (_, i) => old(`m${i}`, i < 5 ? 10 : 90)) as unknown as ReturnType<
        typeof conversation
      >[],
    );
    mount();

    // The newest band - Previous 30 days here - stays open; Older folds.
    expect(await within(list()).findByText("Thread m0")).toBeVisible();
    expect(within(list()).queryByText("Thread m10")).toBeNull();
    expect(within(list()).getByRole("button", { name: /Older/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("opens the band the open conversation lands in, once", async () => {
    useChatBandsStore.setState({ folded: ["today"], opened: [] });
    useConversationStore.getState().setCurrentConversationId("c-1");
    serve([
      { ...conversation("c-1", "Just started"), updated_at: new Date().toISOString() },
    ] as unknown as ReturnType<typeof conversation>[]);
    mount();

    expect(await within(list()).findByText("Just started")).toBeInTheDocument();
    expect(useChatBandsStore.getState().folded).toEqual([]);

    // Folding it again afterwards is the reader's choice, and it stays.
    await userEvent.click(within(list()).getByRole("button", { name: /Today/ }));
    expect(within(list()).queryByText("Just started")).toBeNull();
  });

  it("leads with the threads holding an answer not yet seen", async () => {
    serve([
      conversation("c-1", "Starred and new", true),
      { ...conversation("c-2", "New answer"), unread: true },
      { ...conversation("c-3", "Starred and new too", true), unread: true },
    ] as unknown as ReturnType<typeof conversation>[]);
    mount();
    await within(list()).findByText("New answer");

    const headings = within(list())
      .getAllByText(/^(Unread|Favourites)$/)
      .map((heading) => heading.textContent);
    expect(headings).toEqual(["Unread", "Favourites"]);
  });

  it("does not band the archive, where a star still exists but has no band", async () => {
    // A star survives archiving - the thread is still one somebody cares about
    // - but the band is the active list's. The server stops ordering by it, so
    // the sidebar must stop heading it.
    urlParams = new URLSearchParams("view=archived");
    serve([conversation("c-1", "Rota cover", true)]);
    mount();

    expect(await within(list()).findByText("Rota cover")).toBeVisible();
    expect(within(list()).queryByText("Favourites")).toBeNull();
  });
});

describe("conversations opened over the API (#2122)", () => {
  it("leaves them out by default, and labels them once shown", async () => {
    serve([
      { ...conversation("c-api", "Nightly report"), origin: "api" } as ReturnType<
        typeof conversation
      >,
    ]);
    mount();

    await waitFor(() => expect(listRequests().at(-1)).toContain("hide_api=true"));
    await userEvent.click(await within(list()).findByRole("button", { name: "Filter and sort" }));
    const hide = screen.getByRole("switch", { name: "Hide conversations opened over the API" });
    expect(hide).toBeChecked();
    await userEvent.click(hide);

    await waitFor(() => expect(listRequests().at(-1)).not.toContain("hide_api"));
    expect(window.location.search).toContain("api=show");
    expect(within(list()).getByText("API")).toBeInTheDocument();
  });

  it("goes back to hiding them when the filters are cleared", async () => {
    urlParams = new URLSearchParams("api=show&agent=a-1");
    serve([]);
    mount();

    await waitFor(() => expect(listRequests().at(-1)).not.toContain("hide_api"));
    await userEvent.click(await within(list()).findByRole("button", { name: /clear/i }));

    await waitFor(() => expect(listRequests().at(-1)).toContain("hide_api=true"));
  });
});

describe("who a row is with", () => {
  it("shows the addressed agent on the open thread before any run has named one", async () => {
    // A thread whose first run failed, or has not been listed yet, used to wear
    // a generic chat mark - while the console knew exactly whom it had asked.
    serve([conversation("c-1", "Quarterly numbers"), conversation("c-2", "Older thread")]);
    useConversationStore.getState().setCurrentConversationId("c-1");
    useAgentSelectionStore.setState({ selectedAgentId: "a-1" });
    mount();

    await screen.findAllByText("Quarterly numbers");
    const faces = within(list()).getAllByTestId("row-agents");
    expect(faces.map((face) => face.textContent)).toEqual(["Analyst"]);
  });
});
