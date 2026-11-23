import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
vi.mock("@/hooks/use-report-start-step", () => ({ useReportStartStep: () => undefined }));
import { AccountAppearance } from "@/components/layout/account-appearance";
import { useThemeStore } from "@/stores/theme-store";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { useMotionStore } from "@/stores/motion-store";
import { StartPreferences } from "./start-preferences";

const api = vi.hoisted(() => ({
  read: vi.fn(),
  save: vi.fn(),
  saveLocale: vi.fn(),
  push: vi.fn(),
  error: vi.fn(),
}));
vi.mock("@/lib/account-preferences-api", () => ({
  readAccountPreferences: api.read,
  saveAccountAppearance: api.save,
}));
vi.mock("@/lib/account-locale-api", () => ({ saveAccountLocale: api.saveLocale }));
vi.mock("@/lib/locale-navigation", () => ({
  usePathname: () => "/onboarding",
  useRouter: () => ({ push: api.push }),
}));
vi.mock("sonner", () => ({ toast: { error: api.error } }));

beforeEach(() => {
  vi.clearAllMocks();
  useThemeStore.setState({ theme: "dark", look: "paper", editRevision: 0, editedField: null });
  useAuthStore.setState({
    user: {
      id: "preferences-user",
      email: "one@example.com",
      is_active: true,
      created_at: "2026-11-01",
      locale: "en",
    },
  });
  useOrgStore.setState({ activeOrgId: "existing-workspace" });
  api.read.mockResolvedValue({ theme: null, look: null, locale: null });
  api.save.mockResolvedValue({ theme: null, look: null, locale: null });
  api.saveLocale.mockResolvedValue("pl");
  window.history.replaceState(null, "", "/onboarding?invite=test&variant=studio#intro");
});
function mount(onContinue = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <AccountAppearance />
      <StartPreferences onContinue={onContinue} />
    </QueryClientProvider>,
  );
  return onContinue;
}
it("offers all five native language names without changing stored preferences on mount", async () => {
  mount();
  await waitFor(() => expect(api.read).toHaveBeenCalled());
  expect(screen.getAllByRole("radio")).toHaveLength(5);
  expect(screen.getByRole("radio", { name: "English" })).toBeChecked();
  for (const name of ["Polski", "Deutsch", "Türkçe", "Français"])
    expect(screen.getByRole("radio", { name })).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
  expect(screen.getByRole("link", { name: "Open the app" })).toHaveAttribute("href", "/chat");
  expect(api.save).not.toHaveBeenCalled();
  expect(api.saveLocale).not.toHaveBeenCalled();
  expect(useThemeStore.getState()).toMatchObject({ look: "paper", theme: "dark", editRevision: 0 });
});
it("saves a language through the shared hook and preserves the invitation, variant and fragment", async () => {
  mount();
  await userEvent.click(screen.getByRole("radio", { name: "Polski" }));
  expect(screen.getByRole("radio", { name: "Polski" })).toBeChecked();
  expect(api.saveLocale).toHaveBeenCalledWith("pl");
  expect(api.push).toHaveBeenCalledWith("/onboarding?invite=test&variant=studio#intro", {
    locale: "pl",
  });
  expect(useAuthStore.getState().user?.locale).toBe("pl");
  expect(useOrgStore.getState().activeOrgId).toBe("existing-workspace");
  expect(api.save).not.toHaveBeenCalled();
});
it("reveals five actual looks and three color modes with existing selections preserved", async () => {
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.queryByRole("radio", { name: "English" })).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Make the app feel like yours." })).toHaveFocus();
  const looks = screen.getByRole("radiogroup", { name: "Style" });
  expect(within(looks).getAllByRole("radio")).toHaveLength(5);
  expect(within(looks).getByRole("radio", { name: /Paper/ })).toBeChecked();
  const themes = screen.getByRole("radiogroup", { name: "Theme" });
  expect(within(themes).getAllByRole("radio")).toHaveLength(3);
  expect(within(themes).getByRole("radio", { name: "Dark" })).toBeChecked();
  expect(api.save).not.toHaveBeenCalled();
  expect(useThemeStore.getState().editRevision).toBe(0);
});
it("synchronizes only deliberate appearance edits with the account and keeps them on Back", async () => {
  mount();
  await waitFor(() => expect(api.read).toHaveBeenCalled());
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  await userEvent.click(screen.getByRole("radio", { name: /Graphite/ }));
  await waitFor(() => expect(api.save).toHaveBeenCalledWith({ look: "graphite" }));
  await userEvent.click(screen.getByRole("radio", { name: "Light" }));
  await waitFor(() => expect(api.save).toHaveBeenCalledWith({ theme: "light" }));
  await userEvent.click(screen.getByRole("button", { name: "Back" }));
  expect(screen.getByRole("heading", { name: "Which language feels natural?" })).toHaveFocus();
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByRole("radio", { name: /Graphite/ })).toBeChecked();
  expect(screen.getByRole("radio", { name: "Light" })).toBeChecked();
  expect(api.save).toHaveBeenCalledTimes(2);
});
it("calls the parent only after both questions, without completing onboarding or changing workspace", async () => {
  const onContinue = mount();
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(onContinue).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Continue to setup" }));
  expect(onContinue).toHaveBeenCalledOnce();
  expect(api.save).not.toHaveBeenCalled();
  expect(api.saveLocale).toHaveBeenCalledWith("en");
  expect(useOrgStore.getState().activeOrgId).toBe("existing-workspace");
});

it("confirms the displayed language for an account with no locale without resetting the step", async () => {
  useAuthStore.setState((state) => ({ user: state.user ? { ...state.user, locale: null } : null }));
  mount();
  expect(api.saveLocale).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(api.saveLocale).toHaveBeenCalledWith("en");
  expect(useAuthStore.getState().user?.locale).toBe("en");
  expect(api.push).not.toHaveBeenCalled();
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
    "Make the app feel like yours.",
  );
});

const originalAnimate = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "animate");
afterEach(() => {
  if (originalAnimate) Object.defineProperty(HTMLElement.prototype, "animate", originalAnimate);
  else Reflect.deleteProperty(HTMLElement.prototype, "animate");
  document.documentElement.style.removeProperty("--duration-base");
  document.documentElement.style.removeProperty("--ease-out");
  useMotionStore.setState({ motion: "system" });
});
it.each(["full", "reduce"] as const)(
  "uses the shared %s motion contract only when changing steps",
  async (motion) => {
    const animate = vi.fn(() => ({ cancel: vi.fn() }));
    Object.defineProperty(HTMLElement.prototype, "animate", { configurable: true, value: animate });
    document.documentElement.style.setProperty("--duration-base", "220ms");
    document.documentElement.style.setProperty("--ease-out", "ease-out");
    useMotionStore.setState({ motion });
    mount();
    expect(animate).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(animate).toHaveBeenCalledTimes(motion === "full" ? 1 : 0);
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(animate).toHaveBeenCalledTimes(motion === "full" ? 2 : 0);
  },
);
