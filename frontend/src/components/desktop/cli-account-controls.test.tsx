import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { useCliAccount } from "@/hooks/use-cli-account";
import { CliAccountControls } from "./cli-account-controls";
import { parseMuseAccountProgress, parseCliAccountStatus } from "@/lib/desktop/commands";

const native = vi.hoisted(() => ({
  invoke: vi.fn(),
  progress: undefined as ((payload: unknown) => void) | undefined,
}));
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/shell")>()),
  invokeShell: native.invoke,
}));
vi.mock("@/hooks/use-desktop", () => ({
  useShellEvent: (_event: string, handler: (payload: unknown) => void) => {
    native.progress = handler;
  },
}));

function mount() {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <CliAccountControls id="my-cli" />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  native.invoke.mockReset();
  native.progress = undefined;
});

it("shows only the native credential source and explains an overriding environment key", async () => {
  native.invoke.mockResolvedValue({
    state: "environment_key",
    signOutAvailable: false,
    label: "private@example.test",
    apiKey: "never-display",
  });
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Check account" }));
  expect(await screen.findByText(/inherited environment key/)).toBeVisible();
  expect(screen.queryByText(/private@example|never-display/)).not.toBeInTheDocument();
  expect(native.invoke).toHaveBeenCalledWith(
    "external_cli_account",
    expect.objectContaining({ id: "my-cli", action: "status" }),
  );
});

it("correlates device progress with the initiating native action and cancels that flow", async () => {
  let finish: (value: unknown) => void = () => {};
  const pending = new Promise((resolve) => {
    finish = resolve;
  });
  native.invoke.mockImplementation((command: string) =>
    command === "external_cli_account" ? pending : Promise.resolve(),
  );
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
  await waitFor(() => expect(native.invoke).toHaveBeenCalled());
  const requestId: unknown = native.invoke.mock.calls[0]?.[1]?.requestId;
  expect(typeof requestId).toBe("string");
  act(() =>
    native.progress?.({
      requestId: "old-request",
      verificationUrl: "https://login.example.test/device",
      userCode: "STALE",
    }),
  );
  expect(screen.queryByText("STALE")).not.toBeInTheDocument();
  act(() =>
    native.progress?.({
      requestId,
      verificationUrl: "https://login.example.test/device",
      userCode: "DEVICE-CODE",
    }),
  );
  expect(screen.getByText("DEVICE-CODE")).toBeVisible();
  expect(screen.getByRole("link")).toHaveAttribute("href", "https://login.example.test/device");
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(native.invoke).toHaveBeenCalledWith("external_cancel_muse_account", { requestId });
  await act(async () => {
    finish({ state: "signed_out", signOutAvailable: true });
    await pending;
  });
  await waitFor(() => expect(screen.queryByText("DEVICE-CODE")).not.toBeInTheDocument());
});

it("cancels the owned sign-in when its UI unmounts", async () => {
  native.invoke.mockImplementation((command: string) =>
    command === "external_cli_account" ? new Promise(() => {}) : Promise.resolve(),
  );
  const view = mount();
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
  const requestId: unknown = native.invoke.mock.calls[0]?.[1]?.requestId;
  view.unmount();
  expect(native.invoke).toHaveBeenCalledWith("external_cancel_muse_account", { requestId });
});

it("does not show native error bodies that could contain credentials", async () => {
  native.invoke.mockRejectedValue(new Error("private-token-never-display"));
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Check account" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Account operation did not complete");
  expect(screen.queryByText(/private-token-never-display/)).not.toBeInTheDocument();
});

it.each([
  "http://login.example.test",
  "https://user:password@login.example.test",
  "javascript:alert(1)",
])("refuses an unsafe device address: %s", (verificationUrl) => {
  expect(() =>
    parseMuseAccountProgress({ requestId: "one", verificationUrl, userCode: "CODE" }),
  ).toThrow();
});
it("refuses unknown account states and control characters in device codes", () => {
  expect(() => parseCliAccountStatus({ state: "bad", signOutAvailable: true })).toThrow();
  expect(() =>
    parseMuseAccountProgress({
      requestId: "one",
      verificationUrl: "https://login.example.test",
      userCode: "CODE\u0000",
    }),
  ).toThrow();
});

it("sends sign-out through the native owner", async () => {
  native.invoke.mockResolvedValue({ state: "signed_out", signOutAvailable: true });
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
  expect(await screen.findByText(/CLI is signed out/)).toBeVisible();
  expect(native.invoke).toHaveBeenCalledWith(
    "external_cli_account",
    expect.objectContaining({ id: "my-cli", action: "sign_out" }),
  );
});

it("ignores malformed account progress and cancels an abandoned native flow even if cleanup fails", async () => {
  native.invoke.mockImplementation((command: string) =>
    command === "external_cli_account"
      ? new Promise(() => {})
      : Promise.reject(new Error("Native owner unavailable")),
  );
  const view = mount();
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
  const requestId: unknown = native.invoke.mock.calls[0]?.[1]?.requestId;
  act(() =>
    native.progress?.({ requestId, verificationUrl: "javascript:invalid", userCode: "CODE" }),
  );
  expect(screen.queryByText("CODE")).not.toBeInTheDocument();
  view.unmount();
  await waitFor(() =>
    expect(native.invoke).toHaveBeenCalledWith("external_cancel_muse_account", { requestId }),
  );
});

it("admits one account operation at a time and ignores cancellation after settlement", async () => {
  let finish: (value: unknown) => void = () => {};
  native.invoke.mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const hook = renderHook(() => useCliAccount("my-cli"), {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
  act(() => {
    hook.result.current.start("status");
    hook.result.current.start("sign_out");
  });
  await waitFor(() => expect(native.invoke).toHaveBeenCalledTimes(1));
  act(() => finish({ state: "signed_out", signOutAvailable: true }));
  await waitFor(() => expect(hook.result.current.action.isSuccess).toBe(true));
  await act(async () => {
    await hook.result.current.cancel.mutateAsync();
  });
  expect(native.invoke).toHaveBeenCalledTimes(1);
});

it("reconnects through the native owner and disables unavailable vendor sign-out", async () => {
  native.invoke.mockResolvedValue({ state: "environment_key", signOutAvailable: false });
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Reconnect account" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Sign out" })).toBeDisabled());
  expect(native.invoke).toHaveBeenCalledWith(
    "external_cli_account",
    expect.objectContaining({ action: "reconnect" }),
  );
});

it.each(["signed_in", "unknown"])(
  "renders only the bounded native account state %s",
  async (state) => {
    native.invoke.mockResolvedValue({ state, signOutAvailable: true });
    mount();
    await userEvent.click(screen.getByRole("button", { name: "Check account" }));
    expect(await screen.findByRole("status")).toBeVisible();
  },
);
