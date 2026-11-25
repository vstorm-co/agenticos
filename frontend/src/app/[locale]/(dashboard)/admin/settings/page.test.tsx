import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BrandingProvider } from "@/components/branding/branding-provider";
import { BUILT_IN_BRANDING } from "@/lib/branding";
import { DeploymentSettingsForm } from "@/components/admin/deployment-settings-form";
import type { DeploymentSettings, DeploymentSettingsPatch } from "@/hooks/use-deployment-settings";
import DeploymentSettingsPage from "./page";

// APNs has its own query-backed form and tests; this suite covers deployment settings.
vi.mock("@/components/admin/apns-key-card", () => ({ ApnsKeyCard: () => null }));

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn(async (path: string) => {
      if (path === "/admin/diagnostics")
        return {
          enabled: true,
          collector: "https://analytics.example.com",
          instance_id: null,
          last_attempt: null,
          last_success: null,
          last_error: null,
        };
      if (path === "/admin/updates")
        return {
          configured: false,
          reachable: false,
          pipeline_url: null,
          operation: null,
        };
      if (path === "/releases/latest") return { latest: null };
      throw new Error(`Unexpected request: ${path}`);
    }),
  },
}));

function queryWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <BrandingProvider
          branding={{ ...BUILT_IN_BRANDING, signInProviders: settings?.sign_in_providers ?? [] }}
        >
          {children}
        </BrandingProvider>
      </QueryClientProvider>
    );
  };
}

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
const save =
  vi.fn<(changes: DeploymentSettingsPatch, callbacks: { onSuccess: () => void }) => void>();
let settings: DeploymentSettings | null = null;
let error: Error | null = null;
let loading = true;
vi.mock("@/hooks/use-deployment-settings", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/use-deployment-settings")>(
    "@/hooks/use-deployment-settings",
  );
  return {
    ...actual,
    useDeploymentSettings: () => ({
      settings,
      isLoading: loading,
      error,
      refetch: vi.fn(),
      save: { mutate: save, isPending: false },
      uploadImage: { mutate: vi.fn(), isPending: false },
      clearImage: { mutate: vi.fn(), isPending: false },
    }),
  };
});
vi.mock("@/hooks/use-admin-organizations", () => ({
  useAdminOrganizations: () => ({ organizations: [] }),
}));

const SAVED: DeploymentSettings = {
  app_name: "Acme",
  tagline: null,
  description: null,
  logo_version: null,
  favicon_version: null,
  footer_text: null,
  terms_url: null,
  privacy_url: null,
  signup_mode: "open",
  allowed_email_domains: [],
  maintenance_mode: false,
  maintenance_message: null,
  announcement: null,
  announcement_level: "info",
  max_organizations_per_user: null,
  max_agents_per_organization: null,
  notify_impersonated_users: false,
  personal_organizations: true,
  default_organization_id: null,
  default_organization_role: "member",
  dictation_compressed_audio: false,
  updated_at: null,
};

beforeEach(() => {
  window.history.replaceState(null, "", "/admin/settings");
  settings = null;
  error = null;
  loading = true;
  save.mockReset();
});

