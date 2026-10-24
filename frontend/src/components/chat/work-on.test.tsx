import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { useConversationStore } from "@/stores";
import { useWorkOnStore } from "@/stores/work-on-store";
import { WorkOn } from "./work-on";

vi.mock("@/hooks/use-shell", () => ({
  useShell: () => ({ platform: "macos", window: "main", version: "0.2.0", vibrancy: false }),
}));
vi.mock("@/hooks/use-desktop", () => ({
  useDeviceStatus: () => ({ data: { linked: true, connected: true } }),
  useLocalFolders: () => ({
    state: {
      data: {
        grants: [
          { path: "/first", mode: "read_only" },
          { path: "/second", mode: "read_only" },
        ],
        modes: ["read_only"],
      },
    },
    pick: { mutate: vi.fn(), isPending: false },
    revoke: { mutate: vi.fn() },
  }),
  useLocalServices: () => ({
    state: {
      data: [
        { id: "model", name: "Local model", kind: "model", model: "installed" },
        { id: "files", name: "Local files", kind: "mcp", model: null },
      ],
    },
  }),
}));
beforeEach(() => {
  useConversationStore.setState({ currentConversationId: "chat" });
  useWorkOnStore.setState({
    byConversation: {
      chat: {
        folder: "/first",
        mode: "read_only",
        model_service: "model",
        mcp_services: ["files"],
        browser: true,
      },
    },
    draft: null,
  });
});
it("keeps local service choices when the approved folder changes", async () => {
  render(<WorkOn />);
  await userEvent.click(screen.getByRole("radio", { name: /second/ }));
  expect(useWorkOnStore.getState().targetFor("chat")).toEqual({
    folder: "/second",
    mode: "read_only",
    model_service: "model",
    mcp_services: ["files"],
    browser: true,
  });
});
it("applies local service choices to this conversation only", async () => {
  const user = userEvent.setup();
  render(<WorkOn />);
  await user.selectOptions(screen.getByRole("combobox"), "");
  for (const checkbox of screen.getAllByRole("checkbox")) await user.click(checkbox);
  expect(useWorkOnStore.getState().targetFor("chat")).toEqual({
    folder: "/first",
    mode: "read_only",
    model_service: null,
    mcp_services: [],
    browser: false,
  });
  expect(useWorkOnStore.getState().targetFor("other")).toBeNull();
});
