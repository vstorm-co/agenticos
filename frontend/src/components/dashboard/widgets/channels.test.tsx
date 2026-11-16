import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChannelsWidget } from "./channels";
import type { ChannelBot } from "@/types/channels";

const useChannelBotsMock = vi.fn();
const useBindingRequestsMock = vi.fn();
vi.mock("@/hooks", () => ({
  useChannelBots: (...args: unknown[]) => useChannelBotsMock(...args),
  useChannelBindingRequests: (...args: unknown[]) => useBindingRequestsMock(...args),
}));

function bot(overrides: Partial<ChannelBot> = {}): ChannelBot {
  return {
    id: "b1",
    platform: "whatsapp",
    name: "Support line",
    is_active: true,
    webhook_mode: true,
    access_policy: { mode: "open", rate_limit_rpm: 10 },
    ...overrides,
  } as ChannelBot;
}

function show(bots: ChannelBot[], waiting = 0) {
  useBindingRequestsMock.mockReturnValue({
    requests: Array.from({ length: waiting }, (_, index) => ({ id: `r${index}` })),
  });
  useChannelBotsMock.mockReturnValue({ bots, isLoading: false, error: null, refetch: vi.fn() });
  render(
    <ChannelsWidget
      title="Channels"
      hint=""
      period={{ preset: "30d", from: "2026-10-05", to: "2026-11-04" }}
    />,
  );
}

beforeEach(() => {
  useChannelBotsMock.mockReset();
  useBindingRequestsMock.mockReset();
});

describe("the channels card", () => {
  it("marks a line that answers people with no account", () => {
    show([
      bot({
        access_policy: {
          mode: "open",
          rate_limit_rpm: 10,
          answer_unlinked_direct: true,
        } as ChannelBot["access_policy"],
      }),
    ]);

    expect(screen.getByText("listening · public line")).toBeInTheDocument();
  });

  it("shows the plain mode of a line that does not", () => {
    show([bot()]);

    expect(screen.getByText("listening")).toBeInTheDocument();
  });

  it("does not mark a switched-off bot's line, which answers nobody", () => {
    show([
      bot({
        is_active: false,
        access_policy: {
          mode: "open",
          rate_limit_rpm: 10,
          answer_unlinked_direct: true,
        } as ChannelBot["access_policy"],
      }),
    ]);

    expect(screen.getByText("switched off")).toBeInTheDocument();
  });

  it("says when nothing is registered", () => {
    show([]);

    expect(screen.getByText("No channels yet")).toBeInTheDocument();
  });

  it("says how many binding requests wait, and links to them", () => {
    show([bot()], 2);

    const row = screen.getByRole("link", { name: "2 binding requests" });
    expect(row).toHaveAttribute("href", "/channels?requests=open");
  });

  it("uses the singular for one", () => {
    show([bot()], 1);

    expect(screen.getByRole("link", { name: "1 binding request" })).toBeInTheDocument();
  });

  it("says nothing when none wait", () => {
    show([bot()], 0);

    expect(screen.queryByText(/binding request/)).not.toBeInTheDocument();
  });

  it("shows the requests even with no bot listed yet", () => {
    show([], 1);

    expect(screen.getByRole("link", { name: "1 binding request" })).toBeInTheDocument();
  });
});
