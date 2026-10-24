import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WatchDialog } from "./watch-dialog";
import type { Watch, WatchPreset } from "@/lib/watches-api";

/**
 * Setting up a watch (#2301): a preset fills in its words in the person's
 * language and keeps to the organization's floor, the person's own words work
 * too, and a change to an existing one carries what to leave out.
 */

const state = vi.hoisted(() => ({
  floor: 15 as number | null,
  presets: [] as WatchPreset[],
  create: vi.fn(),
  update: vi.fn(),
  path: "/mcp-servers",
  push: vi.fn(),
}));
const toastSuccess = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());
const refusal = vi.hoisted(() => ({
  value: null as null | { fields: Record<string, string>; toast: string | null },
}));

vi.mock("@/hooks", () => ({
  useMcpConnections: () => ({
    connections: [
      { id: "c-gh", name: "github", label: null, catalog_key: "github" },
      { id: "c-mine", name: "intranet", label: "Our wiki", catalog_key: null },
    ],
  }),
  useOrganizations: () => ({
    activeOrg: state.floor === null ? null : { proactive_watch_min_minutes: state.floor },
  }),
  useMcpCatalog: () => ({
    servers: [{ key: "github", name: "GitHub", icon: "github", url: null }],
  }),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => state.path,
  useRouter: () => ({ push: state.push }),
}));
vi.mock("@/hooks/use-watches", () => ({
  useWatchPresets: () => state.presets,
  useWatches: () => ({ create: state.create, update: state.update }),
}));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError } }));
vi.mock("@/lib/api-error", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-error")>();
  return {
    ...actual,
    submitFailure: (...args: Parameters<typeof actual.submitFailure>) =>
      refusal.value ?? actual.submitFailure(...args),
  };
});

const REVIEWS: WatchPreset = {
  key: "github-reviews",
  server: "github",
  instructions: "Pull requests where my review is requested.",
  interval_minutes: 60,
  urgent: false,
};
const FAILING: WatchPreset = {
  key: "github-failing-checks",
  server: "github",
  instructions: "My own open pull requests whose checks are failing.",
  interval_minutes: 60,
  urgent: true,
};

const watch = (overrides: Partial<Watch> = {}): Watch => ({
  id: "w1",
  connection_id: "c-gh",
  connection_name: "github",
  server: "github",
  preset_key: "github-reviews",
  title: "Reviews",
  instructions: "Waiting on me",
  exclusions: ["dependabot"],
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
  state.floor = 15;
  state.presets = [REVIEWS, FAILING, { ...REVIEWS, key: "linear-assigned", server: "linear" }];
  state.create.mockReset().mockResolvedValue(undefined);
  state.update.mockReset().mockResolvedValue(undefined);
  state.path = "/mcp-servers";
  state.push.mockReset();
  refusal.value = null;
  toastSuccess.mockReset();
  toastError.mockReset();
});

