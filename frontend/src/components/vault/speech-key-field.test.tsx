import { render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SpeechKeyField, speechKeysFor, useSpeechKeyCheck } from "./speech-key-field";
import type { Secret } from "@/types/secrets";

const state = vi.hoisted(() => ({
  secrets: [] as Secret[],
  isLoading: false,
  listError: null as Error | null,
}));

vi.mock("@/hooks", () => ({
  useSecrets: () => ({
    secrets: state.secrets,
    isLoading: state.isLoading,
    listError: state.listError,
  }),
}));
vi.mock("@/components/vault/inline-secret", () => ({
  InlineSecret: ({
    purpose,
    suggestedName,
    onCreated,
  }: {
    purpose: string;
    suggestedName: string;
    onCreated: (id: string) => void;
  }) => (
    <button type="button" onClick={() => onCreated(`new-${purpose}`)}>
      {`add ${suggestedName}`}
    </button>
  ),
}));

function secret(id: string, overrides: Partial<Secret> = {}): Secret {
  return {
    id,
    name: id,
    description: null,
    kind: "api_key",
    hint: "abcd",
    purpose: "openai",
    visibility: "org",
    ...overrides,
  } as Secret;
}

function mount(props: Partial<Parameters<typeof SpeechKeyField>[0]> = {}) {
  const onChange = vi.fn();
  render(
    <SpeechKeyField
      id="key"
      provider="openai"
      providerName="OpenAI"
      value={null}
      orgVisibleOnly
      onChange={onChange}
      {...props}
    />,
  );
  return { onChange };
}

beforeEach(() => {
  state.secrets = [];
  state.isLoading = false;
  state.listError = null;
});

describe("speechKeysFor", () => {
  const keys = [
    secret("team-openai"),
    secret("mine-openai", { visibility: "private" }),
    secret("team-groq", { purpose: "groq" }),
    secret("aws", { kind: "aws_credentials" }),
  ];

  it("offers only organization-wide API keys for the provider where it must", () => {
    expect(speechKeysFor(keys, "openai", true).map((key) => key.id)).toEqual(["team-openai"]);
  });

  it("offers any visible API key for the provider to an agent", () => {
    expect(speechKeysFor(keys, "openai", false).map((key) => key.id)).toEqual([
      "team-openai",
      "mine-openai",
    ]);
  });
});

describe("speechKeysFor, for another kind of key", () => {
  it("offers only keys of that kind, and API keys by default", () => {
    const keys = [
      secret("azure-plain", { purpose: "azure" }),
      secret("azure-deployment", { purpose: "azure", kind: "azure_openai" }),
    ];
    expect(speechKeysFor(keys, "azure", false, "azure_openai").map((key) => key.id)).toEqual([
      "azure-deployment",
    ]);
    expect(speechKeysFor(keys, "azure", false).map((key) => key.id)).toEqual(["azure-plain"]);
  });
});

describe("useSpeechKeyCheck", () => {
  it("says which providers have a key at this level", () => {
    state.secrets = [secret("mine-openai", { visibility: "private" })];
    const { result } = renderHook(() => useSpeechKeyCheck(true));
    expect(result.current("openai")).toBe(false);
    const agent = renderHook(() => useSpeechKeyCheck(false));
    expect(agent.result.current("openai")).toBe(true);
  });

  it("marks nothing while the vault is unread or cannot be read", () => {
    state.isLoading = true;
    expect(renderHook(() => useSpeechKeyCheck(true)).result.current("groq")).toBe(true);
    state.isLoading = false;
    state.listError = new Error("403");
    expect(renderHook(() => useSpeechKeyCheck(true)).result.current("groq")).toBe(true);
  });
});

