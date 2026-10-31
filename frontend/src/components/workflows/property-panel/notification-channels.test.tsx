import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { NotificationChannels } from "./notification-channels";
it("shows readable channel names and preserves an explicit empty selection", async () => {
  const onChange = vi.fn();
  const { rerender } = render(<NotificationChannels value={undefined} onChange={onChange} />);
  expect(screen.getByRole("checkbox", { name: "In-app notification" })).toBeChecked();
  await userEvent.click(screen.getByRole("checkbox", { name: "Email" }));
  expect(onChange).toHaveBeenCalledWith(["in_app", "email"]);
  rerender(<NotificationChannels value={[]} onChange={onChange} />);
  expect(screen.getByRole("checkbox", { name: "In-app notification" })).not.toBeChecked();
});
