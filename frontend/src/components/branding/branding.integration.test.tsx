import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AnnouncementBanner } from "./announcement-banner";
import { BrandMark } from "./brand-mark";
import { BrandingProvider } from "./branding-provider";
import { DeploymentGate } from "./deployment-gate";
import { MaintenanceScreen } from "./maintenance-screen";
import { apiClient } from "@/lib/api-client";
import { BUILT_IN_BRANDING, type Branding } from "@/lib/branding";

/**
 * What the deployment's own state does to the product.
 *
 * The three assertions worth having through a render rather than against a
 * function: that an operator's mark actually replaces the built-in glyph, that a
 * maintenance window hides the product from everybody **except** the administrator
 * who has to end it, and that dismissing an announcement is keyed on the sentence
 * rather than on a flag - a flag makes the *next* announcement invisible to
 * everybody who dismissed the last one.
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn() } };
});

const authState = { user: null as { is_app_admin?: boolean } | null };
vi.mock("@/hooks", () => ({ useAuth: () => authState }));

function branded(overrides: Partial<Branding> = {}) {
  return function Wrapper({ children }: { children: ReactNode }) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return (
      <QueryClientProvider client={client}>
        <BrandingProvider branding={{ ...BUILT_IN_BRANDING, ...overrides }}>
          {children}
        </BrandingProvider>
      </QueryClientProvider>
    );
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  authState.user = { is_app_admin: false };
  vi.mocked(apiClient.get).mockResolvedValue({ message: null, level: "info" });
});

describe("the deployment's mark", () => {
  it("draws the built-in glyph when nothing was uploaded", () => {
    render(<BrandMark />, { wrapper: branded() });

    expect(screen.getByTestId("brand-glyph")).toBeInTheDocument();
    expect(screen.queryByTestId("brand-logo")).not.toBeInTheDocument();
  });

  it("draws the operator's image once there is one", () => {
    render(<BrandMark />, { wrapper: branded({ logoUrl: "/api/branding/mark/logo?v=3" }) });

    expect(screen.getByTestId("brand-logo")).toHaveAttribute("src", "/api/branding/mark/logo?v=3");
    expect(screen.queryByTestId("brand-glyph")).not.toBeInTheDocument();
  });

  it("leaves the image undescribed, because the name is beside it in text", () => {
    render(<BrandMark />, { wrapper: branded({ logoUrl: "/api/branding/mark/logo?v=3" }) });

    expect(screen.getByTestId("brand-logo")).toHaveAttribute("alt", "");
  });
});

describe("a maintenance window", () => {
  it("hides the product from an ordinary user", () => {
    render(
      <DeploymentGate>
        <p>the dashboard</p>
      </DeploymentGate>,
      { wrapper: branded({ maintenanceMode: true }) },
    );

    expect(screen.queryByText("the dashboard")).not.toBeInTheDocument();
  });

  it("leaves it open for the administrator who has to end it", () => {
    // A maintenance mode that also hides the switch is an outage.
    authState.user = { is_app_admin: true };

    render(
      <DeploymentGate>
        <p>the dashboard</p>
      </DeploymentGate>,
      { wrapper: branded({ maintenanceMode: true }) },
    );

    expect(screen.getByText("the dashboard")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/maintenance mode is on/i);
  });

  it("changes nothing while no window is open", () => {
    render(
      <DeploymentGate>
        <p>the dashboard</p>
      </DeploymentGate>,
      { wrapper: branded() },
    );

    expect(screen.getByText("the dashboard")).toBeInTheDocument();
  });

  it("says what the operator wrote, when they wrote something", () => {
    render(<MaintenanceScreen />, {
      wrapper: branded({ maintenanceMode: true, maintenanceMessage: "Back at 22:00, ping ops." }),
    });

    expect(screen.getByText("Back at 22:00, ping ops.")).toBeInTheDocument();
  });

  it("falls back to wording of its own when they did not", () => {
    render(<MaintenanceScreen />, { wrapper: branded({ maintenanceMode: true }) });

    expect(screen.getByRole("heading")).toHaveTextContent(/under maintenance/i);
  });
});

describe("the announcement banner", () => {
  it("stays away when there is no announcement", async () => {
    render(<AnnouncementBanner enabled />, { wrapper: branded() });

    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("shows what the administrator wrote", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ message: "Upgrade at 22:00", level: "warning" });

    render(<AnnouncementBanner enabled />, { wrapper: branded() });

    expect(await screen.findByText("Upgrade at 22:00")).toBeInTheDocument();
  });

  it("stays dismissed once dismissed", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ message: "Upgrade at 22:00", level: "info" });
    render(<AnnouncementBanner enabled />, { wrapper: branded() });
    await screen.findByText("Upgrade at 22:00");

    await userEvent.click(screen.getByRole("button", { name: /dismiss/i }));

    expect(screen.queryByText("Upgrade at 22:00")).not.toBeInTheDocument();
  });

  it("keys the dismissal on the sentence, so the next announcement is seen", async () => {
    // A flag would make every later announcement invisible to anybody who
    // dismissed one; the settings row's timestamp would un-dismiss a notice
    // whenever the deployment was renamed. The text is what changed.
    window.localStorage.setItem("agenticos:notice-dismissed", "The previous one");
    vi.mocked(apiClient.get).mockResolvedValue({ message: "A new one", level: "info" });

    render(<AnnouncementBanner enabled />, { wrapper: branded() });

    expect(await screen.findByText("A new one")).toBeInTheDocument();
  });

  it("does not ask at all when nobody is signed in", async () => {
    render(<AnnouncementBanner enabled={false} />, { wrapper: branded() });

    await waitFor(() => expect(apiClient.get).not.toHaveBeenCalled());
  });
});