describe("the speech-to-text key field", () => {
  it("stores the only key that fits, explicitly", () => {
    state.secrets = [secret("team-openai"), secret("mine", { visibility: "private" })];
    const { onChange } = mount();
    expect(onChange).toHaveBeenCalledWith("team-openai");
  });

  it("does not choose for anyone when two keys fit", async () => {
    state.secrets = [secret("a"), secret("b")];
    const { onChange } = mount();
    expect(onChange).not.toHaveBeenCalled();

    await userEvent.click(screen.getByLabelText("Key"));
    await userEvent.click(screen.getByRole("option", { name: "b (…abcd)" }));
    expect(onChange).toHaveBeenCalledWith("b");
  });

  it("does not preselect while disabled", () => {
    state.secrets = [secret("a")];
    const { onChange } = mount({ disabled: true });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("says a stored key that is gone needs replacing, and does not replace it itself", () => {
    state.secrets = [secret("a")];
    const { onChange } = mount({ value: "deleted" });
    expect(screen.getByRole("note")).toHaveTextContent(/Choose a key/);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("shows the chosen key", () => {
    state.secrets = [secret("a"), secret("b")];
    mount({ value: "b" });
    expect(screen.getByLabelText("Key")).toHaveTextContent("b (…abcd)");
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("with no organization-wide key, says so and offers to add one", async () => {
    state.secrets = [secret("mine", { visibility: "private" })];
    const { onChange } = mount();
    expect(screen.getByText(/mine.*shared with the whole organization/)).toBeVisible();
    expect(
      screen.queryByText(/No organization-wide OpenAI keys in the vault yet/),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Key"));
    expect(screen.queryByRole("option", { name: /mine/ })).not.toBeInTheDocument();
    await userEvent.keyboard("{Escape}");

    await userEvent.click(screen.getByRole("button", { name: "add OpenAI speech to text" }));
    expect(onChange).toHaveBeenCalledWith("new-openai");
  });

  it("explains why an existing ChatGPT sign-in cannot pay for transcription", () => {
    state.secrets = [secret("My ChatGPT", { kind: "openai_codex", purpose: "openai_codex" })];
    const { onChange } = mount();
    expect(screen.getByText(/My ChatGPT.*ChatGPT sign-in.*OpenAI API key/)).toBeVisible();
    expect(
      screen.queryByText(/No organization-wide OpenAI keys in the vault yet/),
    ).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("does not report incompatible sign-ins for other providers or while loading", () => {
    state.secrets = [secret("My ChatGPT", { kind: "openai_codex", purpose: "openai_codex" })];
    const view = render(
      <SpeechKeyField
        id="key"
        provider="groq"
        providerName="Groq"
        value={null}
        orgVisibleOnly
        onChange={vi.fn()}
      />,
    );
    expect(screen.queryByText(/ChatGPT sign-in/)).not.toBeInTheDocument();
    state.isLoading = true;
    view.rerender(
      <SpeechKeyField
        id="key"
        provider="openai"
        providerName="OpenAI"
        value={null}
        orgVisibleOnly
        onChange={vi.fn()}
      />,
    );
    expect(screen.queryByText(/ChatGPT sign-in/)).not.toBeInTheDocument();
  });

  it("for an agent, says there is no key at all", () => {
    mount({ orgVisibleOnly: false });
    expect(screen.getByText("No OpenAI keys in the vault yet. Add one below.")).toBeInTheDocument();
    expect(screen.getByText(/lends it to everyone who can run this agent/)).toBeInTheDocument();
  });

  it("says nothing about missing keys while the vault is unread", () => {
    state.isLoading = true;
    mount({ value: "unknown" });
    expect(screen.queryByText(/keys in the vault yet/)).not.toBeInTheDocument();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("says why no key can be chosen when the vault cannot be listed", () => {
    state.listError = new Error("403");
    mount({ error: "Choose a key for openai" });
    expect(screen.getByText(/You cannot list the vault's keys/)).toBeInTheDocument();
    expect(screen.getByText("Choose a key for openai")).toBeInTheDocument();
  });

  it("shows the server's refusal under the field", () => {
    state.secrets = [secret("a"), secret("b")];
    mount({ error: "That key is for groq" });
    expect(screen.getByText("That key is for groq")).toBeInTheDocument();
  });

  it("names a key added from here as its caller asks", () => {
    mount({ orgVisibleOnly: false, suggestedName: "OpenAI voice calls" });
    expect(screen.getByRole("button", { name: "add OpenAI voice calls" })).toBeInTheDocument();
  });

  it("sends somebody to the vault for a key the inline form cannot take", () => {
    state.secrets = [secret("plain", { purpose: "azure" })];
    render(
      <SpeechKeyField
        id="key"
        provider="azure"
        providerName="Azure OpenAI"
        value={null}
        orgVisibleOnly={false}
        kind="azure_openai"
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/No Azure OpenAI keys in the vault yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^add / })).toBeNull();
    expect(screen.getByRole("link", { name: /vault/i })).toHaveAttribute("target", "_blank");
    expect(screen.getByLabelText("Key").closest("[data-kind]")).toHaveAttribute(
      "data-kind",
      "azure_openai",
    );
  });
});
