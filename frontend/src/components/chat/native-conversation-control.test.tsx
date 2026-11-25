import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ExternalAgent, LocalTarget } from "@/lib/desktop/commands";
import {
  conversationRegistrations,
  NativeConversationControl,
} from "./native-conversation-control";

const options = vi.hoisted(() => ({
  current: {} as Record<string, unknown>,
  requested: [] as (string | null)[],
}));
const vault = vi.hoisted(() => ({
  current: { secrets: [] as Record<string, unknown>[], listError: null as unknown },
}));
vi.mock("@/hooks/use-secrets", () => ({ useSecrets: () => vault.current }));
vi.mock("@/hooks/use-desktop", () => ({
  useExternalAgentOptions: (id: string | null) => {
    options.requested.push(id);
    return options.current;
  },
}));

const agy = (id: string, name: string): ExternalAgent => ({
  provider: "antigravity",
  id,
  name,
  program: "/usr/local/bin/agy",
  args: ["acp"],
  revision: "r1",
});
const signedIn = {
  isSuccess: true,
  isPending: false,
  isError: false,
  data: {
    current_model: "gemini-3-pro",
    current_effort: null,
    models: [
      { value: "gemini-3-pro", name: "Gemini 3 Pro", efforts: [] },
      { value: "gemini-3-flash", name: "Gemini 3 Flash", efforts: [] },
    ],
  },
  refetch: vi.fn(),
};

const base: LocalTarget = { folder: "/work", mode: "full_access" };
const runtime: NonNullable<LocalTarget["conversation_runtime"]> = {
  harness: "codex",
  session_epoch: "original",
  access: "read_only",
};
const configured: LocalTarget = { ...base, conversation_runtime: runtime };

