import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DeploymentSettings } from "@/hooks/use-deployment-settings";
import DeploymentSettingsPage from "./page";

const save = vi.fn();
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
  settings = null;
  error = null;
  loading = true;
  save.mockReset();
});

describe("deployment settings loading", () => {
  it("keeps the actual form cards and controls mounted until the saved values arrive", () => {
    const { container, rerender } = render(<DeploymentSettingsPage />);
    const cards = Array.from(container.querySelectorAll(".shadow-card"));
    const inputs = Array.from(container.querySelectorAll("input,textarea,button[role=combobox]"));
    expect(cards).toHaveLength(9);
    expect(inputs.length).toBeGreaterThan(10);
    expect(screen.getByRole("status", { name: /loading/i })).toBeInTheDocument();
    expect(container.querySelector("[inert]")).toHaveAttribute("aria-hidden", "true");
    settings = SAVED;
    loading = false;
    rerender(<DeploymentSettingsPage />);
    expect(Array.from(container.querySelectorAll(".shadow-card"))).toEqual(cards);
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

  it("reports a failed read instead of offering a default-valued form", () => {
    loading = false;
    error = new Error("down");
    const { container } = render(<DeploymentSettingsPage />);
    expect(container.querySelector("#app-name")).toBeNull();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