describe("WatchDialog", () => {
  it("fills a preset in the person's words, within the organization's floor", async () => {
    state.floor = 180;
    const onOpenChange = vi.fn();
    render(<WatchDialog open onOpenChange={onOpenChange} connectionId="c-gh" />);

    // Only the presets for this connection's server, and one's own words.
    expect(screen.queryByRole("radio", { name: "Issues assigned to me" })).toBeNull();
    await userEvent.click(
      screen.getByRole("radio", { name: "Failing checks on my pull requests" }),
    );
    expect(screen.getByLabelText("Name")).toHaveValue("Failing checks on my pull requests");
    expect(screen.getByRole("switch", { name: "Tell me at once when it is urgent" })).toBeChecked();
    expect(screen.getByRole("combobox", { name: "How often" })).toHaveTextContent("Every 3 hours");
    await userEvent.click(screen.getByRole("button", { name: "Start watching" }));

    expect(state.create).toHaveBeenCalledWith({
      connection_id: "c-gh",
      preset_key: "github-failing-checks",
      title: "Failing checks on my pull requests",
      instructions: "My own open pull requests whose checks are failing.",
      urgent: true,
      interval_minutes: 180,
    });
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    // Started from an account's menu, it says where the watch now lives.
    const [message, options] = toastSuccess.mock.calls[0]!;
    expect(message).toBe("Watching - the first look is within a minute");
    expect(options.description).toBe(
      "It is under Routines, and what it finds lands in your inbox.",
    );
    options.action.onClick();
    expect(state.push).toHaveBeenCalledWith("/routines");
  });

  it("names each account by its server, and offers no way to Routines from Routines", async () => {
    state.path = "/pl/routines";
    render(<WatchDialog open onOpenChange={vi.fn()} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Account" }));
    expect(await screen.findByRole("option", { name: "GitHub" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("option", { name: "Our wiki" }));
    await userEvent.type(screen.getByLabelText("Name"), "Wiki");
    await userEvent.type(screen.getByLabelText("Look for"), "Pricing");
    await userEvent.click(screen.getByRole("button", { name: "Start watching" }));

    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    expect(toastSuccess.mock.calls[0]![1].action).toBeUndefined();
  });

  it("takes the person's own words for a server with no presets", async () => {
    state.floor = null;
    render(<WatchDialog open onOpenChange={vi.fn()} />);
    const start = screen.getByRole("button", { name: "Start watching" });
    expect(start).toBeDisabled();

    await userEvent.click(screen.getByRole("combobox", { name: "Account" }));
    await userEvent.click(await screen.findByRole("option", { name: "Our wiki" }));
    expect(screen.queryByRole("radio", { name: "Something else" })).toBeNull();
    await userEvent.type(screen.getByLabelText("Name"), "  Wiki edits ");
    await userEvent.type(screen.getByLabelText("Look for"), "Pages about pricing");
    await userEvent.click(screen.getByRole("combobox", { name: "How often" }));
    await userEvent.click(await screen.findByRole("option", { name: "Every 15 minutes" }));
    await userEvent.click(start);

    expect(state.create).toHaveBeenCalledWith({
      connection_id: "c-mine",
      preset_key: null,
      title: "Wiki edits",
      instructions: "Pages about pricing",
      urgent: false,
      interval_minutes: 15,
    });
  });

  it("goes back to one's own words from a preset", async () => {
    render(<WatchDialog open onOpenChange={vi.fn()} connectionId="c-gh" />);
    await userEvent.click(
      screen.getByRole("radio", { name: "Pull requests waiting on my review" }),
    );
    await userEvent.click(screen.getByRole("radio", { name: "Something else" }));
    expect(screen.getByRole("radio", { name: "Something else" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    // What the preset wrote stays, to edit from.
    expect(screen.getByLabelText("Name")).toHaveValue("Pull requests waiting on my review");
  });

  it("changes a watch it was opened with, what to leave out included", async () => {
    const onOpenChange = vi.fn();
    render(<WatchDialog open onOpenChange={onOpenChange} watch={watch()} />);
    expect(screen.getByRole("combobox", { name: "Account" })).toBeDisabled();
    expect(screen.queryByRole("radio")).toBeNull();
    await userEvent.type(screen.getByLabelText("Leave out"), "\nrenovate");
    await userEvent.click(
      screen.getByRole("switch", { name: "Tell me at once when it is urgent" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(state.update).toHaveBeenCalledWith({
      id: "w1",
      changes: {
        title: "Reviews",
        instructions: "Waiting on me",
        urgent: true,
        interval_minutes: 60,
        exclusions: ["dependabot", "renovate"],
      },
    });
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Watch saved"));
  });

  it("puts a refusal under the field it names and toasts the rest", async () => {
    refusal.value = { fields: { interval_minutes: "Too often" }, toast: "Also this" };
    state.update.mockRejectedValue(new Error("400"));
    render(<WatchDialog open onOpenChange={vi.fn()} watch={watch()} />);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Too often")).toBeVisible();
    expect(toastError).toHaveBeenCalledWith("Also this");
  });

  it("says nothing more than the field when that is all the refusal named", async () => {
    refusal.value = { fields: { title: "Taken" }, toast: null };
    state.update.mockRejectedValue(new Error("400"));
    render(<WatchDialog open onOpenChange={vi.fn()} watch={watch()} />);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Taken")).toBeVisible();
    expect(toastError).not.toHaveBeenCalled();
  });

  it("closes on Cancel", async () => {
    const onOpenChange = vi.fn();
    render(<WatchDialog open onOpenChange={onOpenChange} watch={watch()} />);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
