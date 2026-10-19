import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConsentScreen } from "./consent-screen";
import type { OAuthConsentRequest } from "@/types/mcp-oauth";

const useConsentRequestMock = vi.fn();
const switchOrg = vi.fn();
const toastError = vi.fn();

vi.mock("@/hooks", () => ({
  useConsentRequest: (...args: unknown[]) => useConsentRequestMock(...args),
  useOrganizations: () => ({
    orgs: [
      { id: "o1", name: "Acme" },
      { id: "o2", name: "Globex" },
    ],
    switchOrg,
  }),
}));
vi.mock("sonner", () => ({ toast: { error: (...args: unknown[]) => toastError(...args) } }));

const REQUEST: OAuthConsentRequest = {
  request_id: "r1",
  client_name: "Claude Code",
  client_uri: null,
  redirect_host: "127.0.0.1:33418",
  organization_id: "o1",
  organization_name: "Acme",
  catalog: {
    scopes: ["agents:view", "agents:edit"],
    presets: [{ id: "read_only", scopes: ["agents:view"] }],
  },
};

function state(overrides: Record<string, unknown> = {}) {
  return {
    request: REQUEST,
    isLoading: false,
    error: null,
    approve: {
      mutateAsync: vi.fn().mockResolvedValue({ redirect_to: "http://cb?code=x" }),
      isPending: false,
    },
    deny: {
      mutateAsync: vi.fn().mockResolvedValue({ redirect_to: "http://cb?error=access_denied" }),
      isPending: false,
    },
    ...overrides,
  };
}

describe("ConsentScreen", () => {
  const assign = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(window, "location", { value: { assign }, writable: true });
  });

  it("names who is asking and where the answer goes, and allows with the chosen access", async () => {
    const current = state();
    useConsentRequestMock.mockReturnValue(current);
    render(<ConsentScreen requestId="r1" />);

    expect(
      screen.getByRole("heading", { name: "Claude Code wants to act as you" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/127\.0\.0\.1:33418/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Allow" }));

    expect(current.approve.mutateAsync).toHaveBeenCalledWith(["agents:view"]);
    expect(assign).toHaveBeenCalledWith("http://cb?code=x");
  });

  it("denies, and switches organization from the picker", async () => {
    const current = state();
    useConsentRequestMock.mockReturnValue(current);
    render(<ConsentScreen requestId="r1" />);

    await userEvent.click(screen.getByLabelText("Organization"));
    await userEvent.click(await screen.findByRole("option", { name: "Globex" }));
    await userEvent.click(screen.getByRole("button", { name: "Deny" }));

    expect(switchOrg).toHaveBeenCalledWith("o2");
    expect(assign).toHaveBeenCalledWith("http://cb?error=access_denied");
  });

  it("stays put and says why when the answer is refused", async () => {
    useConsentRequestMock.mockReturnValue(
      state({
        approve: { mutateAsync: vi.fn().mockRejectedValue(new Error("no")), isPending: false },
      }),
    );
    render(<ConsentScreen requestId="r1" />);

    await userEvent.click(screen.getByRole("button", { name: "Allow" }));

    expect(toastError).toHaveBeenCalled();
    expect(assign).not.toHaveBeenCalled();
  });

  it("says an expired request has expired, and waits while loading", () => {
    useConsentRequestMock.mockReturnValue(state({ request: null, error: new Error("404") }));
    const { rerender } = render(<ConsentScreen requestId="r1" />);
    expect(screen.getByText("This request has expired")).toBeInTheDocument();

    useConsentRequestMock.mockReturnValue(state({ request: null, isLoading: true }));
    rerender(<ConsentScreen requestId="r1" />);
    expect(screen.queryByText("This request has expired")).not.toBeInTheDocument();
  });
});
