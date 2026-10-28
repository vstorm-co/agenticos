import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WatchesCard, useCanWatch } from "./watches-card";
import type { Watch } from "@/lib/watches-api";

/**
 * The person's watches under Routines (#2301): what each looks for, in which
 * account and how often, when it last looked and what of its findings waits,
 * why one that is on is not being read, and pausing, changing and removing them.
 */

const state = vi.hoisted(() => ({
  orgOn: true as boolean | undefined,
  connections: [{ id: "c-gh", authorized: true }] as { id: string; authorized: boolean }[],
  watches: [] as Watch[],
  update: vi.fn(),
  remove: vi.fn(),
  dialog: vi.fn(),
  loading: false,
  error: null as Error | null,
  refetch: vi.fn(),
  push: vi.fn(),
}));
const toastSuccess = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());

vi.mock("@/hooks", () => ({
  useOrganizations: () => ({
    activeOrg: state.orgOn === undefined ? null : { proactive_watches_enabled: state.orgOn },
  }),
  useMcpConnections: () => ({ connections: state.connections }),
  useMcpCatalog: () => ({
    servers: [{ key: "github", name: "GitHub", icon: "github", url: null }],
  }),
}));
vi.mock("@/hooks/use-watches", () => ({
  useWatches: () => ({
    watches: state.watches,
    isLoading: state.loading,
    error: state.error,
    refetch: state.refetch,
    update: state.update,
    remove: state.remove,
  }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: state.push }),
  usePathname: () => "/routines",
}));
vi.mock("./watch-dialog", () => ({
  WatchDialog: (props: { watch?: Watch; onOpenChange: (open: boolean) => void }) => {
    state.dialog(props);
    return (
      <div role="dialog" aria-label={props.watch ? `Editing ${props.watch.title}` : "New watch"}>
        <button type="button" onClick={() => props.onOpenChange(false)}>
          Close
        </button>
      </div>
    );
  },
}));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError } }));

const watch = (overrides: Partial<Watch> = {}): Watch => ({
  id: "w1",
  connection_id: "c-gh",
  connection_name: "github",
  server: "github",
  preset_key: null,
  title: "Reviews",
  instructions: "Waiting on me",
  exclusions: [],
  urgent: false,
  interval_minutes: 60,
  is_active: true,
  stopped: null,
  next_run_at: "2026-10-22T10:00:00Z",
  last_run_at: null,
  waiting: 0,
  created_at: "2026-10-22T09:00:00Z",
  ...overrides,
});

beforeEach(() => {
  state.orgOn = true;
  state.connections = [{ id: "c-gh", authorized: true }];
  state.watches = [];
  state.update.mockReset().mockResolvedValue(undefined);
  state.remove.mockReset().mockResolvedValue(undefined);
  state.dialog.mockReset();
  state.loading = false;
  state.error = null;
  state.refetch.mockReset();
  state.push.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
});

const onNew = vi.fn();

