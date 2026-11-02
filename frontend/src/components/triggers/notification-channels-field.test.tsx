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
