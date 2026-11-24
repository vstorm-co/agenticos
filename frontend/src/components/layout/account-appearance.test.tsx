import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";

import { qk } from "@/lib/query-keys";
import { DEFAULT_APPEARANCE } from "@/lib/user-appearance";
import { AccountAppearance } from "./account-appearance";

const state = vi.hoisted(() => ({
  appearance: vi.fn(),
  adopt: vi.fn(),
}));
vi.mock("@/hooks/use-user-appearance", () => ({ useUserAppearance: state.appearance }));
vi.mock("@/lib/account-appearance", () => ({ adoptAccountAppearance: state.adopt }));

function mount(client = new QueryClient()) {
  render(
    <QueryClientProvider client={client}>
      <AccountAppearance />
    </QueryClientProvider>,
  );
  return client;
}

beforeEach(() => vi.clearAllMocks());

it("adopts an acknowledged account appearance for its owner and epoch", () => {
  state.appearance.mockReturnValue({ owner: "alice", epoch: 3, preferences: DEFAULT_APPEARANCE });
  mount();
  expect(state.adopt).toHaveBeenCalledWith("alice", 3, DEFAULT_APPEARANCE);
});

it("adopts nothing before an owner, epoch and preferences are all known", () => {
  state.appearance.mockReturnValue({ owner: "alice", epoch: undefined, preferences: undefined });
  mount();
  expect(state.adopt).not.toHaveBeenCalled();
});

it("rereads the owner's appearance when an agent or another surface changes it", () => {
  state.appearance.mockReturnValue({ owner: "alice", epoch: 1, preferences: DEFAULT_APPEARANCE });
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  mount(client);
  window.dispatchEvent(new Event("account-appearance-changed"));
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.auth.appearance("alice") });
});

it("ignores an appearance change signalled while nobody is signed in", () => {
  state.appearance.mockReturnValue({ owner: undefined, epoch: undefined, preferences: undefined });
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  mount(client);
  window.dispatchEvent(new Event("account-appearance-changed"));
  expect(invalidate).not.toHaveBeenCalled();
});
