import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import type { DeviceStatus, LocalGrant } from "@/lib/desktop/commands";
import { ProjectFolderChoice } from "./project-folder-choice";
const native = vi.hoisted(() => ({
  pick: vi.fn<(mode: string) => Promise<LocalGrant | null>>(),
  link: vi.fn<() => Promise<DeviceStatus>>(),
  linked: true,
}));
vi.mock("@/hooks/use-shell", () => ({
  useShell: () => ({ platform: "macos", window: "main", version: "0.2.0", vibrancy: false }),
}));
vi.mock("@/lib/desktop/commands", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/commands")>()),
  pickLocalFolder: native.pick,
  getLocalState: async () => ({ grants: [], modes: ["read_only", "workspace_write"] }),
}));
vi.mock("@/hooks/use-desktop", async (original) => ({
  ...(await original<typeof import("@/hooks/use-desktop")>()),
  useDeviceStatus: () => ({ data: { linked: native.linked, connected: true } }),
  useDeviceLink: () => ({ link: { mutateAsync: native.link } }),
}));
function mount() {
  const change = vi.fn();
  const view = render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <ProjectFolderChoice value={null} onChange={change} />
    </QueryClientProvider>,
  );
  return { ...view, change };
}
beforeEach(() => {
  native.pick.mockReset();
  native.link.mockReset();
  native.linked = true;
});
it("starts read-only and preserves a cancelled picker", async () => {
  native.pick.mockResolvedValue(null);
  const view = mount();
  const button = screen.getByRole("button", { name: "Connect a folder" });
  await waitFor(() => expect(button).toBeEnabled());
  await userEvent.click(button);
  await waitFor(() => expect(native.pick).toHaveBeenCalledWith("read_only"));
  expect(view.change).not.toHaveBeenCalled();
});
it("links first and saves the approved folder after the panel unmounts", async () => {
  native.linked = false;
  native.link.mockResolvedValue({ linked: true, connected: true });
  let finish: (grant: LocalGrant | null) => void = () => {
    throw new Error("Not started");
  };
  native.pick.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const view = mount();
  const button = screen.getByRole("button", { name: "Connect a folder" });
  await waitFor(() => expect(button).toBeEnabled());
  await userEvent.selectOptions(screen.getByRole("combobox"), "workspace_write");
  await userEvent.click(button);
  await waitFor(() => expect(native.pick).toHaveBeenCalledWith("workspace_write"));
  view.unmount();
  await act(async () => finish({ path: "/approved", mode: "workspace_write" }));
  await waitFor(() =>
    expect(view.change).toHaveBeenCalledWith({ folder: "/approved", mode: "workspace_write" }),
  );
});
it("does not pick when device linking was cancelled", async () => {
  native.linked = false;
  native.link.mockResolvedValue({ linked: false, connected: false });
  const view = mount();
  const button = screen.getByRole("button", { name: "Connect a folder" });
  await waitFor(() => expect(button).toBeEnabled());
  await userEvent.click(button);
  await waitFor(() => expect(native.link).toHaveBeenCalledOnce());
  expect(native.pick).not.toHaveBeenCalled();
  expect(view.change).not.toHaveBeenCalled();
});

it("disconnects the approved folder without opening a picker", async () => {
  const change = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ProjectFolderChoice value={{ folder: "/approved", mode: "read_only" }} onChange={change} />
    </QueryClientProvider>,
  );
  await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
  expect(change).toHaveBeenCalledWith(null);
  expect(native.pick).not.toHaveBeenCalled();
});
