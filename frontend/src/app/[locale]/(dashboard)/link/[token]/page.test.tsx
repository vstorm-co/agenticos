import { Suspense } from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ChannelLinkPage from "./page";
import type { ChannelLinkRequest } from "@/lib/channel-link-api";

const api = vi.hoisted(() => ({
  readChannelLink: vi.fn(),
  confirmChannelLink: vi.fn(),
}));

vi.mock("@/lib/channel-link-api", () => api);

const whatsapp: ChannelLinkRequest = {
  platform: "whatsapp",
  platform_username: "•••• 1234",
  platform_display_name: "Kacper",
  expires_at: "2026-11-02T12:00:00Z",
  awaiting_code: false,
  confirm_code: null,
  display_name_verified: false,
};

async function renderPage() {
  // `params` is a promise the page reads with `use`, so it suspends once.
  const params = Promise.resolve({ token: "tok" });
  await act(async () => {
    render(
      <Suspense fallback={null}>
        <ChannelLinkPage params={params} />
      </Suspense>,
    );
  });
}

beforeEach(() => {
  api.readChannelLink.mockReset();
  api.confirmChannelLink.mockReset();
});

describe("the chat account link page", () => {
  it("renders_the_code_after_confirming_a_whatsapp_link", async () => {
    api.readChannelLink.mockResolvedValue(whatsapp);
    api.confirmChannelLink.mockResolvedValue({
      ...whatsapp,
      awaiting_code: true,
      confirm_code: "042917",
    });
    await renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Connect this account" }));

    expect(await screen.findByText("042917")).toBeVisible();
    expect(
      screen.getByText(
        "Send this code from your WhatsApp chat to finish. Never give it to anyone.",
      ),
    ).toBeVisible();
    // Not connected yet: it stays here, and does not say it is.
    expect(screen.queryByText("This chat account is now yours.")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect this account" })).not.toBeInTheDocument();
  });

  it("shows_the_code_again_when_the_page_is_reopened", async () => {
    api.readChannelLink.mockResolvedValue({
      ...whatsapp,
      awaiting_code: true,
      confirm_code: "042917",
    });
    await renderPage();

    expect(await screen.findByText("042917")).toBeVisible();
  });

  it("labels_an_unverified_name", async () => {
    api.readChannelLink.mockResolvedValue(whatsapp);
    await renderPage();

    expect(await screen.findByText("•••• 1234")).toBeVisible();
    expect(screen.getByText("Kacper (name not verified)")).toBeVisible();
    expect(screen.getByText("WhatsApp")).toBeVisible();
  });

  it("never_shows_an_unverified_name_as_the_account", async () => {
    api.readChannelLink.mockResolvedValue({ ...whatsapp, platform_username: null });
    await renderPage();

    expect(await screen.findByText("That chat account")).toBeVisible();
    expect(screen.getByText("Kacper (name not verified)")).toBeVisible();
    expect(screen.queryByText("Kacper")).not.toBeInTheDocument();
  });

  it("names_a_verified_account_as_before", async () => {
    api.readChannelLink.mockResolvedValue({
      platform: "teams",
      platform_username: "kacper@example.com",
      platform_display_name: "Kacper",
      expires_at: "2026-11-02T12:00:00Z",
      awaiting_code: false,
      confirm_code: null,
      display_name_verified: true,
    });
    await renderPage();

    expect(await screen.findByText("Kacper")).toBeVisible();
    expect(screen.getByText("Microsoft Teams")).toBeVisible();
    expect(screen.queryByText(/name not verified/)).not.toBeInTheDocument();
  });

  it("finishes_a_one_way_link_in_the_browser", async () => {
    api.readChannelLink.mockResolvedValue({
      ...whatsapp,
      platform: "telegram",
      display_name_verified: true,
    });
    api.confirmChannelLink.mockResolvedValue({
      ...whatsapp,
      platform: "telegram",
      display_name_verified: true,
    });
    await renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Connect this account" }));

    expect(await screen.findByText("This chat account is now yours.")).toBeVisible();
  });
});