describe("deployment settings loading", () => {
  it("keeps the actual form cards and controls mounted until the saved values arrive", () => {
    const { container, rerender } = render(<DeploymentSettingsPage />, { wrapper: queryWrapper() });
    // Only form surfaces matter here; a decorative header may change freely.
    const formCards = () =>
      Array.from(container.querySelectorAll(".shadow-card")).filter(
        (card) => card.querySelector("input,textarea,button[role=combobox]") !== null,
      );
    const cards = formCards();
    const inputs = Array.from(container.querySelectorAll("input,textarea,button[role=combobox]"));
    expect(cards.length).toBeGreaterThan(0);
    expect(inputs.length).toBeGreaterThan(10);
    expect(screen.getByRole("status", { name: /loading/i })).toBeInTheDocument();
    expect(container.querySelector("[inert]")).toHaveAttribute("aria-hidden", "true");
    settings = SAVED;
    loading = false;
    rerender(<DeploymentSettingsPage />);
    expect(formCards()).toEqual(cards);
    expect(Array.from(container.querySelectorAll("input,textarea,button[role=combobox]"))).toEqual(
      inputs,
    );
    expect(container.querySelector("[inert]")).toBeNull();
    expect(screen.queryByRole("status", { name: /loading/i })).not.toBeInTheDocument();
    const name = container.querySelector<HTMLInputElement>("#app-name");
    if (name === null) throw new Error("missing name input");
    expect(name).toHaveValue("Acme");
    fireEvent.change(name, { target: { value: "Updated" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    expect(save).toHaveBeenCalledWith({ app_name: "Updated" }, expect.any(Object));
  });

  it("keeps drafts across sections and discards them without saving", async () => {
    settings = SAVED;
    loading = false;
    render(<DeploymentSettingsPage />, { wrapper: queryWrapper() });
    expect(screen.getByRole("tab", { name: /^Identity$/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "New name" } });
    await userEvent.click(screen.getByRole("tab", { name: "Access & accounts" }));
    expect(screen.queryByLabelText("Name")).not.toBeVisible();
    expect(screen.getByRole("tab", { name: "Access & accounts" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await userEvent.click(screen.getByRole("tab", { name: /^Identity$/ }));
    expect(screen.getByLabelText("Name")).toHaveValue("New name");
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(screen.getByLabelText("Name")).toHaveValue("Acme");
    expect(screen.getByRole("button", { name: /^Save$/ })).toBeDisabled();
    expect(save).not.toHaveBeenCalled();
  });

  it("saves edited fields from different sections in a single patch", async () => {
    settings = SAVED;
    loading = false;
    render(<DeploymentSettingsPage />, { wrapper: queryWrapper() });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Across sections" } });
    await userEvent.click(screen.getByRole("tab", { name: "Access & accounts" }));
    fireEvent.click(screen.getByRole("switch", { name: "Personal organizations" }));
    fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    expect(save).toHaveBeenCalledWith(
      { app_name: "Across sections", personal_organizations: false },
      expect.any(Object),
    );
    await userEvent.click(screen.getByRole("tab", { name: /^Updates & diagnostics$/ }));
    expect(screen.getByText(/^Installed:/)).toBeVisible();
  });

  it("reports a failed read instead of offering a default-valued form", () => {
    loading = false;
    error = new Error("down");
    const { container } = render(<DeploymentSettingsPage />, { wrapper: queryWrapper() });
    expect(container.querySelector("#app-name")).toBeNull();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});

it("guides setup from access settings and advances only when edited settings have saved", async () => {
  settings = SAVED;
  loading = false;
  const next = vi.fn();
  render(<DeploymentSettingsForm onContinue={next} />, { wrapper: queryWrapper() });
  expect(screen.getByRole("tab", { name: "Access & accounts" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  fireEvent.click(screen.getByRole("switch", { name: "Personal organizations" }));
  fireEvent.click(screen.getByRole("button", { name: "Save and continue" }));
  expect(next).not.toHaveBeenCalled();
  expect(save).toHaveBeenCalledWith({ personal_organizations: false }, expect.any(Object));
  const firstSave = save.mock.calls[0];
  if (!firstSave) throw new Error("Expected deployment settings to be saved");
  act(() => firstSave[1].onSuccess());
  expect(next).toHaveBeenCalledOnce();
});

describe("local sign-in policy", () => {
  it("saves the policy without resending other deployment settings", async () => {
    loading = false;
    settings = { ...SAVED, password_sign_in_enabled: true, sign_in_providers: ["oidc"] };
    window.history.replaceState(null, "", "/admin/settings?section=access");
    render(<DeploymentSettingsPage />, { wrapper: queryWrapper() });
    await userEvent.click(screen.getByRole("switch", { name: "Allow local sign-in" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(save).toHaveBeenCalledWith({ password_sign_in_enabled: false }, expect.any(Object));
  });

  it("keeps the last visible sign-in method enabled", () => {
    loading = false;
    settings = { ...SAVED, password_sign_in_enabled: true, sign_in_providers: [] };
    window.history.replaceState(null, "", "/admin/settings?section=access");
    render(<DeploymentSettingsPage />, { wrapper: queryWrapper() });
    expect(screen.getByRole("switch", { name: "Allow local sign-in" })).toBeDisabled();
  });

  it("shows the operator override without changing the saved switch", () => {
    loading = false;
    settings = { ...SAVED, password_sign_in_enabled: false, password_sign_in_forced: true };
    window.history.replaceState(null, "", "/admin/settings?section=access");
    render(<DeploymentSettingsPage />, { wrapper: queryWrapper() });
    expect(screen.getByText(/operator recovery override currently enables/)).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Allow local sign-in" })).not.toBeChecked();
    expect(screen.getByRole("switch", { name: "Allow local sign-in" })).toBeEnabled();
  });
});
