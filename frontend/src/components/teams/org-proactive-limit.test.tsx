import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrgProactiveLimit } from "./org-proactive-limit";
import type { Organization } from "@/types";

/**
 * What background work may spend per person a month (#2301): shown only to who
 * may change spending limits, zero is off, and a refusal lands under the input.
 */

const state = vi.hoisted(() => ({ manages: true, set: vi.fn() }));
const toastSuccess = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());

vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: () => state.manages }),
  useOrganizations: () => ({ setProactiveLimit: state.set }),
}));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError } }));
const refusal = vi.hoisted(() => ({
  value: null as null | { fields: Record<string, string>; toast: string | null },
}));
vi.mock("@/lib/api-error", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-error")>();
  return {
    ...actual,
    submitFailure: (...args: Parameters<typeof actual.submitFailure>) =>
      refusal.value ?? actual.submitFailure(...args),
  };
});

const org = (limit?: string) =>
  ({ id: "o1", name: "Acme", proactive_limit_usd: limit }) as unknown as Organization;

const box = () => screen.getByLabelText("Limit per person (USD)");

beforeEach(() => {
  refusal.value = null;
  state.manages = true;
  state.set.mockReset().mockResolvedValue({});
  toastSuccess.mockReset();
  toastError.mockReset();
});

describe("OrgProactiveLimit", () => {
  it("is not there for somebody who may not change spending limits", () => {
    state.manages = false;
    const { container } = render(<OrgProactiveLimit org={org("1.000000")} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("reads the stored limit as typed, and a dollar before the first save", () => {
    const { unmount } = render(<OrgProactiveLimit org={org("2.500000")} />);
    expect(box()).toHaveValue(2.5);
    unmount();

    render(<OrgProactiveLimit org={org()} />);
    expect(box()).toHaveValue(1);
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("saves a new limit, and says so when zero switches the work off", async () => {
    render(<OrgProactiveLimit org={org("1")} />);

    await userEvent.clear(box());
    await userEvent.type(box(), "0");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(state.set).toHaveBeenCalledWith("o1", 0);
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Background work is off"));
  });

  it("refuses an empty or negative limit before asking", async () => {
    render(<OrgProactiveLimit org={org("1")} />);

    await userEvent.clear(box());
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(screen.getByText("Enter an amount in dollars, 0 or more.")).toBeInTheDocument();
    expect(state.set).not.toHaveBeenCalled();
  });

  it("shows the server's refusal and lets it be tried again", async () => {
    state.set.mockRejectedValue(new Error("no"));
    render(<OrgProactiveLimit org={org("1")} />);

    await userEvent.clear(box());
    await userEvent.type(box(), "3");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("puts a refusal that names the field under the input", async () => {
    refusal.value = { fields: { proactive_limit_usd: "Too much" }, toast: null };
    state.set.mockRejectedValue(new Error("no"));
    render(<OrgProactiveLimit org={org("1")} />);

    await userEvent.clear(box());
    await userEvent.type(box(), "900");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Too much")).toBeInTheDocument();
    expect(toastError).not.toHaveBeenCalled();
  });

  it("thanks a saved positive limit", async () => {
    render(<OrgProactiveLimit org={org("1")} />);

    await userEvent.clear(box());
    await userEvent.type(box(), "5");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Limit per person updated"));
  });
});
