import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AddChannelDialog } from "./add-channel-dialog";
import { useOrgStore } from "@/stores";

vi.mock("@/hooks", () => ({ useOrganizationList: () => ({ data: [] }) }));
vi.mock("@/components/channels/transcription-fields", async (original) => ({
  ...(await original<typeof import("@/components/channels/transcription-fields")>()),
  TranscriptionFields: () => null,
}));

afterEach(() => useOrgStore.setState({ activeOrgId: null }));

function mount() {
  const submit = vi.fn().mockResolvedValue(undefined);
  const change = vi.fn();
  const refresh = vi.fn();
  render(
    <AddChannelDialog
      open
      onOpenChange={change}
      onSubmit={submit}
      isPending={false}
      onPluginSetup={refresh}
    />,
  );
  return { submit, change, refresh };
}

describe("Mattermost setup methods", () => {
  it("keeps manual registration as the default and sends the existing payload", async () => {
    const { submit } = mount();
    expect(screen.getByRole("radio", { name: /Manual setup/ })).toBeChecked();
    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: "Support" } });
    fireEvent.change(screen.getByLabelText(/Bot token/), {
      target: { value: "mattermost-bot-token" },
    });
    fireEvent.change(screen.getByLabelText(/Server URL/), {
      target: { value: "https://mattermost.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Register" }));
    await waitFor(() =>
      expect(submit).toHaveBeenCalledWith(
        expect.objectContaining({
          platform: "mattermost",
          name: "Support",
          token: "mattermost-bot-token",
          api_base_url: "https://mattermost.example",
        }),
      ),
    );
  });

  it("shows plugin instructions and the active organization without requesting a bot token", async () => {
    useOrgStore.setState({ activeOrgId: "11111111-1111-4111-8111-111111111111" });
    const { submit, refresh, change } = mount();
    await userEvent.click(screen.getByRole("radio", { name: /Use plugin/ }));
    expect(screen.getByRole("radio", { name: /Use plugin/ })).toBeChecked();
    expect(screen.queryByLabelText(/Bot token/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Register" })).not.toBeInTheDocument();
    expect(screen.getByText("/agenticos connect")).toBeVisible();
    expect(screen.getByText("11111111-1111-4111-8111-111111111111")).toBeVisible();
    expect(
      screen.getByRole("link", { name: "Plugin and installation instructions" }),
    ).toHaveAttribute("href", "https://github.com/vstorm-co/agenticos-mattermost");
    await userEvent.click(screen.getByRole("button", { name: "Refresh channels" }));
    expect(refresh).toHaveBeenCalledOnce();
    expect(change).toHaveBeenCalledWith(false);
    expect(submit).not.toHaveBeenCalled();
  });

  it("clears credentials when switching to the plugin and back", async () => {
    mount();
    fireEvent.change(screen.getByLabelText(/Bot token/), {
      target: { value: "discard-this-secret" },
    });
    await userEvent.click(screen.getByRole("radio", { name: /Use plugin/ }));
    await userEvent.click(screen.getByRole("radio", { name: /Manual setup/ }));
    expect(screen.getByLabelText(/Bot token/)).toHaveValue("");
    expect(screen.getByRole("button", { name: "Register" })).toBeDisabled();
  });

  it("supports keyboard selection with native radio controls", async () => {
    mount();
    const group = screen.getByRole("group", { name: "Connection method" });
    const manual = within(group).getByRole("radio", { name: /Manual setup/ });
    const plugin = within(group).getByRole("radio", { name: /Use plugin/ });
    manual.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(plugin).toHaveFocus();
    expect(plugin).toBeChecked();
    expect(screen.getByText("/agenticos connect")).toBeVisible();
  });

  it("returns to ordinary registration when another platform is selected", async () => {
    mount();
    await userEvent.click(screen.getByRole("radio", { name: /Use plugin/ }));
    await userEvent.click(screen.getByRole("button", { name: "Slack" }));
    expect(screen.queryByText("/agenticos connect")).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Bot token/)).toBeVisible();
    expect(screen.queryByRole("radio", { name: /Use plugin/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Mattermost" }));
    expect(screen.getByRole("radio", { name: /Manual setup/ })).toBeChecked();
  });
});
