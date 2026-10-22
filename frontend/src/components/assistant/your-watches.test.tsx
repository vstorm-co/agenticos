import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { YourWatches } from "./your-watches";
import type { Watch } from "@/lib/watches-api";

/**
 * The person's watches (#2301): what each looks for and how often, why one that
 * is on is not being read, and pausing, changing and removing them.
 */

const state = vi.hoisted(() => ({
  orgOn: true as boolean | undefined,
  connections: [{ id: "c-gh" }] as { id: string }[],
  watches: [] as Watch[],
  update: vi.fn(),
  remove: vi.fn(),
  dialog: vi.fn(),
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
  useWatches: () => ({ watches: state.watches, update: state.update, remove: state.remove }),
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
  created_at: "2026-10-22T09:00:00Z",
  ...overrides,
});

beforeEach(() => {
  state.orgOn = true;
  state.connections = [{ id: "c-gh" }];
  state.watches = [];
  state.update.mockReset().mockResolvedValue(undefined);
  state.remove.mockReset().mockResolvedValue(undefined);
  state.dialog.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
});

describe("YourWatches", () => {
  it("says the organization has watches off and offers nothing to add", () => {
    state.orgOn = undefined;
    state.watches = [watch({ stopped: "watches_off" })];
    render(<YourWatches />);

    expect(screen.getByText(/has not turned watches on/)).toBeInTheDocument();
    expect(screen.getByText("Off for the organization")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Watch something" })).toBeNull();
  });

  it("asks for a connection first when the person has none", () => {
    state.connections = [];
    render(<YourWatches />);
    expect(screen.getByText(/Connect one of your own accounts/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Watch something" })).toBeNull();
  });

  it("lists each watch with how often it looks, and opens a new one", async () => {
    state.watches = [
      watch({ urgent: true }),
      watch({
        id: "w2",
        title: "Custom",
        server: null,
        interval_minutes: 1440,
        is_active: false,
        stopped: "server_not_allowed",
      }),
    ];
    render(<YourWatches />);

    expect(screen.getByText("github · Every hour")).toBeInTheDocument();
    expect(screen.getByText("Urgent at once")).toBeInTheDocument();
    // A paused watch is not "stopped by the organization": it is paused.
    expect(screen.queryByText("Server not allowed")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Watch something" }));
    expect(screen.getByRole("dialog", { name: "New watch" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("pauses, resumes, edits and removes one", async () => {
    state.watches = [watch(), watch({ id: "w2", title: "Paused one", is_active: false })];
    render(<YourWatches />);

    await userEvent.click(screen.getByRole("switch", { name: "Watch Reviews" }));
    expect(state.update).toHaveBeenLastCalledWith({ id: "w1", changes: { is_active: false } });
    await waitFor(() => expect(toastSuccess).toHaveBeenLastCalledWith("Paused"));
    await userEvent.click(screen.getByRole("switch", { name: "Watch Paused one" }));
    await waitFor(() => expect(toastSuccess).toHaveBeenLastCalledWith("Watching again"));

    await userEvent.click(screen.getByRole("button", { name: "Edit Reviews" }));
    expect(screen.getByRole("dialog", { name: "Editing Reviews" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Stop watching Reviews" }));
    expect(state.remove).toHaveBeenCalledWith("w1");
    await waitFor(() => expect(toastSuccess).toHaveBeenLastCalledWith("Stopped watching"));
  });

  it("toasts a change the server refused", async () => {
    state.watches = [watch()];
    state.remove.mockRejectedValue(new Error("Server down"));
    render(<YourWatches />);
    const row = screen.getByText("Reviews").closest("li")!;
    await userEvent.click(within(row).getByRole("button", { name: "Stop watching Reviews" }));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
  });
});
