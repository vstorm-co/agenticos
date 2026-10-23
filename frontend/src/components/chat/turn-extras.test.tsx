import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TurnExtras } from "./turn-extras";
import { ApiError } from "@/lib/api-error";
import type { ChatMessage, ToolCall } from "@/types/chat";

/**
 * What a turn's calls leave under its answer (#2301). The card is the part with
 * consequences: an editor switches the capability on, anybody else asks the
 * owner, and neither is offered twice.
 */

const state = vi.hoisted(() => ({ editor: true }));
const push = vi.hoisted(() => vi.fn());
const enable = vi.hoisted(() => vi.fn());
const askOwner = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());

vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => state.editor }) }));
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/capability-requests-api", () => ({
  enableCapability: enable,
  askForCapability: askOwner,
}));
vi.mock("sonner", () => ({ toast: { error: toastError } }));

const CARD = {
  agent_id: "a-1",
  capability_id: "web_search",
  name: "Web search",
  reason: "for the news",
};

function call(name: string, overrides: Partial<ToolCall> = {}): ToolCall {
  return { id: `${name}-1`, name, args: {}, status: "completed", ...overrides };
}

function answer(toolCalls: ToolCall[], overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "m-1",
    role: "assistant",
    content: "Done",
    timestamp: new Date(),
    toolCalls,
    ...overrides,
  };
}

const steps = call("suggest_next_steps", {
  result: JSON.stringify({ steps: ["Draft the email"] }),
});
const request = call("request_capability", { result: JSON.stringify(CARD) });

beforeEach(() => {
  state.editor = true;
  push.mockReset();
  enable.mockReset();
  askOwner.mockReset();
  toastError.mockReset();
});

describe("TurnExtras", () => {
  it("draws nothing under a person's message, a streaming answer, or an answer with no extras", () => {
    const { container, rerender } = render(
      <TurnExtras message={answer([steps], { role: "user" })} />,
    );
    expect(container).toBeEmptyDOMElement();

    rerender(<TurnExtras message={answer([request], { isStreaming: true })} />);
    expect(container).toBeEmptyDOMElement();

    rerender(<TurnExtras message={answer([call("web_search")])} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("leaves the next steps to the composer, not the answer (#2301)", () => {
    const { container } = render(<TurnExtras message={answer([steps])} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("says what the agent remembered and forgot, with the way to manage it", async () => {
    render(
      <TurnExtras
        message={answer([
          call("write_memory", {
            id: "w",
            args: { name: "role.md", description: "You work in sales" },
          }),
          call("delete_memory", { id: "d", args: { name: "old.md" } }),
        ])}
      />,
    );

    expect(screen.getByText("Remembered: You work in sales")).toBeVisible();
    expect(screen.getByText("Forgot: old.md")).toBeVisible();
    await userEvent.click(screen.getAllByRole("button", { name: "Manage" })[0]!);
    expect(push).toHaveBeenCalledWith("/settings/memory");
  });

  it("lets an editor switch the capability on, and says it is live when it was published", async () => {
    enable.mockResolvedValue({ published: true });
    render(<TurnExtras message={answer([request])} agentName="Helper" />);

    expect(screen.getByText("Helper needs Web search for this")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Switch on Web search" }));

    expect(enable).toHaveBeenCalledWith("a-1", "web_search");
    expect(await screen.findByRole("status")).toHaveTextContent("Web search is on.");
    expect(screen.queryByRole("button", { name: "Switch on Web search" })).not.toBeInTheDocument();
  });

  it("says the capability waits in the draft when the agent had unpublished changes", async () => {
    enable.mockResolvedValue({ published: false });
    render(<TurnExtras message={answer([request])} />);

    expect(screen.getByText("This agent needs Web search for this")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Switch on Web search" }));

    expect(await screen.findByRole("status")).toHaveTextContent("publish it in the Builder");
  });

  it("offers somebody who cannot edit the agent the owner instead, with the agent's reason", async () => {
    state.editor = false;
    enable.mockRejectedValue(new ApiError(403, "Not allowed"));
    askOwner.mockResolvedValue(undefined);
    render(<TurnExtras message={answer([request])} />);

    await userEvent.click(screen.getByRole("button", { name: "Ask the agent's owner" }));

    expect(askOwner).toHaveBeenCalledWith("a-1", "web_search", "for the news");
    expect(await screen.findByRole("status")).toHaveTextContent("The owner has been asked.");
  });

  it("asks the owner when an organization-wide editor cannot edit this agent", async () => {
    // Codex on #2324: a Member holds `agents:edit` for their own agents only.
    enable.mockRejectedValue(new ApiError(403, "Not allowed"));
    askOwner.mockResolvedValue(undefined);
    render(<TurnExtras message={answer([request])} />);

    await userEvent.click(screen.getByRole("button", { name: "Switch on Web search" }));

    expect(askOwner).toHaveBeenCalledWith("a-1", "web_search", "for the news");
    expect(await screen.findByRole("status")).toHaveTextContent("The owner has been asked.");
  });

  it("switches it on for somebody an edit grant on this agent lets in", async () => {
    state.editor = false;
    enable.mockResolvedValue({ published: true });
    render(<TurnExtras message={answer([request])} />);

    await userEvent.click(screen.getByRole("button", { name: "Ask the agent's owner" }));

    expect(askOwner).not.toHaveBeenCalled();
    expect(await screen.findByRole("status")).toHaveTextContent("Web search is on.");
  });

  it("puts the button back and says why when the switch is refused", async () => {
    enable.mockRejectedValue(new Error("nope"));
    render(<TurnExtras message={answer([request])} />);

    await userEvent.click(screen.getByRole("button", { name: "Switch on Web search" }));

    expect(toastError).toHaveBeenCalled();
    expect(await screen.findByRole("button", { name: "Switch on Web search" })).toBeEnabled();
  });
});
