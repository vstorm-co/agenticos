import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ActiveSessions } from "./active-sessions";
import { apiClient } from "@/lib/api-client";
import type { Session } from "@/types";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), delete: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const PAGE_SIZE = 5;

function session(n: number): Session {
  return {
    id: `s${n}`,
    device_name: `Device ${n}`,
    device_type: "desktop",
    ip_address: `203.0.113.${n}`,
    is_current: false,
    created_at: "2026-07-01T00:00:00Z",
    last_used_at: "2026-07-01T00:00:00Z",
  };
}

/**
 * A server that actually holds the rows.
 *
 * Paging and revoking are only interesting together - the case worth a test is a
 * revocation that empties the page the user is standing on - and a stubbed
 * response per call cannot show that. This one serves whatever slice is asked
 * for and shrinks when a row is deleted, so the assertions are about what the
 * component does with a moving list.
 */
function server(count: number) {
  const rows = Array.from({ length: count }, (_, i) => session(i + 1));

  vi.mocked(apiClient.get).mockImplementation(async (_url, options) => {
    const params = (options as { params: Record<string, string> }).params;
    const skip = Number(params.skip);
    return { items: rows.slice(skip, skip + Number(params.limit)), total: rows.length };
  });
  vi.mocked(apiClient.delete).mockImplementation(async (url) => {
    const id = url.split("/").pop();
    rows.splice(
      rows.findIndex((row) => row.id === id),
      1,
    );
    return undefined;
  });

  return rows;
}

function lastRequest(): Record<string, string> {
  const last = vi.mocked(apiClient.get).mock.calls.at(-1);
  if (!last) throw new Error("the component never asked for a page");
  return (last[1] as { params: Record<string, string> }).params;
}

function firstRevokeButton(): HTMLElement {
  const [button] = screen.getAllByLabelText("Revoke session");
  if (!button) throw new Error("no session on screen to revoke");
  return button;
}

describe("ActiveSessions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("asks for one page rather than every device the account ever signed in from", async () => {
    server(12);
    render(<ActiveSessions />);

    await screen.findByText("Device 1");
    expect(lastRequest()).toEqual({ skip: "0", limit: String(PAGE_SIZE) });
    expect(screen.queryByText("Device 6")).not.toBeInTheDocument();
    expect(screen.getByText("1 / 3")).toBeInTheDocument();
  });

  it("fetches the next page from the server", async () => {
    server(12);
    render(<ActiveSessions />);
    await screen.findByText("Device 1");

    await userEvent.click(screen.getByLabelText("Next page"));

    await screen.findByText("Device 6");
    expect(lastRequest().skip).toBe("5");
    expect(screen.queryByText("Device 1")).not.toBeInTheDocument();
  });

  it("revokes a session that is not on the first page", async () => {
    const rows = server(12);
    render(<ActiveSessions />);
    await screen.findByText("Device 1");
    await userEvent.click(screen.getByLabelText("Next page"));
    await screen.findByText("Device 6");

    await userEvent.click(firstRevokeButton());

    expect(apiClient.delete).toHaveBeenCalledWith("/sessions/s6");
    await waitFor(() => expect(rows).toHaveLength(11));
  });

  it("steps back a page when the row it revoked was the last one on it", async () => {
    // Six sessions: five on the first page, one alone on the second.
    server(6);
    render(<ActiveSessions />);
    await screen.findByText("Device 1");
    await userEvent.click(screen.getByLabelText("Next page"));
    await screen.findByText("Device 6");

    await userEvent.click(firstRevokeButton());

    // Not an empty card on a page that no longer exists.
    await screen.findByText("Device 1");
    expect(lastRequest().skip).toBe("0");
    expect(screen.queryByLabelText("Next page")).not.toBeInTheDocument();
  });

  it("hides itself when the deployment has no session endpoint", async () => {
    const { ApiError } =
      await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(404, "Not Found"));

    const { container } = render(<ActiveSessions />);

    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("says the request failed instead of saying there are no other devices", async () => {
    const { ApiError } =
      await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(500, "Internal server error"));

    render(<ActiveSessions />);

    // "No session data available" for a request that never answered is how a
    // stolen device stays invisible on the page built to show it.
    expect(await screen.findByText(/Internal server error/)).toBeInTheDocument();
    expect(screen.queryByText("No session data available.")).not.toBeInTheDocument();
  });
});
