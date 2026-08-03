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

const state = {
  secrets: [] as Secret[],
  // The inline form writes through `useSecrets().create`, and what this card owes
  // it is the callback: a key added there is the key selected here.
  create: { mutate: vi.fn(), isPending: false },
};

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
  vi.clearAllMocks();
  state.secrets = [secret()];
  state.create = { mutate: vi.fn(), isPending: false };
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

  it("lets a token be added here when the vault has none", () => {
    // Rather than an empty picker and a sentence pointing somewhere else: the
    // answer to "no tokens stored yet" is a form, and a picker with nothing in it
    // and nowhere to go is a dead end.
    state.secrets = [];
    mount();

    expect(screen.getByRole("button", { name: /Add a key/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open the Vault/ })).toBeInTheDocument();
  });

  it("selects a token added inline, so nobody has to re-pick it", async () => {
    // The whole point of the inline form: a key added there is the key this agent
    // traces with, without a round trip through the Vault and back.
    state.secrets = [];
    // The real mutation calls `onSuccess` with the stored secret; the stub has to
    // as well, or the callback under test never runs.
    state.create.mutate = vi.fn((_input, options) => options?.onSuccess?.({ id: "s-new" }));
    const { onChange } = mount();

    await userEvent.click(screen.getByRole("button", { name: /Add a key/ }));
    await userEvent.type(screen.getByLabelText("Key"), "pylf_v1_x");
    await userEvent.click(screen.getByRole("button", { name: "Save key" }));

    expect(state.create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ purpose: "logfire" }),
      expect.anything(),
    );
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ token_secret_id: "s-new" }));
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

  it("stores an emptied service name as null too", async () => {
    // Two fields, one rule. `""` here would be sent to Logfire as the service
    // name and every trace would arrive under a blank.
    const { onChange } = mount({ token_secret_id: "s-logfire", service_name: "support" });

    await userEvent.clear(screen.getByLabelText("Service name"));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ token_secret_id: "s-logfire", service_name: null }),
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
