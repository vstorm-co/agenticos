import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateContextDialog } from "./create-context-dialog";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { toast } from "sonner";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const TAKEN = "A context file named 'glossary' already exists.";
const NAME_TAKEN = new ApiError(409, TAKEN, {
  error: { code: "ALREADY_EXISTS", message: TAKEN, details: { name: "glossary" } },
});

const name = () => screen.getByLabelText("Name");
const description = () => screen.getByLabelText("Description");
const format = () => screen.getByLabelText("Format");
// The body is the shared file pane, as the editor has it - editable only once
// the pane is flipped to Source, and named from the file being created, so it is
// asked for by role rather than by a name that moves as somebody types.
const content = () => screen.getByRole("textbox", { name: /source$/ });
const openSource = () => userEvent.click(screen.getByRole("button", { name: "Source" }));
const create = () => screen.getByRole("button", { name: "Create" });

function mount(onOpenChange = vi.fn(), onCreated = vi.fn()) {
  render(<CreateContextDialog open onOpenChange={onOpenChange} onCreated={onCreated} />, {
    wrapper,
  });
  return { onOpenChange, onCreated };
}

describe("CreateContextDialog", () => {
  beforeEach(() => vi.clearAllMocks());

  it("creates an injected file by default and reports it", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "c1", name: "glossary" });
    const { onCreated } = mount();

    await userEvent.type(name(), "glossary");
    await userEvent.type(description(), "terms");
    await openSource();
    await userEvent.type(content(), "SLA: ...");
    await userEvent.click(create());

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(apiClient.post).toHaveBeenCalledWith("/context", {
      name: "glossary",
      description: "terms",
      content: "SLA: ...",
      format: "md",
      mode: "inject",
    });
    // Reported rather than closed: whether one file created means "done" or
    // "next of the four somebody dropped" is the page's queue to answer.
    expect(onCreated).toHaveBeenCalled();
  });

  it("sends an untouched description as null and Markdown as the default format", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "c1", name: "glossary" });
    mount();

    await userEvent.type(name(), "glossary");
    await openSource();
    await userEvent.type(content(), "body");
    await userEvent.click(create());

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    const [, payload] = vi.mocked(apiClient.post).mock.calls.at(-1)!;
    expect(payload).toMatchObject({ description: null, format: "md" });
  });

  it("takes the format from a closed list rather than from typing", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "c1", name: "notes" });
    mount();

    await userEvent.type(name(), "notes");
    await userEvent.click(format());
    await userEvent.click(await screen.findByRole("option", { name: "txt" }));
    await userEvent.click(create());

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(vi.mocked(apiClient.post).mock.calls.at(-1)![1]).toMatchObject({ format: "txt" });
  });

  it("lets the author choose to link a file instead of injecting it", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "c1", name: "runbook" });
    mount();

    await userEvent.type(name(), "runbook");
    await userEvent.click(screen.getByLabelText("Mode"));
    await userEvent.click(await screen.findByRole("option", { name: "linked" }));
    await openSource();
    await userEvent.type(content(), "steps");
    await userEvent.click(create());

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(vi.mocked(apiClient.post).mock.calls.at(-1)![1]).toMatchObject({ mode: "link" });
  });

  it("cannot be submitted without a name", () => {
    mount();
    expect(create()).toBeDisabled();
  });

  it("shows a taken name against the field rather than losing the dialog", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(NAME_TAKEN);
    const { onCreated } = mount();

    await userEvent.type(name(), "glossary");
    await openSource();
    await userEvent.type(content(), "body");
    await userEvent.click(create());

    await waitFor(() => expect(screen.getByText(TAKEN)).toBeInTheDocument());
    expect(onCreated).not.toHaveBeenCalled();
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
            { field: "description", message: "too long" },
            { field: "format", message: "not a format" },
            { field: "content", message: "must be text" },
          ],
        },
      },
    };
    vi.mocked(apiClient.post).mockRejectedValue(new ApiError(422, "invalid", problems));
    mount();

    await userEvent.type(name(), "glossary");
    await userEvent.click(create());

    await waitFor(() => expect(screen.getByText("must be text")).toBeInTheDocument());
    expect(screen.getByText("too long")).toBeInTheDocument();
    expect(screen.getByText("not a format")).toBeInTheDocument();
  });

  it("toasts a failure that names no field", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new Error("bad gateway"));
    mount();

    await userEvent.type(name(), "glossary");
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
