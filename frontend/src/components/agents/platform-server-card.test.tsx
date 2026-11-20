import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui";
import type { PlatformMcpServerRef } from "@/types/agents";
import type { PlatformMcpTool } from "@/types/mcp";
import { NEW_PLATFORM_BINDING, PlatformServerCard } from "./platform-server-card";

const DEFAULT_TOOLS = () => ({
  tools: [
    {
      name: "list_agents",
      description: "The agents this caller can see.",
      group: "agents",
      writes: false,
    },
    { name: "run_agent", description: "Run an agent.", group: "agents", writes: true },
  ] as PlatformMcpTool[],
  isLoading: false,
  error: null as Error | null,
});
const tools = vi.fn(DEFAULT_TOOLS);
vi.mock("@/hooks", () => ({ usePlatformMcpTools: () => tools() }));
vi.mock("@/components/branding/branding-provider", () => ({
  useBranding: () => ({ appName: "AgenticOS", logoUrl: null }),
}));

/** The card as the Builder holds it: the spec's platform binding, changed in place. */
function Harness({
  initial,
  onChange,
  disabled,
}: {
  initial: PlatformMcpServerRef | null;
  onChange: (next: PlatformMcpServerRef | null) => void;
  disabled?: boolean;
}) {
  const [binding, setBinding] = useState(initial);
  return (
    <TooltipProvider>
      <PlatformServerCard
        binding={binding}
        disabled={disabled}
        onChange={(next) => {
          setBinding(next);
          onChange(next);
        }}
      />
    </TooltipProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  tools.mockImplementation(DEFAULT_TOOLS);
});

describe("the AgenticOS server in the Builder", () => {
  it("is switched on with writes held for approval, and says it acts as whoever asks", async () => {
    const onChange = vi.fn();
    render(<Harness initial={null} onChange={onChange} />);
    expect(screen.getByText("Acts as whoever asks")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("switch", { name: "Use AgenticOS in this agent" }));

    expect(onChange).toHaveBeenLastCalledWith(NEW_PLATFORM_BINDING);
    expect(screen.getByRole("dialog")).toHaveTextContent("exactly their permissions");
    expect(screen.getByRole("heading", { name: "Agents" })).toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: "Changes something" })).toHaveLength(1);
  });

  it("cannot ask before the person's own language, the write no policy holds (#2301)", async () => {
    tools.mockReturnValue({
      tools: [
        { name: "publish_agent", description: "Publish.", group: "agents", writes: true },
        {
          name: "set_my_language",
          description: "Switch the language.",
          group: "account",
          writes: true,
          ungated: true,
        },
      ],
      isLoading: false,
      error: null,
    });
    render(<Harness initial={NEW_PLATFORM_BINDING} onChange={vi.fn()} />);
    await userEvent.click(screen.getByText("Asks before any change"));

    const language = screen.getByRole("button", { name: "Ask first before set_my_language" });
    expect(language).toBeDisabled();
    expect(language).toHaveAttribute("title", "your own setting, never asks");
    expect(screen.getByRole("button", { name: "Ask first before publish_agent" })).toBeEnabled();
  });

  it("narrows the tools, and every tool chosen again is today's tools only", async () => {
    const onChange = vi.fn();
    render(<Harness initial={NEW_PLATFORM_BINDING} onChange={onChange} />);
    await userEvent.click(screen.getByText("Asks before any change"));

    await userEvent.click(screen.getByRole("checkbox", { name: "run_agent" }));
    expect(onChange).toHaveBeenLastCalledWith({
      ...NEW_PLATFORM_BINDING,
      allowed_tools: ["list_agents"],
    });

    await userEvent.click(screen.getByRole("checkbox", { name: "run_agent" }));
    expect(onChange).toHaveBeenLastCalledWith({
      ...NEW_PLATFORM_BINDING,
      allowed_tools: ["list_agents", "run_agent"],
    });
  });

  it("says when a tool runs freely, and is removed from the dialog", async () => {
    const onChange = vi.fn();
    render(<Harness initial={NEW_PLATFORM_BINDING} onChange={onChange} />);
    await userEvent.click(screen.getByText("Asks before any change"));

    await userEvent.click(screen.getByRole("button", { name: "Ask first before run_agent" }));
    expect(onChange).toHaveBeenLastCalledWith({
      ...NEW_PLATFORM_BINDING,
      tool_approval: { run_agent: "never" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.getByText("Some tools run without asking")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Some tools run without asking"));
    await userEvent.click(screen.getByRole("button", { name: "Remove from this agent" }));
    expect(onChange).toHaveBeenLastCalledWith(null);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("does not count a tool the agent cannot call as running freely", () => {
    const binding = {
      ...NEW_PLATFORM_BINDING,
      allowed_tools: ["list_agents"],
      tool_approval: { run_agent: "never" as const },
    };
    render(<Harness initial={binding} onChange={vi.fn()} />);
    expect(screen.getByText("Asks before any change")).toBeInTheDocument();
  });

  it("says a binding that asks before every call does", () => {
    render(<Harness initial={{ ...NEW_PLATFORM_BINDING, approval: "all" }} onChange={vi.fn()} />);
    expect(screen.getByText("Asks before every call")).toBeInTheDocument();
  });

  it("offers to use it from the dialog when it is off, and holds while the tools load", async () => {
    tools.mockReturnValueOnce({ tools: [], isLoading: true, error: null });
    const onChange = vi.fn();
    render(<Harness initial={null} onChange={onChange} />);
    await userEvent.click(screen.getByText("Acts as whoever asks"));

    await userEvent.click(screen.getByRole("button", { name: "Use it in this agent" }));
    expect(onChange).toHaveBeenLastCalledWith(NEW_PLATFORM_BINDING);
  });

  it("says the tools could not be read rather than showing a server with none", async () => {
    const listed = tools.getMockImplementation()!;
    tools.mockReturnValue({ tools: [], isLoading: false, error: new Error("Service unavailable") });
    render(<Harness initial={NEW_PLATFORM_BINDING} onChange={vi.fn()} />);
    await userEvent.click(screen.getByText("Asks before any change"));

    expect(screen.getByRole("dialog")).toHaveTextContent("Service unavailable");
    expect(screen.queryByRole("checkbox")).toBeNull();
    tools.mockImplementation(listed);
  });

  it("switches off from the card", async () => {
    const onChange = vi.fn();
    render(<Harness initial={NEW_PLATFORM_BINDING} onChange={onChange} />);
    await userEvent.click(screen.getByRole("switch", { name: "Use AgenticOS in this agent" }));
    expect(onChange).toHaveBeenLastCalledWith(null);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens its settings from anywhere on the card", async () => {
    render(<Harness initial={null} onChange={vi.fn()} />);
    await userEvent.click(screen.getByText("Built in"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("opens nothing for a reader who cannot edit the agent", async () => {
    render(<Harness initial={NEW_PLATFORM_BINDING} onChange={vi.fn()} disabled />);
    await userEvent.click(screen.getByText("Asks before any change"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
