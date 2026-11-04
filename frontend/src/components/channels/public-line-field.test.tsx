import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PublicLineField } from "./public-line-field";
import type { PublicLine } from "@/types/channels";

let line: PublicLine | undefined;
vi.mock("@/hooks/use-channel-bots", () => ({
  usePublicLine: () => ({ data: line, isLoading: line === undefined }),
}));

function warning(overrides: Partial<PublicLine> = {}): PublicLine {
  return {
    answers_unlinked: false,
    agent_name: "Front desk",
    agent_version: 3,
    agent_monthly_usd: "5.00",
    organization_monthly_usd: null,
    can_turn_on: true,
    accept_customer_files: false,
    voice: "refused_no_org_cap",
    rate_limit_rpm: 10,
    approval_expiry_hours: 72,
    recording_max_mb: 2,
    file_max_mb: 5,
    reaches: [
      { kind: "knowledge", names: ["Handbook", "Returns"], detail: null },
      { kind: "tables", names: ["Support"], detail: "Support: read, update; may create tables" },
      { kind: "web", names: ["web_fetch"], detail: "not counted in the spending limit" },
      { kind: "code", names: ["code_execution"], detail: "not counted in the spending limit" },
      { kind: "context", names: ["Tone"], detail: null },
      { kind: "skills", names: ["Refunds"], detail: null },
      { kind: "generation", names: ["image_generation"], detail: null },
      { kind: "delegates", names: ["Billing"], detail: null },
      { kind: "mcp", names: ["CRM"], detail: null },
      { kind: "files", names: [], detail: null },
    ],
    refused: [
      "memory",
      "conversation_search",
      "artifacts",
      "workflows",
      "background_tasks",
      "platform_mcp",
    ],
    ...overrides,
  };
}

function show(props: Partial<React.ComponentProps<typeof PublicLineField>> = {}) {
  const onAnswers = vi.fn();
  const onFiles = vi.fn();
  render(
    <PublicLineField
      botId="b1"
      answers={false}
      files={false}
      onAnswers={onAnswers}
      onFiles={onFiles}
      {...props}
    />,
  );
  return { onAnswers, onFiles };
}

describe("the switch for answering people with no account", () => {
  it("shows what a customer can reach, with names", () => {
    line = warning();
    show();

    expect(screen.getByText(/Handbook and Returns/)).toBeInTheDocument();
    expect(screen.getByText(/Support: read, update; may create tables/)).toBeInTheDocument();
    expect(screen.getByText(/Refunds/)).toBeInTheDocument();
    expect(screen.getByText(/Billing/)).toBeInTheDocument();
    expect(screen.getByText(/CRM/)).toBeInTheDocument();
    expect(screen.getByText(/Tone/)).toBeInTheDocument();
    expect(screen.getByText(/image_generation/)).toBeInTheDocument();
    expect(screen.getAllByText(/not counted in the spending limit/)).toHaveLength(2);
  });

  it("states the ceilings, the rate, the expiry, the file and voice caps and what is refused", () => {
    line = warning({ organization_monthly_usd: "100.00", voice: "on" });
    show();

    expect(screen.getByText(/agent monthly budget.*\$5\.00/i)).toBeInTheDocument();
    expect(screen.getByText(/organization monthly cap.*\$100\.00/i)).toBeInTheDocument();
    expect(screen.getByText(/10 messages a minute/i)).toBeInTheDocument();
    expect(screen.getByText(/72 hours/i)).toBeInTheDocument();
    expect(screen.getByText(/files up to 5 MB/i)).toBeInTheDocument();
    expect(screen.getByText(/voice notes up to 2 MB/i)).toBeInTheDocument();
    expect(screen.getByText(/never reach.*memory/i)).toBeInTheDocument();
  });

  it("says voice notes need an organization cap while there is none", () => {
    line = warning({ voice: "refused_no_org_cap" });
    show();

    expect(screen.getByText(/voice notes need an organization cap/i)).toBeInTheDocument();
  });

  it("says nothing about voice notes the bot does not transcribe", () => {
    line = warning({ voice: "off" });
    show();

    expect(screen.queryByText(/voice notes/i)).not.toBeInTheDocument();
  });

  it("turns the switch on", () => {
    line = warning();
    const { onAnswers } = show();

    fireEvent.click(screen.getByRole("switch", { name: /answer people with no account/i }));

    expect(onAnswers).toHaveBeenCalledWith(true);
  });

  it("disables the switch with no spending limit, and says why", () => {
    line = warning({ can_turn_on: false, agent_monthly_usd: null });
    show();

    expect(screen.getByRole("switch", { name: /answer people with no account/i })).toBeDisabled();
    expect(screen.getByText(/needs a spending limit/i)).toBeInTheDocument();
  });

  it("lets a line already on be switched off whatever the limit", () => {
    line = warning({ can_turn_on: false, answers_unlinked: true });
    show({ answers: true });

    expect(screen.getByRole("switch", { name: /answer people with no account/i })).toBeEnabled();
  });

  it("holds the files toggle until the line is on, then toggles it", () => {
    line = warning();
    const closed = show();
    expect(screen.getByRole("switch", { name: /accept files from customers/i })).toBeDisabled();
    expect(closed.onFiles).not.toHaveBeenCalled();
  });

  it("toggles the files setting on an open line", () => {
    line = warning();
    const { onFiles } = show({ answers: true });

    fireEvent.click(screen.getByRole("switch", { name: /accept files from customers/i }));

    expect(onFiles).toHaveBeenCalledWith(true);
  });

  it("shows the server's refusal under the switch", () => {
    line = warning();
    show({ error: "The agent has no spending limit" });

    expect(screen.getByText("The agent has no spending limit")).toBeInTheDocument();
  });

  it("shows nothing but the switch while the warning loads", () => {
    line = undefined;
    show();

    expect(screen.getByRole("switch", { name: /answer people with no account/i })).toBeDisabled();
    expect(screen.queryByText(/never reach/i)).not.toBeInTheDocument();
  });

  it("says a bot serving no agent reaches nothing yet", () => {
    line = warning({ agent_name: null, agent_version: null, reaches: [] });
    show();

    expect(screen.getByText(/serves no agent yet/i)).toBeInTheDocument();
  });
});
