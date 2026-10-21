import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BlobbySettingsPanel } from "./blobby-settings";
import { DESKTOP_STATE, MAC_MAIN } from "./fixtures";

const env = vi.hoisted(() => ({
  state: null as unknown,
  mutate: vi.fn(),
  may: true,
  agents: [] as unknown[],
  loading: false,
}));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => MAC_MAIN }));
vi.mock("@/hooks/use-desktop", () => ({
  useDesktopState: () => ({ data: env.state, error: null }),
  useSetBlobby: () => ({ mutate: env.mutate }),
}));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => env.may }) }));
vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({ agents: env.agents, isLoading: env.loading }),
}));

const SUPPORT = { id: "a1", slug: "support", name: "Support", avatar_color: 4 };
const blobby = DESKTOP_STATE.blobby;

beforeEach(() => {
  env.state = DESKTOP_STATE;
  env.mutate = vi.fn();
  env.may = true;
  env.agents = [SUPPORT, { id: "a2", slug: "ops", name: "Ops", avatar_color: null }];
  env.loading = false;
});

describe("BlobbySettingsPanel", () => {
  it("shows blobby, who it is and how it behaves, and switches it off", async () => {
    render(<BlobbySettingsPanel />);
    expect(screen.getByRole("radio", { name: "Pebble" })).toBeChecked();
    expect(screen.getByRole("switch", { name: "Strolls" })).toBeChecked();

    await userEvent.click(screen.getByRole("switch", { name: "Show blobby" }));

    expect(env.mutate).toHaveBeenCalledWith({ ...blobby, enabled: false });
  });

  it("picks one of the cast, which also puts it back on the desktop", async () => {
    env.state = { ...DESKTOP_STATE, blobby: { ...blobby, enabled: false } };
    render(<BlobbySettingsPanel />);
    await userEvent.click(screen.getByRole("radio", { name: "Nimbus" }));
    expect(env.mutate).toHaveBeenCalledWith({
      ...blobby,
      enabled: true,
      character: { kind: "cast", id: "nimbus" },
    });
  });

  it("wears one of the person's agents' faces", async () => {
    render(<BlobbySettingsPanel />);
    await userEvent.click(screen.getByRole("radio", { name: "One of my agents" }));
    await userEvent.click(screen.getByRole("radio", { name: "Support" }));
    expect(env.mutate).toHaveBeenLastCalledWith(
      expect.objectContaining({
        character: {
          kind: "agent",
          agent_id: "a1",
          slug: "support",
          name: "Support",
          color_slot: 4,
        },
      }),
    );
  });

  it("marks the agent it already wears, and says so when there are none to wear", () => {
    env.state = {
      ...DESKTOP_STATE,
      blobby: {
        ...blobby,
        character: { kind: "agent", agent_id: "a2", slug: "ops", name: "Ops", color_slot: null },
      },
    };
    const { unmount } = render(<BlobbySettingsPanel />);
    expect(
      within(screen.getByRole("radiogroup", { name: "One of my agents" })).getByRole("radio", {
        name: "Ops",
      }),
    ).toBeChecked();
    unmount();

    env.agents = [];
    const second = render(<BlobbySettingsPanel />);
    expect(screen.getByText("No agents you can see yet.")).toBeInTheDocument();
    second.unmount();

    env.may = false;
    env.agents = [SUPPORT];
    render(<BlobbySettingsPanel />);
    expect(screen.getByText("No agents you can see yet.")).toBeInTheDocument();
  });

  it("draws a face of the person's own from a name and a colour", async () => {
    render(<BlobbySettingsPanel />);
    await userEvent.click(screen.getByRole("radio", { name: "My own" }));
    const name = screen.getByRole("textbox", { name: "Name" });
    fireEvent.blur(name);
    expect(env.mutate).not.toHaveBeenCalled();

    await userEvent.type(name, "kacper");
    fireEvent.blur(name);
    expect(env.mutate).toHaveBeenLastCalledWith(
      expect.objectContaining({ character: { kind: "custom", seed: "kacper", color_slot: null } }),
    );

    const colours = screen
      .getAllByRole("radio")
      .filter((radio) => radio.getAttribute("aria-label") !== null);
    await userEvent.click(colours.at(-1)!);
    expect(env.mutate).toHaveBeenLastCalledWith(
      expect.objectContaining({
        character: expect.objectContaining({ kind: "custom", seed: "kacper" }),
      }),
    );
  });

  it("starts from the face it already wears when it is one of the person's own", () => {
    env.state = {
      ...DESKTOP_STATE,
      blobby: { ...blobby, character: { kind: "custom", seed: "zed", color_slot: 2 } },
    };
    render(<BlobbySettingsPanel />);
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("zed");
  });

  it("changes how often it talks and whether it says what the agents are doing", async () => {
    render(<BlobbySettingsPanel />);
    await userEvent.click(screen.getByRole("radio", { name: "Often" }));
    expect(env.mutate).toHaveBeenLastCalledWith({ ...blobby, chatter: "chatty" });
    await userEvent.click(
      screen.getByRole("switch", { name: "Tells you what your agents are doing" }),
    );
    expect(env.mutate).toHaveBeenLastCalledWith({ ...blobby, activity: false });
    await userEvent.click(screen.getByRole("switch", { name: "Strolls" }));
    expect(env.mutate).toHaveBeenLastCalledWith({ ...blobby, roams: false });
  });

  it("sets its size when the slider is let go", () => {
    render(<BlobbySettingsPanel />);
    const slider = screen.getByRole("slider", { name: "Size" });
    fireEvent.change(slider, { target: { value: "1.3" } });
    fireEvent.pointerUp(slider);
    expect(env.mutate).toHaveBeenLastCalledWith({ ...blobby, size: 1.3 });
    fireEvent.change(slider, { target: { value: "0.8" } });
    fireEvent.keyUp(slider, { key: "ArrowLeft" });
    expect(env.mutate).toHaveBeenLastCalledWith({ ...blobby, size: 0.8 });
  });
});
