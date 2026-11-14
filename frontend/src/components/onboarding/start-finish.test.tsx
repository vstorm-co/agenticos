import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { StartFinish } from "./start-finish";
const env = vi.hoisted(() => ({
  save: vi.fn(),
  push: vi.fn(),
  error: null as unknown,
  pending: false,
}));
vi.mock("@/hooks/use-start", () => ({
  useStart: () => ({ save: { mutate: env.save, error: env.error, isPending: env.pending } }),
}));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ push: env.push }) }));
beforeEach(() => {
  vi.clearAllMocks();
  env.error = null;
  env.pending = false;
});
it("finishes setup without an agent, result or optional configuration", async () => {
  render(<StartFinish />);
  await userEvent.click(screen.getByRole("button", { name: "Finish setup and open the app" }));
  expect(env.save).toHaveBeenCalledWith({ completed: true }, expect.any(Object));
  expect(env.push).not.toHaveBeenCalled();
  act(() => env.save.mock.calls[0]?.[1].onSuccess());
  expect(env.push).toHaveBeenCalledWith("/chat");
});
it("keeps a failed completion retryable", () => {
  env.error = new Error("offline");
  render(<StartFinish />);
  expect(screen.getByRole("alert")).toBeVisible();
  expect(screen.getByRole("button")).toBeEnabled();
  expect(env.push).not.toHaveBeenCalled();
});
it("ignores completion after the person leaves the final question", async () => {
  const view = render(<StartFinish />);
  await userEvent.click(screen.getByRole("button"));
  const finish = env.save.mock.calls[0]?.[1].onSuccess;
  expect(finish).toBeTypeOf("function");
  view.unmount();
  act(() => finish?.());
  expect(env.push).not.toHaveBeenCalled();
});
it("prevents repeated saves while completion is pending", () => {
  env.pending = true;
  render(<StartFinish />);
  expect(screen.getByRole("button")).toBeDisabled();
});
