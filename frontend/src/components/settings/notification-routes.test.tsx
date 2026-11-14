import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { NotificationRoutes } from "./notification-routes";
import type { NotificationRoutes as Routes } from "@/lib/notification-preferences-api";

const replace = vi.fn();
const refetch = vi.fn();
let data: Routes | undefined;
let error: Error | null;
let isLoading: boolean;
let isSaving: boolean;
vi.mock("@/hooks/use-notification-routes", () => ({
  useNotificationRoutes: () => ({ data, error, isLoading, isSaving, replace, refetch }),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

beforeEach(() => {
  vi.clearAllMocks();
  replace.mockResolvedValue(undefined);
  error = null;
  isLoading = false;
  isSaving = false;
  data = {
    items: [],
    destinations: [
      { session_id: "session-one", channel: "slack", bot_name: "Assistant", account_name: "Ada" },
    ],
  };
});

describe("private chat notification destinations", () => {
  it("does not enable notifications merely because an account was linked", async () => {
    render(<NotificationRoutes />);
    expect(screen.getByRole("combobox", { name: "Slack" })).toHaveTextContent("Off");
    await userEvent.click(screen.getByRole("combobox", { name: "Slack" }));
    await userEvent.click(await screen.findByRole("option", { name: /Assistant · Ada/ }));
    expect(replace).toHaveBeenCalledWith({ channel: "slack", session_id: "session-one" });
  });

  it("can revoke a destination whose link is no longer usable", async () => {
    data = {
      destinations: [
        { session_id: "session-one", channel: "slack", bot_name: "Assistant", account_name: "Ada" },
      ],
      items: [{ id: "route", channel: "slack", session_id: "session-one", available: false }],
    };
    render(<NotificationRoutes />);
    await userEvent.click(screen.getByRole("combobox", { name: "Slack" }));
    await userEvent.click(await screen.findByRole("option", { name: "Off" }));
    expect(replace).toHaveBeenCalledWith({ channel: "slack", session_id: null });
  });

  it("shows a refusal instead of pretending an unavailable destination was saved", async () => {
    replace.mockRejectedValue(new Error("Destination changed"));
    render(<NotificationRoutes />);
    await userEvent.click(screen.getByRole("combobox", { name: "Slack" }));
    await userEvent.click(await screen.findByRole("option", { name: /Assistant · Ada/ }));
    expect(toast.error).toHaveBeenCalledWith("Destination changed");
    expect(screen.getByRole("combobox", { name: "Slack" })).toHaveTextContent("Off");
  });

  it("distinguishes loading, pending writes and a failed read from an empty list", () => {
    isLoading = true;
    data = undefined;
    const view = render(<NotificationRoutes />);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    isLoading = false;
    data = {
      items: [],
      destinations: [
        { session_id: "session-one", channel: "slack", bot_name: "Assistant", account_name: "Ada" },
      ],
    };
    isSaving = true;
    view.rerender(<NotificationRoutes />);
    expect(screen.getAllByRole("combobox").every((item) => item.hasAttribute("disabled"))).toBe(
      true,
    );
    error = new Error("Read failed");
    view.rerender(<NotificationRoutes />);
    expect(screen.getByText("Read failed")).toBeVisible();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });
});

it("shows the selected destination from the server", () => {
  data = {
    items: [{ id: "route", channel: "slack", session_id: "session-one", available: true }],
    destinations: [
      { session_id: "session-one", channel: "slack", bot_name: "Assistant", account_name: "Ada" },
    ],
  };
  render(<NotificationRoutes />);
  expect(screen.getByRole("combobox", { name: "Slack" })).toHaveTextContent("Assistant · Ada");
});

it("keeps unconnected platforms folded and offers recovery from a failed read", async () => {
  data = { items: [], destinations: [] };
  const view = render(<NotificationRoutes />);
  expect(screen.queryByRole("combobox", { name: "Mattermost" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Chat platforms" }));
  expect(screen.getByRole("combobox", { name: "Mattermost" })).toBeDisabled();
  error = new Error("Read refused");
  view.rerender(<NotificationRoutes />);
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(refetch).toHaveBeenCalledOnce();
});
