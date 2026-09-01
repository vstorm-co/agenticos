import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateMemoryFileDialog } from "./create-memory-file-dialog";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <div data-testid="rendered">{content}</div>
  ),
}));

import { toast } from "sonner";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const name = () => screen.getByLabelText("Name");
const description = () => screen.getByLabelText("Description");
const format = () => screen.getByLabelText("Format");
const content = () => screen.getByRole("textbox", { name: /source$/ });
const openSource = () => userEvent.click(screen.getByRole("button", { name: "Source" }));
const create = () => screen.getByRole("button", { name: "Create" });

function mount(onOpenChange = vi.fn()) {
  render(<CreateMemoryFileDialog agentId="a1" open onOpenChange={onOpenChange} />, { wrapper });
  return { onOpenChange };
}

describe("CreateMemoryFileDialog", () => {
  beforeEach(() => vi.clearAllMocks());

  it("posts a trusted shared file under the agent, defaulting the empty fields", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "f1", name: "runbook" });
    const { onOpenChange } = mount();

    await userEvent.type(name(), "runbook");
    await openSource();
    await userEvent.type(content(), "steps");
    await userEvent.click(create());

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(apiClient.post).toHaveBeenCalledWith("/memory/files", {
      agent_id: "a1",
      name: "runbook",
      description: null,
      content: "steps",
      format: "md",
      kind: "note",
      end_user_scope_key: null,
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("takes the format from a closed list rather than from typing", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "f1", name: "notes" });
    mount();

    await userEvent.type(name(), "notes");
    await userEvent.click(format());
    await userEvent.click(await screen.findByRole("option", { name: "txt" }));
    await userEvent.click(create());

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(vi.mocked(apiClient.post).mock.calls.at(-1)![1]).toMatchObject({ format: "txt" });
  });

  it("carries an edited kind and description through", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "f1", name: "profile" });
    mount();

    await userEvent.type(name(), "profile");
    await userEvent.clear(screen.getByLabelText("Kind"));
    await userEvent.type(screen.getByLabelText("Kind"), "profile");
    await userEvent.type(description(), "preferred tone");
    await userEvent.click(create());

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(vi.mocked(apiClient.post).mock.calls.at(-1)![1]).toMatchObject({
      kind: "profile",
      description: "preferred tone",
    });
  });

  it("cannot be submitted without a name", () => {
    mount();
    expect(create()).toBeDisabled();
  });

  it("shows a taken name against the field rather than losing the dialog", async () => {
    const TAKEN = "A memory file named 'runbook' already exists.";
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(409, TAKEN, {
        error: { code: "ALREADY_EXISTS", message: TAKEN, details: { name: "runbook" } },
      }),
    );
    const { onOpenChange } = mount();

    await userEvent.type(name(), "runbook");
    await userEvent.click(create());

    await waitFor(() => expect(screen.getByText(TAKEN)).toBeInTheDocument());
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    // Editing the field clears the refusal it was about.
    await userEvent.type(name(), "2");
    expect(screen.queryByText(TAKEN)).not.toBeInTheDocument();
  });

  it("marks every field the server named as wrong", async () => {
    const problems = {
      error: {
        code: "VALIDATION_ERROR",
        message: "invalid",
        details: {
          fields: [
            { field: "kind", message: "not a kind" },
            { field: "content", message: "must be text" },
          ],
        },
      },
    };
    vi.mocked(apiClient.post).mockRejectedValue(new ApiError(422, "invalid", problems));
    mount();

    await userEvent.type(name(), "runbook");
    await userEvent.click(create());

    await waitFor(() => expect(screen.getByText("must be text")).toBeInTheDocument());
    expect(screen.getByText("not a kind")).toBeInTheDocument();
  });

  it("toasts a failure that names no field", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new Error("bad gateway"));
    mount();

    await userEvent.type(name(), "runbook");
    await openSource();
    await userEvent.type(content(), "body");
    await userEvent.click(create());

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("closes without creating when cancelled", async () => {
    const { onOpenChange } = mount();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});
