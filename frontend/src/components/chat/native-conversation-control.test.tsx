import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { LocalTarget } from "@/lib/desktop/commands";
import { NativeConversationControl } from "./native-conversation-control";

const base: LocalTarget = { folder: "/work", mode: "full_access" };
const runtime: NonNullable<LocalTarget["conversation_runtime"]> = {
  harness: "codex",
  session_epoch: "original",
  access: "read_only",
};
const configured: LocalTarget = { ...base, conversation_runtime: runtime };

describe("native primary conversation choice", () => {
  it("keeps an ineligible deployment unavailable without inspecting account credentials", () => {
    render(<NativeConversationControl codexEnabled={false} target={base} onChange={vi.fn()} />);
    expect(screen.getByRole("option", { name: "Codex · this computer" })).toBeDisabled();
    expect(screen.getByText(/Your operator must enable/)).toBeVisible();
  });
  it("requires full local access before offering a primary runtime", () => {
    const { container } = render(
      <NativeConversationControl
        codexEnabled
        target={{ ...base, mode: "workspace_write" }}
        onChange={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("selects a fresh, read-only Codex primary session and can return to the model provider", () => {
    const changed = vi.fn<(target: LocalTarget) => void>();
    render(
      <NativeConversationControl
        codexEnabled
        target={{ ...base, model_service: "local-model" }}
        onChange={changed}
      />,
    );
    fireEvent.change(screen.getByRole("combobox", { name: "Conversation runtime" }), {
      target: { value: "codex" },
    });
    const target = changed.mock.calls[0]?.[0];
    expect(target?.folder).toBe("/work");
    expect(target?.model_service).toBeNull();
    expect(target?.conversation_runtime).toMatchObject({ harness: "codex", access: "read_only" });
    expect(target?.conversation_runtime?.session_epoch).toMatch(/^[a-f0-9-]{36}$/);
    fireEvent.change(screen.getByRole("combobox", { name: "Conversation runtime" }), {
      target: { value: "agent" },
    });
    expect(changed.mock.lastCall?.[0].conversation_runtime).toBeNull();
  });

  it("changes native model and tool policy only under a new explicit session epoch", () => {
    const changed = vi.fn<(target: LocalTarget) => void>();
    render(<NativeConversationControl codexEnabled target={configured} onChange={changed} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Runtime tool access" }), {
      target: { value: "edit" },
    });
    expect(changed.mock.lastCall?.[0].conversation_runtime?.access).toBe("edit");
    expect(changed.mock.lastCall?.[0].conversation_runtime?.session_epoch).not.toBe("original");
    fireEvent.change(screen.getByRole("combobox", { name: "Runtime tool access" }), {
      target: { value: "invalid" },
    });
    expect(changed).toHaveBeenCalledTimes(1);
    const model = screen.getByRole("textbox", { name: "Native model ID (optional)" });
    fireEvent.change(model, { target: { value: "native-id" } });
    expect(changed.mock.lastCall?.[0].conversation_runtime?.model_id).toBe("native-id");
  });

  it("resets native context without submitting the chat or changing its folder", () => {
    const changed = vi.fn<(target: LocalTarget) => void>();
    const submit = vi.fn((event: { preventDefault: () => void }) => event.preventDefault());
    render(
      <form onSubmit={submit}>
        <NativeConversationControl
          codexEnabled
          target={{ ...configured, conversation_runtime: { ...runtime, model_id: "previous-id" } }}
          onChange={changed}
        />
      </form>,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Native model ID (optional)" }), {
      target: { value: "" },
    });
    expect(changed.mock.lastCall?.[0].conversation_runtime?.model_id).toBeNull();
    const reset = screen.getByRole("button", { name: "Reset native session" });
    expect(reset).toHaveAttribute("type", "button");
    fireEvent.click(reset);
    expect(submit).not.toHaveBeenCalled();
    expect(changed.mock.lastCall?.[0]).toMatchObject({
      folder: "/work",
      conversation_runtime: { model_id: "previous-id" },
    });
    expect(changed.mock.lastCall?.[0].conversation_runtime?.session_epoch).not.toBe("original");
  });
});
