import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WhatsAppCustomersSheet } from "./whatsapp-customers-sheet";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import type { WhatsAppCustomer } from "@/types/channels";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function customer(overrides: Partial<WhatsAppCustomer> = {}): WhatsAppCustomer {
  return {
    id: "c1",
    bsuid: "PL.1234",
    phone: "48600700800",
    profile_name: "Ana",
    username: "@ana",
    last_message_at: "2026-11-04T09:00:00Z",
    linked: false,
    ...overrides,
  };
}

let customers: WhatsAppCustomer[];

function show() {
  render(<WhatsAppCustomersSheet bot={{ id: "b1", name: "Shop line" }} onClose={vi.fn()} />, {
    wrapper,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  customers = [customer()];
  vi.mocked(apiClient.get).mockImplementation(async () => ({
    items: customers,
    total: customers.length,
  }));
});

describe("a WhatsApp bot's customers", () => {
  it("shows how many there are and loads the next page on request", async () => {
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ items: [customer()], total: 2 })
      .mockResolvedValueOnce({ items: [customer({ id: "c2", phone: "48111222333" })], total: 2 });
    show();

    expect(await screen.findByText("1 of 2 customers")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText("48111222333")).toBeInTheDocument();
    expect(screen.getByText("2 of 2 customers")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("lists each with the full number, an unverified name, the username and the last message", async () => {
    show();

    expect(await screen.findByText("48600700800")).toBeInTheDocument();
    expect(screen.getByText("Ana (unverified)")).toBeInTheDocument();
    expect(screen.getByText("@ana")).toBeInTheDocument();
    expect(screen.getByText(/Last message/)).toBeInTheDocument();
  });

  it("falls back to the stable id for a customer with no number, and says nothing of a missing name", async () => {
    customers = [
      customer({ phone: null, profile_name: null, username: null, last_message_at: null }),
    ];
    show();

    expect(await screen.findByText("PL.1234")).toBeInTheDocument();
    expect(screen.queryByText(/unverified/)).not.toBeInTheDocument();
    expect(screen.getByText("No messages yet")).toBeInTheDocument();
  });

  it("says when there are none", async () => {
    customers = [];
    show();

    expect(await screen.findByText("No customers yet")).toBeInTheDocument();
  });

  it("searches by number: the body carries it and the url does not", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      items: [customer({ id: "c2", phone: "48111222333", profile_name: "Piotr" })],
      total: 1,
    });
    show();
    await screen.findByText("48600700800");

    await userEvent.type(screen.getByLabelText("Search by phone number"), "+48 111 222 333");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(apiClient.post).toHaveBeenCalledWith("/channels/bots/b1/whatsapp-customers/search", {
      phone: "+48 111 222 333",
    });
    for (const [path] of vi.mocked(apiClient.get).mock.calls) {
      expect(String(path)).not.toContain("111");
    }
    expect(await screen.findByText("Piotr (unverified)")).toBeInTheDocument();
    expect(screen.queryByText("Ana (unverified)")).not.toBeInTheDocument();
  });

  it("returns to the whole list when the search is cleared", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ items: [], total: 0 });
    show();
    await screen.findByText("48600700800");
    await userEvent.type(screen.getByLabelText("Search by phone number"), "999");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("No customer has that number")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Show all" }));

    expect(await screen.findByText("48600700800")).toBeInTheDocument();
  });

  it("asks before forgetting, says what it does, and calls only after confirming", async () => {
    vi.mocked(apiClient.post).mockImplementation(async () => {
      customers = [];
      return {};
    });
    show();

    await userEvent.click(await screen.findByRole("button", { name: "Forget Ana" }));

    expect(screen.getByText(/across all of the organization's WhatsApp bots/)).toBeInTheDocument();
    expect(screen.getByText(/cannot be undone/)).toBeInTheDocument();
    expect(screen.getByText(/runs stay as accounting/i)).toBeInTheDocument();
    expect(apiClient.post).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Forget customer" }));

    expect(apiClient.post).toHaveBeenCalledWith("/channels/bots/b1/whatsapp-customers/forget", {
      customer_id: "c1",
    });
    await waitFor(() => expect(screen.queryByText("48600700800")).not.toBeInTheDocument());
  });

  it("can be dismissed without forgetting", async () => {
    show();

    await userEvent.click(await screen.findByRole("button", { name: "Forget Ana" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("shows the server's 409 in the dialog instead of closing", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(409, "This customer has linked an account", {
        error: { code: "CONFLICT", message: "This customer has linked an account", details: {} },
      }),
    );
    show();

    await userEvent.click(await screen.findByRole("button", { name: "Forget Ana" }));
    await userEvent.click(screen.getByRole("button", { name: "Forget customer" }));

    expect(await screen.findByText("This customer has linked an account")).toBeInTheDocument();
  });

  it("shows a refusal that is not an api error too", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new Error("Network down"));
    show();

    await userEvent.click(await screen.findByRole("button", { name: "Forget Ana" }));
    await userEvent.click(screen.getByRole("button", { name: "Forget customer" }));

    expect(await screen.findByText("Network down")).toBeInTheDocument();
  });

  it("marks a linked customer and holds Forget back, saying why", async () => {
    customers = [customer({ linked: true })];
    show();

    expect(await screen.findByText("Linked")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Forget Ana" })).not.toBeInTheDocument();
    expect(screen.getByText(/linked an account, so they are a member/i)).toBeInTheDocument();
  });
});
