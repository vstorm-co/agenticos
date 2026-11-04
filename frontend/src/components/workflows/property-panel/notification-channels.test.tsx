import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { NotificationChannels } from "./notification-channels";
it("keeps the last channel selected and lets an invalid empty draft be repaired", async () => {
  const onChange = vi.fn();
  const { rerender } = render(<NotificationChannels value={undefined} onChange={onChange} />);
  expect(screen.getByRole("checkbox", { name: "In-app notification" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "In-app notification" })).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox", { name: "In-app notification" }));
  expect(onChange).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("checkbox", { name: "Email" }));
  expect(onChange).toHaveBeenCalledWith(["in_app", "email"]);
  rerender(<NotificationChannels value={["email", "in_app"]} onChange={onChange} />);
  await userEvent.click(screen.getByRole("checkbox", { name: "In-app notification" }));
  expect(onChange).toHaveBeenLastCalledWith(["email"]);
  rerender(<NotificationChannels value={[]} onChange={onChange} />);
  expect(screen.getByRole("checkbox", { name: "In-app notification" })).not.toBeChecked();
});
