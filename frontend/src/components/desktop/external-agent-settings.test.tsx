import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ExternalAgentSettings } from "./external-agent-settings";
import { parseExternalAgents } from "@/lib/desktop/commands";

const invoke = vi.hoisted(() => vi.fn());
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/shell")>()),
  invokeShell: invoke,
}));
const registration = {
  provider: "custom",
  id: "my-agent",
  name: "My agent",
  program: "/opt/bin/agent",
  args: ["acp"],
  revision: "v1",
};
beforeEach(() => {
  window.__AGENTICOS_SHELL__ = {
    platform: "macos",
    version: "0.2.0",
    window: "main",
    vibrancy: true,
  };
  invoke.mockReset();
  invoke.mockResolvedValue([]);
});
afterEach(() => {
  delete window.__AGENTICOS_SHELL__;
});
function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
        })
      }
    >
      <ExternalAgentSettings />
    </QueryClientProvider>,
  );
}
async function fill() {
  await userEvent.type(screen.getByLabelText("Agent ID"), registration.id);
  await userEvent.type(screen.getByLabelText("Display name"), registration.name);
  await userEvent.type(screen.getByLabelText("Absolute executable path"), registration.program);
}
it("registers exact argv over native IPC and refreshes after confirmation", async () => {
  invoke.mockImplementation(async (command: string) =>
    command === "external_agents" ? [] : [registration],
  );
  mount();
  await fill();
  await userEvent.clear(screen.getByLabelText("Arguments (JSON array)"));
  await userEvent.paste('["acp","literal;$HOME"]');
  await userEvent.click(screen.getByRole("button", { name: "Register agent" }));
  await waitFor(() =>
    expect(invoke).toHaveBeenCalledWith("external_save_agent", {
      registration: {
        provider: "custom",
        id: "my-agent",
        name: "My agent",
        program: "/opt/bin/agent",
        args: ["acp", "literal;$HOME"],
      },
    }),
  );
  await waitFor(() => expect(screen.getByLabelText("Agent ID")).toHaveValue(""));
});
it.each(['{"command":"sh"}', "[1]", "invalid"])(
  "refuses non-string argv %s before native registration",
  async (args) => {
    mount();
    await fill();
    await userEvent.clear(screen.getByLabelText("Arguments (JSON array)"));
    await userEvent.paste(args);
    await userEvent.click(screen.getByRole("button", { name: "Register agent" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Enter a JSON array containing only strings.",
    );
    expect(invoke.mock.calls.some(([command]) => command === "external_save_agent")).toBe(false);
  },
);
it("revokes the named local registration", async () => {
  invoke.mockImplementation(async (command: string) =>
    command === "external_agents" ? [registration] : [],
  );
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Remove My agent" }));
  await waitFor(() =>
    expect(invoke).toHaveBeenCalledWith("external_remove_agent", { id: "my-agent" }),
  );
});
it("rejects malformed native replies", () => {
  expect(parseExternalAgents([registration])).toEqual([registration]);
  expect(() => parseExternalAgents({})).toThrow("malformed");
  expect(() => parseExternalAgents([{ ...registration, provider: "unsupported" }])).toThrow(
    "malformed",
  );
  expect(() => parseExternalAgents([{ ...registration, args: [1] }])).toThrow("malformed");
  expect(() => parseExternalAgents([{ ...registration, revision: null }])).toThrow("malformed");
});

it("registers the Antigravity personal-account template without an API key", async () => {
  mount();
  await userEvent.selectOptions(screen.getByLabelText("Setup template"), "antigravity");
  expect(screen.getByLabelText("Agent ID")).toHaveValue("antigravity");
  expect(screen.getByLabelText("Arguments (JSON array)")).toHaveValue('["acp"]');
  await userEvent.type(screen.getByLabelText("Absolute executable path"), "/opt/bin/agy");
  await userEvent.click(screen.getByRole("button", { name: "Register agent" }));
  await waitFor(() =>
    expect(invoke).toHaveBeenCalledWith("external_save_agent", {
      registration: {
        provider: "antigravity",
        id: "antigravity",
        name: "Antigravity",
        program: "/opt/bin/agy",
        args: ["acp"],
      },
    }),
  );
});

it.each([
  ["cursor", "cursor", "Cursor"],
  ["opencode", "opencode", "OpenCode"],
  ["opencode_go", "opencode-go", "OpenCode Go"],
])("registers %s without copying provider credentials", async (provider, id, name) => {
  mount();
  await userEvent.selectOptions(screen.getByLabelText("Setup template"), provider);
  expect(screen.getByLabelText("Agent ID")).toHaveValue(id);
  expect(screen.getByLabelText("Arguments (JSON array)")).toHaveValue('["acp"]');
  await userEvent.type(screen.getByLabelText("Absolute executable path"), "/opt/bin/opencode");
  await userEvent.click(screen.getByRole("button", { name: "Register agent" }));
  await waitFor(() =>
    expect(invoke).toHaveBeenCalledWith("external_save_agent", {
      registration: { provider, id, name, program: "/opt/bin/opencode", args: ["acp"] },
    }),
  );
  expect(parseExternalAgents([{ ...registration, provider }])).toEqual([
    { ...registration, provider },
  ]);
});

it.each([
  ["cline", "cline", "Cline"],
  ["cline_api_key", "cline-api-key", "Cline API key"],
])(
  "registers the %s foreground template with the selected credential mode",
  async (provider, id, name) => {
    mount();
    await userEvent.selectOptions(screen.getByLabelText("Setup template"), provider);
    expect(screen.getByLabelText("Arguments (JSON array)")).toHaveValue('["--acp"]');
    await userEvent.type(screen.getByLabelText("Absolute executable path"), "/opt/bin/cline");
    await userEvent.click(screen.getByRole("button", { name: "Register agent" }));
    await waitFor(() =>
      expect(invoke).toHaveBeenCalledWith("external_save_agent", {
        registration: { provider, id, name, program: "/opt/bin/cline", args: ["--acp"] },
      }),
    );
    expect(parseExternalAgents([{ ...registration, provider }])).toEqual([
      { ...registration, provider },
    ]);
  },
);

it("keeps the editable command when switching a template back to custom", async () => {
  mount();
  await userEvent.selectOptions(screen.getByLabelText("Setup template"), "opencode");
  await userEvent.selectOptions(screen.getByLabelText("Setup template"), "custom");
  await userEvent.type(screen.getByLabelText("Absolute executable path"), "/opt/bin/my-agent");
  await userEvent.click(screen.getByRole("button", { name: "Register agent" }));
  await waitFor(() =>
    expect(invoke).toHaveBeenCalledWith("external_save_agent", {
      registration: {
        provider: "custom",
        id: "opencode",
        name: "OpenCode",
        program: "/opt/bin/my-agent",
        args: ["acp"],
      },
    }),
  );
});

it("registers vibe-acp without arguments or copied credentials", async () => {
  mount();
  await userEvent.selectOptions(screen.getByLabelText("Setup template"), "mistral_vibe");
  expect(screen.getByLabelText("Arguments (JSON array)")).toHaveValue("[]");
  await userEvent.type(screen.getByLabelText("Absolute executable path"), "/opt/bin/vibe-acp");
  await userEvent.click(screen.getByRole("button", { name: "Register agent" }));
  await waitFor(() =>
    expect(invoke).toHaveBeenCalledWith("external_save_agent", {
      registration: {
        provider: "mistral_vibe",
        id: "mistral-vibe",
        name: "Mistral Vibe",
        program: "/opt/bin/vibe-acp",
        args: [],
      },
    }),
  );
  expect(parseExternalAgents([{ ...registration, provider: "mistral_vibe" }])).toEqual([
    { ...registration, provider: "mistral_vibe" },
  ]);
});

it("registers Grok cached-account stdio without background updates", async () => {
  mount();
  await userEvent.selectOptions(screen.getByLabelText("Setup template"), "grok");
  await userEvent.type(screen.getByLabelText("Absolute executable path"), "/opt/bin/grok");
  await userEvent.click(screen.getByRole("button", { name: "Register agent" }));
  await waitFor(() =>
    expect(invoke).toHaveBeenCalledWith("external_save_agent", {
      registration: {
        provider: "grok",
        id: "grok",
        name: "Grok",
        program: "/opt/bin/grok",
        args: ["--no-auto-update", "agent", "stdio"],
      },
    }),
  );
  expect(parseExternalAgents([{ ...registration, provider: "grok" }])).toEqual([
    { ...registration, provider: "grok" },
  ]);
});

it("registers Kimi with its CLI-owned configured account", async () => {
  mount();
  await userEvent.selectOptions(screen.getByLabelText("Setup template"), "kimi");
  expect(
    screen.getByText(/Keep External model ID empty and choose the model in Kimi/),
  ).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Absolute executable path"), "/opt/bin/kimi");
  await userEvent.click(screen.getByRole("button", { name: "Register agent" }));
  await waitFor(() =>
    expect(invoke).toHaveBeenCalledWith("external_save_agent", {
      registration: {
        provider: "kimi",
        id: "kimi",
        name: "Kimi Code",
        program: "/opt/bin/kimi",
        args: ["acp"],
      },
    }),
  );
  expect(parseExternalAgents([{ ...registration, provider: "kimi" }])).toEqual([
    { ...registration, provider: "kimi" },
  ]);
});

it("pins Qwen subscription auth without launching its mutating authentication RPC", async () => {
  mount();
  await userEvent.selectOptions(screen.getByLabelText("Setup template"), "qwen_subscription");
  expect(screen.getByText(/without calling ACP authenticate/)).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Absolute executable path"), "/opt/bin/qwen");
  await userEvent.click(screen.getByRole("button", { name: "Register agent" }));
  await waitFor(() =>
    expect(invoke).toHaveBeenCalledWith("external_save_agent", {
      registration: {
        provider: "qwen_subscription",
        id: "qwen-subscription",
        name: "Qwen subscription",
        program: "/opt/bin/qwen",
        args: ["--acp", "--auth-type=qwen-subscription"],
      },
    }),
  );
  expect(parseExternalAgents([{ ...registration, provider: "qwen_subscription" }])).toEqual([
    { ...registration, provider: "qwen_subscription" },
  ]);
});
