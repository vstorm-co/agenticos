import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { useMuseAccount } from "@/hooks/use-muse-account";
import { MuseAccountControls } from "./muse-account-controls";
import { parseMuseAccountProgress, parseMuseAccountStatus } from "@/lib/desktop/commands";

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

function mount(keyOnly = false) {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MuseAccountControls id="my-muse" keyOnly={keyOnly} />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  native.invoke.mockReset();
  native.progress = undefined;
});

it("shows only the native credential source and explains an overriding environment key", async () => {
  native.invoke.mockResolvedValue({
    state: "envKey",
    credentialRequired: true,
    label: "private@example.test",
    apiKey: "never-display",
  });
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Check account" }));
  expect(await screen.findByText(/sign-out cannot remove it/)).toBeVisible();
  expect(screen.queryByText(/private@example|never-display/)).not.toBeInTheDocument();
  expect(native.invoke).toHaveBeenCalledWith(
    "external_muse_account",
    expect.objectContaining({ id: "my-muse", action: "status" }),
  );
});

it("correlates device progress with the initiating native action and cancels that flow", async () => {
  let finish: (value: unknown) => void = () => {};
  const pending = new Promise((resolve) => {
    finish = resolve;
  });
  native.invoke.mockImplementation((command: string) =>
    command === "external_muse_account" ? pending : Promise.resolve(),
  );
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Sign in to Muse" }));
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
    finish({ state: "loggedOut", credentialRequired: true });
    await pending;
  });
  await waitFor(() => expect(screen.queryByText("DEVICE-CODE")).not.toBeInTheDocument());
});

it("does not offer browser sign-in for a required environment-key registration", () => {
  mount(true);
  expect(screen.queryByRole("button", { name: "Sign in to Muse" })).not.toBeInTheDocument();
});

it("cancels the owned sign-in when its UI unmounts", async () => {
  native.invoke.mockImplementation((command: string) =>
    command === "external_muse_account" ? new Promise(() => {}) : Promise.resolve(),
  );
  const view = mount();
  await userEvent.click(screen.getByRole("button", { name: "Sign in to Muse" }));
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
  expect(() => parseMuseAccountStatus({ state: "unknown", credentialRequired: true })).toThrow();
  expect(() =>
    parseMuseAccountProgress({
      requestId: "one",
      verificationUrl: "https://login.example.test",
      userCode: "CODE\u0000",
    }),
  ).toThrow();
});

it("sends sign-out through the native owner and describes a keyless endpoint", async () => {
  native.invoke.mockResolvedValue({ state: "loggedOut", credentialRequired: false });
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Sign out of Muse" }));
  expect(await screen.findByText(/This endpoint requires no credential/)).toBeVisible();
  expect(native.invoke).toHaveBeenCalledWith(
    "external_muse_account",
    expect.objectContaining({ id: "my-muse", action: "sign_out" }),
  );
});

it("ignores malformed account progress and cancels an abandoned native flow even if cleanup fails", async () => {
  native.invoke.mockImplementation((command: string) =>
    command === "external_muse_account"
      ? new Promise(() => {})
      : Promise.reject(new Error("Native owner unavailable")),
  );
  const view = mount();
  await userEvent.click(screen.getByRole("button", { name: "Sign in to Muse" }));
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
  const hook = renderHook(() => useMuseAccount("my-muse"), {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
  act(() => {
    hook.result.current.start("status");
    hook.result.current.start("sign_out");
  });
  await waitFor(() => expect(native.invoke).toHaveBeenCalledTimes(1));
  act(() => finish({ state: "loggedOut", credentialRequired: true }));
  await waitFor(() => expect(hook.result.current.action.isSuccess).toBe(true));
  await act(async () => {
    await hook.result.current.cancel.mutateAsync();
  });
  expect(native.invoke).toHaveBeenCalledTimes(1);
});
