import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { apiClient } from "@/lib/api-client";
import { MfaSettingsSection } from "./mfa-settings";

vi.mock("@/lib/api-client", async () => ({
  ...(await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client")),
  apiClient: { get: vi.fn(), post: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const mocked = apiClient as unknown as {
  get: ReturnType<typeof vi.fn>;
  post: ReturnType<typeof vi.fn>;
};

function renderSection() {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <MfaSettingsSection />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("MfaSettingsSection", () => {
  it("offers setup when the second factor is off", async () => {
    mocked.get.mockResolvedValue({ enabled: false });
    renderSection();

    expect(
      await screen.findByRole("button", { name: "Set up two-factor authentication" }),
    ).toBeVisible();
  });

  it("starts setup, shows the secret once, and enables on a good code", async () => {
    mocked.get.mockResolvedValue({ enabled: false });
    mocked.post
      .mockResolvedValueOnce({ provisioning_uri: "otpauth://totp/x", secret: "JBSWY3DPEHPK3PXP" })
      .mockResolvedValueOnce({ recovery_codes: ["ABCD-EFGH", "IJKL-MNOP"] });
    renderSection();

    fireEvent.click(
      await screen.findByRole("button", { name: "Set up two-factor authentication" }),
    );
    expect(await screen.findByDisplayValue("JBSWY3DPEHPK3PXP")).toBeVisible();

    fireEvent.change(screen.getByLabelText("Authenticator code"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Enable two-factor authentication" }));

    expect(await screen.findByText("Recovery codes - save these now")).toBeVisible();
    expect(screen.getByText("ABCD-EFGH")).toBeVisible();
    expect(mocked.post).toHaveBeenCalledWith("/auth/mfa/enable", { code: "123456" });
  });

  it("offers disablement when the second factor is on", async () => {
    mocked.get.mockResolvedValue({ enabled: true });
    mocked.post.mockResolvedValue(undefined);
    renderSection();

    expect(
      await screen.findByRole("button", { name: "Turn off two-factor authentication" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Replace recovery codes" })).toBeVisible();

    fireEvent.change(screen.getByLabelText("Authenticator code"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Turn off two-factor authentication" }));

    await waitFor(() =>
      expect(mocked.post).toHaveBeenCalledWith("/auth/mfa/disable", { code: "123456" }),
    );
  });

  it("offers a retry when the status cannot be read", async () => {
    mocked.get.mockRejectedValue(new Error("unreachable"));
    renderSection();

    expect(
      await screen.findByText("Could not load two-factor authentication status."),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  });
});