describe("WatchesCard", () => {
  it("says the organization has watches off, and still lists what is stopped by it", () => {
    state.orgOn = undefined;
    render(<WatchesCard onNew={onNew} />);
    expect(screen.getByText("Watches are off")).toBeInTheDocument();

    state.watches = [watch({ stopped: "watches_off" })];
    render(<WatchesCard onNew={onNew} />);
    expect(screen.getByText("Off for the organization")).toBeInTheDocument();
  });

  it("sends a person with no account to connect one, and one with an account to start", async () => {
    state.connections = [];
    const { unmount } = render(<WatchesCard onNew={onNew} />);
    await userEvent.click(screen.getByRole("button", { name: "Open MCP servers" }));
    expect(state.push).toHaveBeenCalledWith("/mcp-servers");
    unmount();

    state.connections = [{ id: "c-gh", authorized: true }];
    render(<WatchesCard onNew={onNew} />);
    expect(screen.getByText("No watches yet", { selector: "p" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "New watch" }));
    expect(onNew).toHaveBeenCalled();
  });

  it("counts nothing while the list loads", () => {
    state.loading = true;
    render(<WatchesCard onNew={onNew} />);
    expect(screen.queryByText(/watches?$/)).toBeNull();
  });

  it("lists each with its account, how often and when it looked, and what of it waits", () => {
    state.watches = [
      watch({ urgent: true, waiting: 2, last_run_at: new Date().toISOString() }),
      watch({
        id: "w2",
        title: "Custom",
        server: null,
        connection_name: "Our wiki",
        interval_minutes: 1440,
        is_active: false,
        stopped: "connection_disabled",
      }),
      watch({ id: "w3", title: "Work reviews", connection_name: "Work" }),
    ];
    render(<WatchesCard onNew={onNew} />);

    expect(screen.getByText("3 watches")).toBeInTheDocument();
    expect(screen.getAllByText("GitHub")).toHaveLength(1);
    expect(screen.getByText("Every hour · looked just now")).toBeInTheDocument();
    expect(screen.getByText("Our wiki")).toBeInTheDocument();
    expect(screen.getByText("Daily · first look within a minute")).toBeInTheDocument();
    expect(screen.getByText("GitHub (Work)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "2 in your inbox" })).toHaveAttribute(
      "href",
      "/inbox?filter=watches",
    );
    expect(screen.getByRole("link", { name: "What they found" })).toHaveAttribute(
      "href",
      "/inbox?filter=watches",
    );
    expect(screen.getByText("Urgent at once")).toBeInTheDocument();
    // A paused watch is not "stopped by the organization": it is paused.
    expect(screen.queryByText("Connection off")).toBeNull();
  });

  it("pauses, resumes, edits and removes one", async () => {
    state.watches = [watch(), watch({ id: "w2", title: "Paused one", is_active: false })];
    render(<WatchesCard onNew={onNew} />);

    await userEvent.click(screen.getByRole("switch", { name: "Watch Reviews" }));
    expect(state.update).toHaveBeenLastCalledWith({ id: "w1", changes: { is_active: false } });
    await waitFor(() => expect(toastSuccess).toHaveBeenLastCalledWith("Paused"));
    await userEvent.click(screen.getByRole("switch", { name: "Watch Paused one" }));
    await waitFor(() => expect(toastSuccess).toHaveBeenLastCalledWith("Watching again"));

    await userEvent.click(screen.getByRole("button", { name: "Edit Reviews" }));
    expect(screen.getByRole("dialog", { name: "Editing Reviews" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Stop watching Reviews" }));
    expect(state.remove).toHaveBeenCalledWith("w1");
    await waitFor(() => expect(toastSuccess).toHaveBeenLastCalledWith("Stopped watching"));
  });

  it("says when the account's sign-in lapsed, which a look cannot read through", () => {
    state.connections = [{ id: "c-gh", authorized: false }];
    state.watches = [watch(), watch({ id: "w2", title: "Paused", is_active: false })];
    render(<WatchesCard onNew={onNew} />);
    expect(screen.getAllByText("Sign in to it again")).toHaveLength(1);
  });

  it("toasts a change the server refused", async () => {
    state.watches = [watch()];
    state.remove.mockRejectedValue(new Error("Server down"));
    render(<WatchesCard onNew={onNew} />);
    const row = screen.getByText("Reviews").closest("li")!;
    await userEvent.click(within(row).getByRole("button", { name: "Stop watching Reviews" }));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
  });
});

describe("useCanWatch", () => {
  function Probe() {
    return <p>{String(useCanWatch())}</p>;
  }

  it("needs the organization's switch and an account of the person's own", () => {
    const { rerender } = render(<Probe />);
    expect(screen.getByText("true")).toBeInTheDocument();
    state.connections = [];
    rerender(<Probe />);
    expect(screen.getByText("false")).toBeInTheDocument();
  });
});

it("does not present a failed watch read as a prompt to create a new watch", async () => {
  state.error = new Error("unavailable");
  render(<WatchesCard onNew={vi.fn()} />);
  expect(screen.queryByText("No watches yet")).toBeNull();
  expect(screen.getByText("Something went wrong")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(state.refetch).toHaveBeenCalledOnce();
});
