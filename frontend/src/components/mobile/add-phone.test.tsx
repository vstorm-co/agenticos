import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AddPhone } from "./add-phone";

const create = vi.hoisted(() => vi.fn());
vi.mock("@/lib/pairing-api", async (original) => ({
  ...(await original<typeof import("@/lib/pairing-api")>()),
  createPairingCode: create,
}));

function mount() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AddPhone />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  create.mockReset();
});

afterEach(() => vi.useRealTimers());

describe("AddPhone", () => {
  it("shows a code only on a click, counts it down, and offers a new one once it expires", async () => {
    create.mockResolvedValue({ code: "c0de", expires_in: 3 });
    mount();
    expect(screen.queryByRole("img")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Show a code" }));

    expect(
      await screen.findByRole("img", { name: /signs the AgenticOS app in/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Works for 3 more seconds");
    expect(screen.queryByRole("button", { name: /Show a (new )?code/ })).toBeNull();

    await act(async () => vi.advanceTimersByTimeAsync(3100));

    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("That code has expired.");
    await userEvent.click(screen.getByRole("button", { name: "Show a new code" }));
    expect(create).toHaveBeenCalledTimes(2);
  });

  it("says so when a code could not be made", async () => {
    create.mockRejectedValue(new Error("down"));
    mount();
    await userEvent.click(screen.getByRole("button", { name: "Show a code" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A code could not be made.");
  });
});
