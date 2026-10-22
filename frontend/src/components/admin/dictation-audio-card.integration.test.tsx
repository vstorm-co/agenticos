import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DeploymentSettingsPage from "@/app/[locale]/(dashboard)/admin/settings/page";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), patch: vi.fn(), delete: vi.fn(), upload: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
// The page refreshes the server-rendered branding after a save.
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

/** `GET /admin/settings` for a deployment that has never accepted compressed audio. */
const SETTINGS = {
  app_name: null,
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
  dictation_compressed_audio: false,
  updated_at: null,
};

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

async function page(overrides: Partial<typeof SETTINGS> = {}) {
  vi.mocked(apiClient.get).mockResolvedValue({ ...SETTINGS, ...overrides });
  render(<DeploymentSettingsPage />, { wrapper });
  return screen.findByRole("switch", { name: "Accept compressed recordings (WebM, Ogg, MP4)" });
}

const save = () => userEvent.click(screen.getByRole("button", { name: "Save" }));

describe("accepting compressed dictation audio", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.patch).mockImplementation(async (_url, body) => ({
      ...SETTINGS,
      ...(body as object),
    }));
  });

  it("is off until an administrator accepts the risks the dialog names", async () => {
    const toggle = await page();
    expect(toggle).toHaveAttribute("aria-checked", "false");

    await userEvent.click(toggle);

    const dialog = await screen.findByRole("dialog", { name: "Accept compressed recordings?" });
    expect(within(dialog).getByText(/A crafted file can understate it/)).toBeInTheDocument();
    expect(within(dialog).getByText(/up to about 40 times as much/)).toBeInTheDocument();
    expect(
      within(dialog).getByText(/anyone holding the link can send such files/),
    ).toBeInTheDocument();
    expect(within(dialog).getByText(/outside agent budgets/)).toBeInTheDocument();
    expect(
      within(dialog).getByText("It applies to every organization on this deployment."),
    ).toBeInTheDocument();
    expect(within(dialog).getByText(/about an eighth of the size/)).toBeInTheDocument();
    // Nothing changes while the dialog is only open.
    expect(toggle).toHaveAttribute("aria-checked", "false");

    const confirm = within(dialog).getByRole("button", { name: "Accept compressed recordings" });
    expect(confirm).toBeDisabled();
    await userEvent.click(within(dialog).getByRole("checkbox"));
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(apiClient.patch).not.toHaveBeenCalled();

    await save();

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/admin/settings", {
        dictation_compressed_audio: true,
      }),
    );
  });

  it("stays off when the dialog is cancelled, acknowledged or not", async () => {
    const toggle = await page();

    await userEvent.click(toggle);
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("checkbox"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Keep PCM only" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

    // Opened again, the acknowledgement is not remembered from last time.
    await userEvent.click(toggle);
    const again = await screen.findByRole("dialog");
    expect(within(again).getByRole("checkbox")).toHaveAttribute("aria-checked", "false");
    expect(
      within(again).getByRole("button", { name: "Accept compressed recordings" }),
    ).toBeDisabled();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(toggle).toHaveAttribute("aria-checked", "false");
  });

  it("turns off without asking, because off is the safe direction", async () => {
    const toggle = await page({ dictation_compressed_audio: true });
    expect(toggle).toHaveAttribute("aria-checked", "true");

    await userEvent.click(toggle);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-checked", "false");
    await save();
    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/admin/settings", {
        dictation_compressed_audio: false,
      }),
    );
  });
});
