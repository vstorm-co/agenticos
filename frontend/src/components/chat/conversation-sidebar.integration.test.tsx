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
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConversationSidebar } from "./conversation-sidebar";
import { apiClient } from "@/lib/api-client";
import { useConversationStore } from "@/stores";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({ agents: [{ id: "a-1", name: "Analyst", status: "published" }] }),
}));
// A manager, so the trigger split button and section render; a viewer variant is
// covered in the section's own suite.
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => true, isLoading: false }),
}));
vi.mock("@/components/agents/agent-avatar", () => ({
  AgentAvatar: ({ name }: { name: string }) => <span>{name}</span>,
}));
vi.mock("@/components/agents/conversation-agents", () => ({
  ConversationAgents: () => null,
}));

let urlParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useSearchParams: () => urlParams,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/chat",
}));

function conversation(id: string, title: string) {
  return {
    id,
    title,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    is_archived: false,
    agents: [],
  };
}

/** Whatever the list route should answer with next. */
function serve(items: ReturnType<typeof conversation>[], total = items.length) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path.includes("/messages")) return { items: [], total: 0 };
    return { items, total };
  });
}

/** Every list request made so far, newest last. */
function listRequests(): string[] {
  return vi
    .mocked(apiClient.get)
    .mock.calls.map(([path]) => path as string)
    .filter((path) => !path.includes("/messages"));
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
  serve([conversation("c-1", "Quarterly numbers")]);
});

describe("searching the conversation list", () => {
  it("asks the server, rather than filtering the page it holds", async () => {
    mount();
    await screen.findAllByText("Quarterly numbers");

    await userEvent.type(
      within(list()).getByRole("textbox", { name: "Search conversations" }),
      "refund",
    );

    await waitFor(() => expect(listRequests().at(-1)).toContain("search=refund"));
  });

  it("waits for the typing to stop rather than asking per keystroke", async () => {
    mount();
    await screen.findAllByText("Quarterly numbers");
    const before = listRequests().length;

    await userEvent.type(
      within(list()).getByRole("textbox", { name: "Search conversations" }),
      "refunds",
    );

    // Seven characters, and not seven requests: the settled value is what the
    // key is built from, so nothing is fetched until the box stops moving.
    expect(listRequests().length).toBeLessThan(before + 7);
    await waitFor(() => expect(listRequests().at(-1)).toContain("search=refunds"));
  });

  it("writes the search to the URL, so a reload lands on the same list", async () => {
    mount();
    await screen.findAllByText("Quarterly numbers");

    await userEvent.type(
      within(list()).getByRole("textbox", { name: "Search conversations" }),
      "refund",
    );

    await waitFor(() => expect(window.location.search).toContain("q=refund"));
  });

  it("starts from the URL it was given", async () => {
    urlParams = new URLSearchParams("q=refund&agent=a-1&sort=title:asc&view=archived");
    mount();

    await waitFor(() => {
      const request = listRequests().at(-1) ?? "";
      expect(request).toContain("search=refund");
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

describe("what the sidebar says about the list", () => {
  it("counts what matches, not what it fetched", async () => {
    serve([conversation("c-1", "Quarterly numbers")], 214);
    mount();

    expect(await screen.findAllByText("214 conversations")).not.toHaveLength(0);
  });

  it("puts no count on the tabs, because it never knew one", async () => {
    serve([conversation("c-1", "Quarterly numbers")], 214);
    mount();
    await screen.findAllByText("Quarterly numbers");

    expect(within(list()).getByRole("button", { name: "Active" })).toHaveTextContent(/^Active$/);
    expect(within(list()).getByRole("button", { name: "Archived" })).toHaveTextContent(
      /^Archived$/,
    );
  });

  it("distinguishes an empty deployment from an empty search", async () => {
    serve([]);
    mount();

    expect(await screen.findAllByText("No conversations yet")).not.toHaveLength(0);
    expect(screen.queryByText("Nothing matches")).not.toBeInTheDocument();

    await userEvent.type(
      within(list()).getByRole("textbox", { name: "Search conversations" }),
      "refund",
    );

    expect((await screen.findAllByText("Nothing matches"))[0]).toBeVisible();
  });

  it("offers a way out of a filter that matches nothing", async () => {
    serve([]);
    mount();
    await userEvent.type(
      within(list()).getByRole("textbox", { name: "Search conversations" }),
      "refund",
    );
    await screen.findAllByText("Nothing matches");

    serve([conversation("c-1", "Quarterly numbers")]);
    await userEvent.click(within(list()).getAllByRole("button", { name: "Clear filters" })[0]!);

    expect((await screen.findAllByText("Quarterly numbers"))[0]).toBeVisible();
    await waitFor(() => expect(window.location.search).not.toContain("q="));
  });

  it("says the archive is empty rather than that nothing matched", async () => {
    serve([]);
    mount();

    await userEvent.click(within(list()).getByRole("button", { name: "Archived" }));

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
    return screen.getByRole("button", { name: "Expand conversations sidebar" })
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

  it("expands with the cursor already in the search box", async () => {
    // Otherwise the button is a second Expand, and costs a click to reach the
    // thing it is named after.
    const rail = await collapse();

    await userEvent.click(within(rail).getByRole("button", { name: "Search conversations" }));

    const box = within(list()).getByRole("textbox", { name: "Search conversations" });
    await waitFor(() => expect(box).toHaveFocus());
  });

  it("expands onto the archived tab", async () => {
    const rail = await collapse();

    await userEvent.click(within(rail).getByRole("button", { name: "Archived" }));

    await waitFor(() => expect(listRequests().at(-1)).toContain("archived_only=true"));
  });

  it("does not steal the cursor when it is expanded with the chevron", async () => {
    // The search button's focus is a one-shot. Left set, every later expand would
    // take the cursor out of whatever somebody was typing in the composer.
    const rail = await collapse();
    await userEvent.click(within(rail).getByRole("button", { name: "Search conversations" }));
    await userEvent.click(
      within(list()).getByRole("button", { name: "Collapse conversations sidebar" }),
    );

    await userEvent.click(screen.getByRole("button", { name: "Expand conversations sidebar" }));

    expect(within(list()).getByRole("textbox", { name: "Search conversations" })).not.toHaveFocus();
  });
});

describe("the New Chat split button", () => {
  it("keeps New Chat itself starting a chat, not opening a menu", async () => {
    mount();
    await screen.findAllByText("Quarterly numbers");

    await userEvent.click(within(list()).getByRole("button", { name: "New Chat" }));

    // No dialog and no menu: the wide half of the split button is exactly the
    // button it always was.
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("opens the schedule dialog from the chevron menu", async () => {
    mount();
    await screen.findAllByText("Quarterly numbers");

    await userEvent.click(within(list()).getByRole("button", { name: "New schedule or trigger" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "New schedule" }));

    const dialog = await screen.findByRole("dialog");
    // No agent is in context here, so the form asks whom to schedule.
    expect(within(dialog).getByRole("combobox", { name: "Agent" })).toBeVisible();
  });

  it("opens the event-trigger dialog from the chevron menu", async () => {
    mount();
    await screen.findAllByText("Quarterly numbers");

    await userEvent.click(within(list()).getByRole("button", { name: "New schedule or trigger" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "New trigger" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Signing secret")).toBeVisible();
  });
});
