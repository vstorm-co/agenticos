import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
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
// The body is the shared file pane, as the editor has it - editable only once
// the pane is flipped to Source, and named from the file being created, so it is
// asked for by role rather than by a name that moves as somebody types.
const content = () => screen.getByRole("textbox", { name: /source$/ });
const openSource = async () => {
  const source = screen.queryByRole("button", { name: "Source" });
  if (source) await userEvent.click(source);
};
const create = () => screen.getByRole("button", { name: "Create" });

function mount(onOpenChange = vi.fn(), onCreated = vi.fn()) {
  render(<CreateContextDialog open onOpenChange={onOpenChange} onCreated={onCreated} />, {
    wrapper,
  });
  return { onOpenChange, onCreated };
}

describe("CreateContextDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useUnsavedChangesStore.setState({ sources: {}, prompt: null, saving: false });
  });

  it("keeps the audience visible in the mobile details control", async () => {
    mount();
    const details = screen.getByRole("button", { name: "Details · Everyone" });
    expect(details).toHaveAttribute("aria-expanded", "false");
    const panel = document.getElementById(details.getAttribute("aria-controls") ?? "");
    expect(panel).toHaveClass("max-md:hidden");
    await userEvent.click(details);
    expect(details).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(screen.getByRole("radio", { name: /Only me/ }));
    expect(details).toHaveTextContent("Only me");
    await userEvent.click(details);
    expect(panel).toHaveClass("max-md:hidden");
  });

  it("opens mobile details when their hidden field is refused", async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce(
      new ApiError(422, "Invalid description", {
        error: {
          code: "VALIDATION_ERROR",
          message: "Invalid description",
          details: { fields: [{ field: "description", message: "Description needs attention" }] },
        },
      }),
    );
    mount();
    await userEvent.type(name(), "mobile-policy");
    await userEvent.click(create());
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Details · Everyone" })).toHaveAttribute(
        "aria-expanded",
        "true",
      ),
    );
    expect(description()).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Description needs attention")).toBeInTheDocument();
  });

  it("locks the source and dismissal while creating, then retains the draft after refusal", async () => {
    let rejectWrite: (error: Error) => void = () => {
      throw new Error("Not started");
    };
    vi.mocked(apiClient.post).mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          rejectWrite = reject;
        }),
    );
    const { onOpenChange } = mount();
    await userEvent.type(name(), "mobile-policy");
    await userEvent.type(content(), "Keep this policy.");
    await userEvent.click(create());
    await waitFor(() => expect(name()).toBeDisabled());
    expect(content()).toHaveAttribute("readonly");
    expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    await userEvent.keyboard("{Escape}");
    expect(onOpenChange).not.toHaveBeenCalled();
    const proceed = vi.fn();
    act(() => useUnsavedChangesStore.getState().leave(proceed));
    await act(() => useUnsavedChangesStore.getState().answer("save"));
    expect(proceed).not.toHaveBeenCalled();
    await act(async () => rejectWrite(new Error("Controlled refusal")));
    await waitFor(() => expect(name()).toBeEnabled());
    expect(content()).not.toHaveAttribute("readonly");
    expect(content()).toHaveValue("Keep this policy.");
    expect(name()).toHaveAttribute("aria-describedby", "new-context-name-note");
  });

  it("keeps a new draft on Stay and clears it only on Discard", async () => {
    const { onOpenChange } = mount();
    await userEvent.type(name(), "mobile-policy");
    await userEvent.type(content(), "Draft policy.");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(useUnsavedChangesStore.getState().prompt).not.toBeNull();
    await act(() => useUnsavedChangesStore.getState().answer("stay"));
    expect(content()).toHaveValue("Draft policy.");
    await userEvent.keyboard("{Escape}");
    await act(() => useUnsavedChangesStore.getState().answer("discard"));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(name()).toHaveValue("");
    expect(content()).toHaveValue("");
  });

  it("does not save one dropped file and silently abandon the remaining queue on close", async () => {
    render(
      <CreateContextDialog
        open
        initial={{ key: "first", name: "first-policy", format: "md", content: "First policy." }}
        remaining={1}
        onOpenChange={vi.fn()}
        onCreated={vi.fn()}
      />,
      { wrapper },
    );
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    const prompt = useUnsavedChangesStore.getState().prompt;
    expect(prompt).not.toBeNull();
    expect(
      prompt?.ids.every((id) => useUnsavedChangesStore.getState().sources[id]?.save === undefined),
    ).toBe(true);
    await act(() => useUnsavedChangesStore.getState().answer("stay"));
    expect(name()).toHaveValue("first-policy");
    expect(apiClient.post).not.toHaveBeenCalled();
  });

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
      visibility: "org",
      group_ids: [],
      user_ids: [],
    });
    // Reported rather than closed: whether one file created means "done" or
    // "next of the four somebody dropped" is the page's queue to answer.
    expect(onCreated).toHaveBeenCalledWith({ id: "c1", name: "glossary" });
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

  it("infers the renderer from the filename and leaves usage to the builder", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "c1", name: "notes.json" });
    mount();
    await userEvent.type(name(), "notes.json");
    expect(screen.queryByLabelText("Format")).toBeNull();
    expect(screen.queryByLabelText("Mode")).toBeNull();
    await userEvent.click(create());
    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(apiClient.post).toHaveBeenCalledWith(
      "/context",
      expect.objectContaining({ format: "json", mode: "inject" }),
    );
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
