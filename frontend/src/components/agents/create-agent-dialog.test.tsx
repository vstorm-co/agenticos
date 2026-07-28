import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateAgentDialog, deriveHandle } from "./create-agent-dialog";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { toast } from "sonner";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** The 409 the registry answers when a name derives a handle already in use. */
const HANDLE_TAKEN = new ApiError(409, "An agent with the handle 'support' already exists", {
  error: {
    code: "ALREADY_EXISTS",
    message: "An agent with the handle 'support' already exists",
    details: { slug: "support" },
  },
});

function open(onCreated = vi.fn()) {
  render(<CreateAgentDialog open onOpenChange={vi.fn()} onCreated={onCreated} />, { wrapper });
  return { onCreated };
}

const name = () => screen.getByLabelText("Name");
const create = () => screen.getByRole("button", { name: "Create" });

describe("deriveHandle", () => {
  it.each([
    ["Support Copilot", "support-copilot"],
    ["  Refunds  ", "refunds"],
    ["Sales / EMEA", "sales-emea"],
    ["Ärger", "rger"],
    // What the backend does with a name that leaves nothing behind. Predicting
    // it is the point: the reader sees the surprise before they cause it.
    ["!!!", "agent"],
  ])("derives %s into @%s, exactly as the backend would", (input, expected) => {
    expect(deriveHandle(input)).toBe(expected);
  });
});

describe("CreateAgentDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  });

  it("shows the handle the name will produce, while it is being typed", async () => {
    // The handle is what a duplicate is refused on, what Slack resolves, and
    // the one thing about an agent that cannot be changed afterwards. A reader
    // told "the handle 'support' is taken" needs to have seen where it came
    // from.
    open();
    await userEvent.type(name(), "Support Copilot");
    expect(screen.getByText("@support-copilot")).toBeInTheDocument();
  });

  it("marks the name and keeps the form when the handle is taken", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(HANDLE_TAKEN);
    const { onCreated } = open();

    await userEvent.type(name(), "Support");
    await userEvent.type(screen.getByLabelText("Description"), "Answers questions.");
    await userEvent.click(create());

    await waitFor(() =>
      expect(
        screen.getByText("An agent with the handle 'support' already exists"),
      ).toBeInTheDocument(),
    );
    // Beside the field, not floating over the page: the input is marked, and
    // the message is what a screen reader reads out for it.
    expect(name()).toHaveAttribute("aria-invalid", "true");
    expect(name()).toHaveAccessibleDescription(/An agent with the handle 'support' already exists/);

    // Everything typed is still there, and nothing has navigated away.
    expect(name()).toHaveValue("Support");
    expect(screen.getByLabelText("Description")).toHaveValue("Answers questions.");
    expect(onCreated).not.toHaveBeenCalled();
    // And it is not also announced as a failure - one problem, one place.
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("clears the mark as soon as the name changes", async () => {
    // The server's verdict was about the value that was sent. Leaving it on a
    // field the reader has since fixed is a form arguing with itself.
    vi.mocked(apiClient.post).mockRejectedValue(HANDLE_TAKEN);
    open();

    await userEvent.type(name(), "Support");
    await userEvent.click(create());
    await waitFor(() => expect(name()).toHaveAttribute("aria-invalid", "true"));

    await userEvent.type(name(), "2");
    expect(name()).not.toHaveAttribute("aria-invalid", "true");
  });

  it("still says something broke when something broke", async () => {
    // The line this must not cross. A 500 is not a hint about the name, and
    // dressing it as one would send somebody editing a field that was fine.
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(500, "An unexpected error occurred", {
        error: { code: "INTERNAL_ERROR", message: "An unexpected error occurred", details: null },
      }),
    );
    open();

    await userEvent.type(name(), "Support");
    await userEvent.click(create());

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("An unexpected error occurred"));
    expect(name()).not.toHaveAttribute("aria-invalid", "true");
  });

  it("cannot send a name longer than the server accepts", async () => {
    // A round trip that can only end in a refusal is one the browser can spare.
    open();
    expect(name()).toHaveAttribute("maxLength", "128");
  });

  it("hands the created agent back and empties itself", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "a1", name: "Support" });
    const { onCreated } = open();

    await userEvent.type(name(), "Support");
    await userEvent.click(create());

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith({ id: "a1", name: "Support" }));
    expect(name()).toHaveValue("");
  });
});
