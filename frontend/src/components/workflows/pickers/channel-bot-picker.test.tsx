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

vi.mock("@/components/channels/add-channel-dialog", () => ({
  AddChannelDialog: ({
    initialPlatform,
    onSubmit,
  }: {
    initialPlatform?: string;
    onSubmit: (data: { platform: string; name: string; token: string }) => Promise<unknown>;
  }) => (
    <button
      onClick={() =>
        void onSubmit({
          platform: initialPlatform ?? "mattermost",
          name: "New bot",
          token: "write-only",
        })
      }
    >
      Create connected bot
    </button>
  ),
}));

const BOTS = [
  { id: "b1", name: "Ops bot", platform: "slack", is_active: true },
  { id: "b2", name: "Old bot", platform: "mattermost", is_active: false },
  { id: "b3", name: "Teams bot", platform: "teams", is_active: true },
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

  it("is called what its field is called, when the field names itself", () => {
    render(<ChannelBotPicker value={null} onChange={vi.fn()} label="Alert bot" />);
    expect(screen.getByRole("combobox", { name: "Alert bot" })).toBeTruthy();
  });

  it("offers only its platform's bots when the step names one, without the platform badge", async () => {
    render(<ChannelBotPicker value={null} onChange={vi.fn()} platform="slack" />);
    await userEvent.click(screen.getByRole("combobox", { name: "Bot" }));
    expect(screen.getByRole("option", { name: "Ops bot" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: /Old bot/ })).toBeNull();
  });

  it("offers the bots of every platform it names, each with its platform", async () => {
    render(
      <ChannelBotPicker
        value={null}
        onChange={vi.fn()}
        platform={["slack", "mattermost", "telegram"]}
      />,
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Bot" }));
    expect(screen.getByRole("option", { name: /Ops bot.*slack/ })).toBeTruthy();
    expect(screen.queryByRole("option", { name: /Teams bot/ })).toBeNull();
  });

  it("says a stored bot of a platform it cannot use is the wrong kind, not gone", () => {
    render(
      <ChannelBotPicker
        value="b3"
        onChange={vi.fn()}
        platform={["slack", "mattermost", "telegram"]}
      />,
    );
    expect(screen.getByText(/Workflows answer on Slack, Mattermost and Telegram/)).toBeTruthy();
    expect(screen.queryByText(/is gone/)).toBeNull();
  });

  it("names the one platform a single-platform step takes when its stored bot is another's", () => {
    render(<ChannelBotPicker value="b2" onChange={vi.fn()} platform="slack" />);
    expect(screen.getByText("This step takes Slack bots - choose another.")).toBeTruthy();
    expect(screen.queryByText(/Workflows answer on/)).toBeNull();
  });

  it("says where to add a bot when there is none, and names a bot that is gone", () => {
    bots.mockReturnValue({ bots: [], isLoading: false });
    const { rerender } = render(<ChannelBotPicker value={null} onChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Connect channel" })).toBeInTheDocument();

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

it("creates a channel inline and selects its returned identity", async () => {
  const onChange = vi.fn();
  const create = vi.fn().mockResolvedValue({ id: "fresh" });
  bots.mockReturnValue({
    bots: [],
    isLoading: false,
    create: { isPending: false, mutateAsync: create },
  });
  render(<ChannelBotPicker value={null} onChange={onChange} platform="slack" />);
  await userEvent.click(screen.getByRole("button", { name: "Connect channel" }));
  await userEvent.click(await screen.findByRole("button", { name: "Create connected bot" }));
  expect(create).toHaveBeenCalledWith({ platform: "slack", name: "New bot", token: "write-only" });
  expect(onChange).toHaveBeenCalledWith("fresh");
});
