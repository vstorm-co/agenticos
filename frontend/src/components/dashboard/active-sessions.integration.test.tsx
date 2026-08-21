import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render as renderBare, screen, waitFor } from "@testing-library/react";
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

/**
 * The component reads its sessions through the query layer now, so it needs a
 * client. A fresh one per render, with retries off: a test that retries a
 * deliberate failure three times is a test that takes three seconds to say the
 * same thing.
 *
 * `staleTime` matches `src/app/providers.tsx`, and it is load-bearing. At the
 * library default of 0 every remount refetches, so a page served from cache
 * looks identical to a page that was invalidated - and a test written against
 * that harness passes whether or not the invalidation it is checking exists.
 */
function render(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 5 * 60 * 1000 } },
  });
  return renderBare(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

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
    // Two endpoints, and they are not the same shape: `/sessions/{id}` drops
    // one row, `/sessions` drops every device except the one asking. Splicing
    // by a trailing path segment served both and quietly turned "revoke all"
    // into "revoke the last one".
    if (url === "/sessions") {
      rows.splice(0, rows.length, ...rows.filter((row) => row.is_current));
      return undefined;
    }
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

  it("keeps the current page on screen while the next one is in flight", async () => {
    // Hold the second page open so the in-flight state is observable rather
    // than a microtask that resolves before the assertions run.
    const rows = Array.from({ length: 12 }, (_, i) => session(i + 1));
    let releaseSecondPage!: () => void;
    const secondPage = new Promise<void>((resolve) => {
      releaseSecondPage = resolve;
    });
    vi.mocked(apiClient.get).mockImplementation(async (_url, options) => {
      const params = (options as { params: Record<string, string> }).params;
      const skip = Number(params.skip);
      if (skip > 0) await secondPage;
      return { items: rows.slice(skip, skip + Number(params.limit)), total: rows.length };
    });

    const user = userEvent.setup();
    render(<ActiveSessions />);
    await screen.findByText("Device 1");

    await user.click(screen.getByLabelText("Next page"));

    expect(screen.getByText("Device 1")).toBeInTheDocument();
    const heldList = screen.getByRole("list");
    expect(heldList).toHaveAttribute("aria-busy", "true");
    // Inert, so a keyboard or assistive technology cannot reach a revoke button
    // on the held page and revoke the wrong page's session (#944).
    expect(heldList).toHaveAttribute("inert");
    expect(screen.getByLabelText("Next page")).toBeDisabled();

    releaseSecondPage();

    await screen.findByText("Device 6");
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
    expect(screen.getByLabelText("Next page")).toBeDisabled();
  });

  it("shows no revoked device after revoking every other one from a later page", async () => {
    // "Revoke all others" from page two steps back to page one, which is
    // already cached. Refreshing only the page on screen left the five devices
    // it had just revoked listed there for as long as the cache held them.
    server(6);
    render(<ActiveSessions />);
    await screen.findByText("Device 1");
    await userEvent.click(screen.getByLabelText("Next page"));
    await screen.findByText("Device 6");

    await userEvent.click(screen.getByRole("button", { name: "Revoke all others" }));
    await userEvent.click(screen.getByRole("button", { name: "Revoke all" }));

    await waitFor(() => expect(apiClient.delete).toHaveBeenCalledWith("/sessions"));
    await waitFor(() => expect(screen.queryByText("Device 1")).not.toBeInTheDocument());
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