describe("native primary conversation choice", () => {
  it("keeps an ineligible deployment unavailable without inspecting account credentials", () => {
    render(
      <NativeConversationControl
        claudeEnabled
        codexEnabled={false}
        target={base}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("option", { name: "Codex · this computer" })).toBeDisabled();
    expect(screen.getByText(/Your operator must enable/)).toBeVisible();
  });
  it("requires full local access before offering a primary runtime", () => {
    const { container } = render(
      <NativeConversationControl
        claudeEnabled
        codexEnabled
        target={{ ...base, mode: "workspace_write" }}
        onChange={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("selects Claude with independent native identity", () => {
    const changed = vi.fn<(target: LocalTarget) => void>();
    render(
      <NativeConversationControl
        codexEnabled
        claudeEnabled
        target={configured}
        onChange={changed}
      />,
    );
    fireEvent.change(screen.getByRole("combobox", { name: "Conversation runtime" }), {
      target: { value: "claude_code" },
    });
    expect(changed.mock.lastCall?.[0].conversation_runtime).toMatchObject({
      harness: "claude_code",
      access: "read_only",
    });
    expect(changed.mock.lastCall?.[0].conversation_runtime?.session_epoch).not.toBe("original");
  });

  it("selects a fresh, read-only Codex primary session and can return to the model provider", () => {
    const changed = vi.fn<(target: LocalTarget) => void>();
    render(
      <NativeConversationControl
        claudeEnabled
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
    render(
      <NativeConversationControl
        claudeEnabled
        codexEnabled
        target={configured}
        onChange={changed}
      />,
    );
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
          claudeEnabled
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

  it("keeps external agents unavailable until enabled and registered", () => {
    const { rerender } = render(
      <NativeConversationControl
        claudeEnabled
        codexEnabled
        target={base}
        registrations={[agy("agy", "Antigravity")]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("option", { name: "External agent · this computer" })).toBeDisabled();
    rerender(
      <NativeConversationControl
        claudeEnabled
        codexEnabled
        externalEnabled
        target={base}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("option", { name: "External agent · this computer" })).toBeDisabled();
    expect(screen.getByText(/Register an ACP agent/)).toBeVisible();
  });

  it("selects an external agent on its first registration with its own tool access", () => {
    const changed = vi.fn<(target: LocalTarget) => void>();
    render(
      <NativeConversationControl
        claudeEnabled
        codexEnabled
        externalEnabled
        registrations={[agy("agy", "Antigravity"), agy("agy-work", "Work account")]}
        target={{ ...base, model_service: "local-model" }}
        onChange={changed}
      />,
    );
    fireEvent.change(screen.getByRole("combobox", { name: "Conversation runtime" }), {
      target: { value: "external" },
    });
    expect(changed.mock.lastCall?.[0]).toMatchObject({
      model_service: null,
      conversation_runtime: { harness: "external", access: "edit", registration_id: "agy" },
    });
  });

  it("offers the signed-in account's models and a new session for every choice", () => {
    options.current = signedIn;
    options.requested.length = 0;
    const changed = vi.fn<(target: LocalTarget) => void>();
    const chosen: LocalTarget = {
      ...base,
      conversation_runtime: {
        harness: "external",
        session_epoch: "original",
        access: "edit",
        registration_id: "agy",
      },
    };
    render(
      <NativeConversationControl
        claudeEnabled
        codexEnabled
        externalEnabled
        registrations={[agy("agy", "Antigravity"), agy("agy-work", "Work account")]}
        target={chosen}
        onChange={changed}
      />,
    );
    expect(options.requested).toContain("agy");
    expect(screen.queryByRole("combobox", { name: "Runtime tool access" })).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Native model ID (optional)" })).toBeNull();
    expect(screen.getByRole("option", { name: "Agent default (gemini-3-pro)" })).toBeVisible();
    expect(screen.getByText(/uses your Google personal sign-in/)).toBeVisible();
    fireEvent.change(screen.getByRole("combobox", { name: "Model" }), {
      target: { value: "gemini-3-flash" },
    });
    const picked = changed.mock.lastCall?.[0].conversation_runtime;
    expect(picked).toMatchObject({ model_id: "gemini-3-flash", registration_id: "agy" });
    expect(picked?.session_epoch).not.toBe("original");
    fireEvent.change(screen.getByRole("combobox", { name: "Agent" }), {
      target: { value: "agy-work" },
    });
    expect(changed.mock.lastCall?.[0].conversation_runtime).toMatchObject({
      registration_id: "agy-work",
      model_id: null,
    });
  });

  it("reports an unreadable account catalog and lets the person retry", () => {
    const refetch = vi.fn();
    options.current = {
      isSuccess: false,
      isPending: false,
      isError: true,
      error: new Error("This Antigravity CLI does not offer Google personal login."),
      refetch,
    };
    render(
      <NativeConversationControl
        claudeEnabled
        codexEnabled
        externalEnabled
        registrations={[agy("agy", "Antigravity")]}
        target={{
          ...base,
          conversation_runtime: {
            harness: "external",
            session_epoch: "original",
            access: "edit",
            registration_id: "agy",
          },
        }}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/Google personal login/);
    expect(screen.getByRole("combobox", { name: "Model" })).toBeDisabled();
    expect(screen.queryByRole("combobox", { name: "Agent" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Read models again" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("explains a pending read and a failure without a message", () => {
    options.current = { isSuccess: false, isPending: true, isError: false, refetch: vi.fn() };
    const target: LocalTarget = {
      ...base,
      conversation_runtime: {
        harness: "external",
        session_epoch: "original",
        access: "edit",
        registration_id: "agy",
      },
    };
    const { rerender } = render(
      <NativeConversationControl
        claudeEnabled
        codexEnabled
        externalEnabled
        registrations={[agy("agy", "Antigravity")]}
        target={target}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/Reading the models/)).toBeVisible();
    expect(screen.getByRole("option", { name: "Agent default" })).toBeInTheDocument();
    options.current = {
      isSuccess: false,
      isPending: false,
      isError: true,
      error: "x",
      refetch: vi.fn(),
    };
    rerender(
      <NativeConversationControl
        claudeEnabled
        codexEnabled
        externalEnabled
        registrations={[agy("agy", "Antigravity")]}
        target={target}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/Could not read this agent's models/);
  });

  it("leaves the model to agents that choose it themselves and states the account terms", () => {
    options.requested.length = 0;
    render(
      <NativeConversationControl
        claudeEnabled
        codexEnabled
        externalEnabled
        registrations={[{ ...agy("kimi", "Kimi Code"), provider: "kimi" }]}
        target={{
          ...base,
          conversation_runtime: {
            harness: "external",
            session_epoch: "original",
            access: "edit",
            registration_id: "kimi",
          },
        }}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText("This agent chooses its model in its own settings.")).toBeVisible();
    expect(screen.queryByRole("combobox", { name: "Model" })).toBeNull();
    expect(options.requested).toEqual([]);
    expect(screen.getByText(/that risk is yours/)).toBeVisible();
  });

  it("offers every registration that speaks ACP and keeps Pi for delegation", () => {
    const registrations = [
      agy("agy", "Antigravity"),
      { ...agy("pi", "Pi"), provider: "pi" as const },
      { ...agy("pi-deepseek", "Pi · DeepSeek"), provider: "pi_deepseek" as const },
      { ...agy("cursor", "Cursor"), provider: "cursor" as const },
    ];
    expect(conversationRegistrations(registrations).map((item) => item.id)).toEqual([
      "agy",
      "cursor",
    ]);
  });

  it("runs an Antigravity key registration on a chosen Gemini vault key or Desktop's own", () => {
    options.current = signedIn;
    vault.current = {
      secrets: [
        { id: "g", name: "Team Gemini", kind: "api_key", purpose: "google" },
        { id: "c", name: "Custom key", kind: "api_key", purpose: "custom" },
        { id: "o", name: "OpenAI", kind: "api_key", purpose: "openai" },
        { id: "s", name: "Service account", kind: "service_account", purpose: "google" },
      ],
      listError: null,
    };
    const changed = vi.fn<(target: LocalTarget) => void>();
    render(
      <NativeConversationControl
        claudeEnabled
        codexEnabled
        externalEnabled
        registrations={[
          { ...agy("agy-key", "Antigravity key"), provider: "antigravity_api_key" },
          agy("agy", "Antigravity"),
        ]}
        target={{
          ...base,
          conversation_runtime: {
            harness: "external",
            session_epoch: "original",
            access: "edit",
            registration_id: "agy-key",
          },
        }}
        onChange={changed}
      />,
    );
    const picker = screen.getByRole("combobox", { name: "Gemini API key" });
    expect(Array.from((picker as HTMLSelectElement).options).map((option) => option.value)).toEqual(
      ["", "g", "c"],
    );
    expect(screen.queryByText(/uses your Google personal sign-in/)).toBeNull();
    fireEvent.change(picker, { target: { value: "g" } });
    const picked = changed.mock.lastCall?.[0].conversation_runtime;
    expect(picked).toMatchObject({ secret_id: "g" });
    expect(picked?.session_epoch).not.toBe("original");
    fireEvent.change(picker, { target: { value: "" } });
    expect(changed.mock.lastCall?.[0].conversation_runtime?.secret_id).toBeNull();
    fireEvent.change(screen.getByRole("combobox", { name: "Agent" }), {
      target: { value: "agy" },
    });
    expect(changed.mock.lastCall?.[0].conversation_runtime).toMatchObject({
      registration_id: "agy",
      secret_id: null,
    });
  });

  it("falls back to Desktop's key when the vault cannot be listed", () => {
    vault.current = { secrets: [], listError: new Error("403") };
    const changed = vi.fn();
    options.requested.length = 0;
    render(
      <NativeConversationControl
        claudeEnabled
        codexEnabled
        externalEnabled
        registrations={[{ ...agy("agy-key", "Antigravity key"), provider: "antigravity_api_key" }]}
        target={{
          ...base,
          conversation_runtime: {
            harness: "external",
            session_epoch: "original",
            access: "edit",
            registration_id: "agy-key",
          },
        }}
        onChange={changed}
      />,
    );
    expect(screen.getByText(/key inherited by Desktop is used/)).toBeVisible();
    expect(options.requested).toEqual([]);
    fireEvent.change(screen.getByRole("textbox", { name: "Native model ID (optional)" }), {
      target: { value: "gemini-pro" },
    });
    expect(changed.mock.lastCall?.[0].conversation_runtime?.model_id).toBe("gemini-pro");
  });
});
