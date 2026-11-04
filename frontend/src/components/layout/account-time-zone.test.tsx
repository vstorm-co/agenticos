import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccountTimeZone } from "./account-time-zone";
import { useAuthStore } from "@/stores";
import type { User } from "@/types";

/**
 * The browser's time zone, recorded once on an account that has none - never over
 * one the person chose, or one another device recorded first.
 */

const save = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/use-account-profile", () => ({ useSaveAgentContext: () => save }));

function zoneIs(timeZone: string) {
  vi.spyOn(Intl, "DateTimeFormat").mockReturnValue({
    resolvedOptions: () => ({ timeZone }),
  } as Intl.DateTimeFormat);
}

beforeEach(() => {
  save.mockReset();
  save.mockResolvedValue({});
  zoneIs("Europe/Warsaw");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AccountTimeZone", () => {
  it("records the browser's zone on an account that has none, once", async () => {
    useAuthStore.setState({ user: { id: "u-1", time_zone: null } as User });
    const { rerender } = render(<AccountTimeZone />);
    rerender(<AccountTimeZone />);

    await waitFor(() => expect(save).toHaveBeenCalledWith({ time_zone: "Europe/Warsaw" }));
    expect(save).toHaveBeenCalledTimes(1);
  });

  it("keeps a zone the account already has", () => {
    useAuthStore.setState({ user: { id: "u-1", time_zone: "America/New_York" } as User });
    render(<AccountTimeZone />);

    expect(save).not.toHaveBeenCalled();
  });

  it("waits for somebody to be signed in, and records nothing the browser does not know", () => {
    useAuthStore.setState({ user: null });
    render(<AccountTimeZone />);
    expect(save).not.toHaveBeenCalled();

    zoneIs("");
    useAuthStore.setState({ user: { id: "u-2", time_zone: null } as User });
    expect(save).not.toHaveBeenCalled();
  });

  it("lets a refused save go, for the next page load to try again", async () => {
    save.mockRejectedValue(new Error("offline"));
    useAuthStore.setState({ user: { id: "u-1", time_zone: null } as User });

    render(<AccountTimeZone />);

    await waitFor(() => expect(save).toHaveBeenCalled());
  });
});
