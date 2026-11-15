import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { RegisterForm } from "./register-form";
const env = vi.hoisted(() => ({
  register: vi.fn(),
  login: vi.fn(),
  push: vi.fn(),
  search: new URLSearchParams(),
}));
vi.mock("@/hooks", () => ({ useAuth: () => ({ register: env.register, login: env.login }) }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: env.push }),
  useSearchParams: () => env.search,
}));
vi.mock("@/components/auth/oauth-buttons", () => ({ OAuthBlock: () => null }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
beforeEach(() => {
  vi.clearAllMocks();
  env.register.mockResolvedValue({});
  env.login.mockResolvedValue({});
  env.search = new URLSearchParams();
});
async function submit() {
  await userEvent.type(screen.getByLabelText(/^email$/i), "person@example.com");
  await userEvent.type(screen.getByLabelText(/^password$/i), "ValidPassword123!");
  await userEvent.type(screen.getByLabelText(/confirm password/i), "ValidPassword123!");
  await userEvent.click(screen.getByRole("button", { name: /^register$/i }));
}
it("signs in a new account and opens the shared start", async () => {
  render(<RegisterForm />);
  await submit();
  await waitFor(() =>
    expect(env.login).toHaveBeenCalledWith(
      { email: "person@example.com", password: "ValidPassword123!" },
      "/onboarding?welcome=1&entry=account",
    ),
  );
  expect(env.push).not.toHaveBeenCalled();
});
it("preserves an invitation destination if the new account still needs to sign in", async () => {
  const returnTo = "/invitations/pending?flow=0123456789abcdef0123456789abcdef";
  env.search = new URLSearchParams({ returnTo });
  env.login.mockRejectedValue(new Error("session unavailable"));
  render(<RegisterForm />);
  await submit();
  await waitFor(() =>
    expect(env.push).toHaveBeenCalledWith(
      `/login?registered=true&returnTo=${encodeURIComponent(returnTo)}`,
    ),
  );
  expect(env.register).toHaveBeenCalledTimes(1);
});
