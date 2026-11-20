import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense } from "react";
import { expect, it, vi } from "vitest";

import ChannelLinkPage from "./page";
import { confirmChannelLink, readChannelLink } from "@/lib/channel-link-api";

vi.mock("@/lib/channel-link-api", () => ({
  readChannelLink: vi.fn(),
  confirmChannelLink: vi.fn(),
}));

it("shows the asserting Matrix homeserver before account consent", async () => {
  vi.mocked(readChannelLink).mockResolvedValue({
    platform: "matrix",
    server_url: "https://homeserver.example.org/tenant",
    platform_username: "@ada:example.org",
    platform_display_name: "Ada",
    expires_at: "2026-11-20T20:00:00Z",
  });
  vi.mocked(confirmChannelLink).mockResolvedValue({
    platform: "matrix",
    server_url: "https://homeserver.example.org/tenant",
    platform_username: "@ada:example.org",
    platform_display_name: "Ada",
    expires_at: "2026-11-20T20:00:00Z",
  });
  const params = Promise.resolve({ token: "matrix-link" });
  await act(async () => {
    render(
      <Suspense>
        <ChannelLinkPage params={params} />
      </Suspense>,
    );
  });
  expect(await screen.findByText("https://homeserver.example.org/tenant")).toBeVisible();
  expect(screen.getByText("Matrix")).toBeVisible();
  expect(confirmChannelLink).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Connect this account" }));
  expect(confirmChannelLink).toHaveBeenCalledWith("matrix-link");
});
