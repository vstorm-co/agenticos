import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { LocalServiceSettings } from "./local-service-settings";

const invoke = vi.hoisted(() => vi.fn());
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/shell")>()),
  invokeShell: invoke,
}));
const service = {
  id: "files",
  name: "My files",
  kind: "mcp",
  endpoint: "http://127.0.0.1:8000/mcp",
  model: null,
};
beforeEach(() => {
  window.__AGENTICOS_SHELL__ = {
    platform: "macos",
    version: "0.2.0",
    window: "main",
    vibrancy: true,
  };
  invoke.mockReset();
  invoke.mockResolvedValue([]);
});
afterEach(() => {
  delete window.__AGENTICOS_SHELL__;
});
function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
        })
      }
    >
      <LocalServiceSettings />
    </QueryClientProvider>,
  );
}
it("lists approved services and removes only the named grant", async () => {
  invoke.mockResolvedValueOnce([service]);
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Remove My files" }));
  await waitFor(() => expect(invoke).toHaveBeenCalledWith("local_remove_service", { id: "files" }));
  await waitFor(() => expect(screen.queryByText("My files")).toBeNull());
});
it("sends the installed model and waits for native confirmation", async () => {
  const user = userEvent.setup();
  mount();
  await user.type(screen.getByLabelText("Name"), "My model");
  await user.type(screen.getByLabelText("Installed model ID"), "installed-model");
  await user.click(screen.getByRole("button", { name: "Connect service" }));
  await waitFor(() =>
    expect(invoke).toHaveBeenCalledWith("local_save_service", {
      service: expect.objectContaining({
        name: "My model",
        kind: "model",
        model: "installed-model",
        endpoint: "http://127.0.0.1:11434/v1",
      }),
    }),
  );
  await waitFor(() => expect(screen.getByLabelText("Name")).toHaveValue(""));
});
it("uses HTTP MCP without asking for a model and reports a native refusal inline", async () => {
  const user = userEvent.setup();
  mount();
  await user.selectOptions(screen.getByLabelText("Service type"), "mcp");
  expect(screen.queryByLabelText("Installed model ID")).toBeNull();
  expect(screen.getByLabelText("Loopback address")).toHaveValue("http://127.0.0.1:8000/mcp");
  await user.type(screen.getByLabelText("Name"), "Files");
  invoke.mockRejectedValueOnce(new Error("Connection cancelled."));
  await user.click(screen.getByRole("button", { name: "Connect service" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Connection cancelled.");
  expect(screen.getByLabelText("Name")).toHaveValue("Files");
});
it("does not call native desktop commands from a phone", async () => {
  window.__AGENTICOS_SHELL__ = {
    platform: "ios",
    version: "0.1.0",
    window: "main",
    vibrancy: false,
  };
  mount();
  expect(invoke).not.toHaveBeenCalled();
});
