import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ApnsSetup } from "@/lib/mobile/apns";

import { ApnsKeyCard } from "./apns-key-card";

const NONE: ApnsSetup = {
  configured: false,
  key_id: null,
  team_id: null,
  topic: null,
  environment: null,
};
const SET: ApnsSetup = {
  configured: true,
  key_id: "KEY1234567",
  team_id: "TEAM123456",
  topic: "com.acme.app",
  environment: "sandbox",
};
const P8 = "the contents of AuthKey_KEY1234567.p8";

const env = vi.hoisted(() => ({
  read: vi.fn(),
  set: vi.fn(),
  clear: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
}));
vi.mock("@/lib/mobile/apns", () => ({
  apnsSetup: env.read,
  setApnsKey: env.set,
  clearApnsKey: env.clear,
}));
vi.mock("sonner", () => ({ toast: { success: env.success, error: env.error } }));

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ApnsKeyCard />
    </QueryClientProvider>,
  );
}

async function fill() {
  await userEvent.type(await screen.findByLabelText("Key ID"), "key1234567");
  await userEvent.type(screen.getByLabelText("Team ID"), "team123456");
  await userEvent.type(screen.getByLabelText("Bundle ID"), " com.acme.app ");
  await userEvent.upload(
    screen.getByLabelText("Key file (.p8)"),
    new File([P8], "AuthKey_KEY1234567.p8"),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  env.read.mockResolvedValue(NONE);
});

describe("ApnsKeyCard", () => {
  it("takes the key from Apple's file and its three names, then shows whose it is", async () => {
    env.set.mockResolvedValue(SET);
    mount();
    const save = await screen.findByRole("button", { name: "Save key" });
    expect(save).toBeDisabled();
    await fill();
    await userEvent.click(save);
    await waitFor(() =>
      expect(env.set).toHaveBeenCalledWith({
        key_id: "KEY1234567",
        team_id: "TEAM123456",
        topic: "com.acme.app",
        environment: "production",
        private_key: P8,
      }),
    );
    expect(await screen.findByText("Key KEY1234567, team TEAM123456, development")).toBeVisible();
    expect(env.success).toHaveBeenCalled();
  });

  it("replaces a key, or goes back to the one it has", async () => {
    env.read.mockResolvedValue(SET);
    env.set.mockRejectedValueOnce(new Error("That is not an APNs key"));
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Replace" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "Replace" }));
    await fill();
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(await screen.findByRole("option", { name: "development" }));
    await userEvent.click(screen.getByRole("button", { name: "Save key" }));
    await waitFor(() => expect(env.error).toHaveBeenCalled());
    expect(env.set.mock.calls[0]?.[0]).toMatchObject({ environment: "sandbox" });
  });

  it("removes the key", async () => {
    env.read.mockResolvedValue(SET);
    env.clear.mockResolvedValueOnce(NONE);
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Remove" }));
    expect(await screen.findByRole("button", { name: "Save key" })).toBeInTheDocument();
    expect(env.success).toHaveBeenCalledWith(expect.stringContaining("Removed"));
  });

  it("says when the key could not be removed", async () => {
    env.read.mockResolvedValue(SET);
    env.clear.mockRejectedValueOnce(new Error("down"));
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Remove" }));
    await waitFor(() => expect(env.error).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Replace" })).toBeInTheDocument();
  });

  it("shows nothing until it knows", () => {
    env.read.mockReturnValue(new Promise(() => {}));
    const { container } = mount();
    expect(container).toBeEmptyDOMElement();
  });
});
