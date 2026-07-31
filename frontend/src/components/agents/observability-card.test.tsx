import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ObservabilityCard } from "./observability-card";
import type { ObservabilitySpec } from "@/types/agents";

interface Secret {
  id: string;
  name: string;
  hint: string;
  purpose: string | null;
  kind: string;
}

const state = { secrets: [] as Secret[] };

vi.mock("@/hooks", () => ({ useSecrets: () => state }));

function secret(overrides: Partial<Secret> = {}): Secret {
  return {
    id: "s-logfire",
    name: "Client Logfire",
    hint: "3123",
    purpose: "logfire",
    kind: "api_key",
    ...overrides,
  };
}

function mount(value: ObservabilitySpec | null = null) {
  const onChange = vi.fn();
  render(<ObservabilityCard value={value} onChange={onChange} agentName="Support Copilot" />);
  return { onChange };
}

beforeEach(() => {
  state.secrets = [secret()];
});

describe("the tracing card", () => {
  it("defaults to the deployment's own project", () => {
    // The normal state: Logfire is configured once and every run lands there.
    mount();

    expect(screen.getByLabelText("Write token")).toHaveTextContent("The deployment's project");
  });

  it("offers only Logfire tokens, not every key in the vault", () => {
    // Each provider key would be a plausible-looking wrong answer in this picker,
    // and picking one produces an agent whose traces go nowhere.
    state.secrets = [secret(), secret({ id: "s-openai", name: "OpenAI", purpose: "openai" })];
    mount();

    return userEvent.click(screen.getByLabelText("Write token")).then(() => {
      expect(screen.getByRole("option", { name: /Client Logfire/ })).toBeInTheDocument();
      expect(screen.queryByRole("option", { name: /OpenAI/ })).toBeNull();
    });
  });

  it("says where to put a token when the vault has none", () => {
    // Rather than an empty picker, which reads as a broken control.
    state.secrets = [];
    mount();

    expect(screen.getByText(/No Logfire tokens stored yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Vault" })).toBeInTheDocument();
  });

  it("says the spec keeps a reference once there is something to pick", () => {
    mount();

    expect(screen.getByText(/never the token/)).toBeInTheDocument();
  });

  it("locks the service name and environment until a token is chosen", () => {
    // Three stored fields with nowhere to send are three fields that do nothing,
    // and on the next edit they read as though tracing were configured.
    mount();

    expect(screen.getByLabelText("Service name")).toBeDisabled();
    expect(screen.getByLabelText("Environment")).toBeDisabled();
  });

  it("unlocks them once a token is chosen", () => {
    mount({ token_secret_id: "s-logfire" });

    expect(screen.getByLabelText("Service name")).toBeEnabled();
    expect(screen.getByLabelText("Environment")).toBeEnabled();
  });

  it("records the token that was picked", async () => {
    const { onChange } = mount();

    await userEvent.click(screen.getByLabelText("Write token"));
    await userEvent.click(screen.getByRole("option", { name: /Client Logfire/ }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ token_secret_id: "s-logfire" }),
    );
  });

  it("clears the whole block when the token is cleared", async () => {
    // Not `{token_secret_id: null, service_name: "..."}` - the block goes, because
    // a service name with nowhere to send is a lie about the next edit.
    const { onChange } = mount({
      token_secret_id: "s-logfire",
      service_name: "client-support",
      environment: "production",
    });

    await userEvent.click(screen.getByLabelText("Write token"));
    await userEvent.click(screen.getByRole("option", { name: "The deployment's project" }));

    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("keeps the token when only the service name changes", async () => {
    const { onChange } = mount({ token_secret_id: "s-logfire" });

    await userEvent.type(screen.getByLabelText("Service name"), "x");

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ token_secret_id: "s-logfire", service_name: "x" }),
    );
  });

  it("stores an emptied field as null rather than as an empty string", async () => {
    // `""` is a value the backend would store and send to Logfire as a service
    // name; absence is what "not set" means.
    const { onChange } = mount({ token_secret_id: "s-logfire", environment: "p" });

    await userEvent.clear(screen.getByLabelText("Environment"));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ token_secret_id: "s-logfire", environment: null }),
    );
  });

  it("suggests the agent's own name for the service", () => {
    mount({ token_secret_id: "s-logfire" });

    expect(screen.getByLabelText("Service name")).toHaveAttribute("placeholder", "Support Copilot");
  });

  it("falls back to the deployment's project when the stored token is gone", () => {
    // A secret deleted from the vault leaves a reference behind. Radix renders
    // nothing for a value no item matches, so the control would otherwise be
    // blank and silent.
    state.secrets = [];
    mount({ token_secret_id: "s-deleted" });

    expect(screen.getByLabelText("Write token")).toHaveTextContent("The deployment's project");
  });

  it("cannot be changed by somebody without edit rights", () => {
    const onChange = vi.fn();
    render(
      <ObservabilityCard
        value={{ token_secret_id: "s-logfire" }}
        onChange={onChange}
        agentName="Support Copilot"
        disabled
      />,
    );

    expect(screen.getByLabelText("Write token")).toBeDisabled();
    expect(screen.getByLabelText("Service name")).toBeDisabled();
    expect(screen.getByLabelText("Environment")).toBeDisabled();
  });
});
