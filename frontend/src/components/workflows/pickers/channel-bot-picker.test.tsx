import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChannelBotPicker } from "./channel-bot-picker";

const bots = vi.fn();
const mayManage = vi.fn(() => true);

vi.mock("@/hooks", () => ({
  useChannelBots: (enabled: boolean) => bots(enabled),
  usePermissions: () => ({ can: () => mayManage() }),
}));

const BOTS = [
  { id: "b1", name: "Ops bot", platform: "slack", is_active: true },
  { id: "b2", name: "Old bot", platform: "mattermost", is_active: false },
];

beforeEach(() => {
  vi.clearAllMocks();
  mayManage.mockReturnValue(true);
  bots.mockReturnValue({ bots: BOTS, isLoading: false });
});

describe("ChannelBotPicker", () => {
  it("writes the chosen bot's id, and marks one that is switched off", async () => {
    const onChange = vi.fn();
    render(<ChannelBotPicker value={null} onChange={onChange} />);

    await userEvent.click(screen.getByRole("combobox", { name: "Bot" }));
    expect(screen.getByRole("option", { name: /Old bot.*Off/ })).toBeTruthy();
    await userEvent.click(screen.getByRole("option", { name: /Ops bot/ }));

    expect(onChange).toHaveBeenCalledWith("b1");
    expect(bots).toHaveBeenCalledWith(true);
  });

  it("says where to add a bot when there is none, and names a bot that is gone", () => {
    bots.mockReturnValue({ bots: [], isLoading: false });
    const { rerender } = render(<ChannelBotPicker value={null} onChange={vi.fn()} />);
    expect(screen.getByRole("link", { name: "Add one under Channels" }).getAttribute("href")).toBe(
      "/channels",
    );

    rerender(<ChannelBotPicker value="gone" onChange={vi.fn()} error="Pick a bot" />);
    expect(screen.getByText(/The bot this step names is gone/)).toBeTruthy();
    expect(screen.getByText("Pick a bot")).toBeTruthy();
  });

  it("tells a member without channels:manage why, and lists nothing for them", () => {
    mayManage.mockReturnValue(false);
    bots.mockReturnValue({ bots: [], isLoading: false });
    render(<ChannelBotPicker value={null} onChange={vi.fn()} />);

    expect(screen.getByText(/needs channels:manage/)).toBeTruthy();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(bots).toHaveBeenCalledWith(false);
  });
});
