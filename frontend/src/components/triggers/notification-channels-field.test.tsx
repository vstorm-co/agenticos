import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { NotificationChannelsField } from "./notification-channels-field";

describe("routine notification channels", () => {
  it("inherits preferences or explicitly keeps only frontend results", async () => {
    const change = vi.fn();
    const { rerender } = render(<NotificationChannelsField value={null} onChange={change} />);
    expect(screen.getByRole("combobox")).toHaveTextContent("Use my preferences");
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(await screen.findByRole("option", { name: "In the app only" }));
    expect(change).toHaveBeenLastCalledWith([]);
    rerender(<NotificationChannelsField value={[]} onChange={change} />);
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(await screen.findByRole("option", { name: "Use my preferences" }));
    expect(change).toHaveBeenLastCalledWith(null);
  });
  it("can select multiple external channels without claiming they override preferences", async () => {
    const change = vi.fn();
    render(<NotificationChannelsField value={["push"]} onChange={change} />);
    expect(screen.getByRole("combobox")).toHaveTextContent("Device notifications only");
    expect(screen.getByText(/preferences still apply/)).toBeVisible();
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(
      await screen.findByRole("option", { name: "E-mail and device notifications" }),
    );
    expect(change).toHaveBeenLastCalledWith(["email", "push"]);
  });
});

it("can combine supported chat channels without expanding personal preferences", async () => {
  const change = vi.fn();
  const { rerender } = render(
    <NotificationChannelsField value={["sms", "teams"]} onChange={change} />,
  );
  expect(screen.getByRole("combobox")).toHaveTextContent("Choose channels");
  expect(screen.getByRole("checkbox", { name: "SMS" })).toBeChecked();
  await userEvent.click(screen.getByRole("checkbox", { name: "Telegram" }));
  expect(change).toHaveBeenLastCalledWith(["telegram", "teams", "sms"]);
  rerender(<NotificationChannelsField value={["telegram", "teams", "sms"]} onChange={change} />);
  await userEvent.click(screen.getByRole("checkbox", { name: "SMS" }));
  expect(change).toHaveBeenLastCalledWith(["telegram", "teams"]);
});

it("opens a custom selection from inherited preferences", async () => {
  const change = vi.fn();
  render(<NotificationChannelsField value={null} onChange={change} />);
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(await screen.findByRole("option", { name: "Choose channels" }));
  expect(change).toHaveBeenLastCalledWith([]);
  expect(screen.getByRole("checkbox", { name: "Slack" })).not.toBeChecked();
});
