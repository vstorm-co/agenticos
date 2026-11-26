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
  expect(screen.getByText(/at your own risk/)).toBeVisible();
  const register = screen.getByRole("button", { name: "Register agent" });
  expect(register).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox", { name: /accept this risk/ }));
  await userEvent.click(register);
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

it("registers the Antigravity Gemini API key template without the sign-in risk step", async () => {
  mount();
  await userEvent.selectOptions(screen.getByLabelText("Setup template"), "antigravity_api_key");
  expect(screen.queryByRole("checkbox", { name: /accept this risk/ })).toBeNull();
  expect(screen.getByLabelText("Agent ID")).toHaveValue("antigravity-api-key");
  expect(screen.getByLabelText("Arguments (JSON array)")).toHaveValue('["acp"]');
  expect(screen.getByText(/never falls back to the saved Google sign-in/)).toBeVisible();
  await userEvent.type(screen.getByLabelText("Absolute executable path"), "/opt/bin/agy");
  await userEvent.click(screen.getByRole("button", { name: "Register agent" }));
  await waitFor(() =>
    expect(invoke).toHaveBeenCalledWith("external_save_agent", {
      registration: {
        provider: "antigravity_api_key",
        id: "antigravity-api-key",
        name: "Antigravity · Gemini API key",
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

it("registers local Devin ACP with normal permissions and no cloud flag", async () => {
  mount();
  await userEvent.selectOptions(screen.getByLabelText("Setup template"), "devin");
  expect(screen.getByText(/requires the advertised devin-browser method/)).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Absolute executable path"), "/opt/bin/devin");
  await userEvent.click(screen.getByRole("button", { name: "Register agent" }));
  await waitFor(() =>
    expect(invoke).toHaveBeenCalledWith("external_save_agent", {
      registration: {
        provider: "devin",
        id: "devin",
        name: "Devin",
        program: "/opt/bin/devin",
        args: ["--permission-mode", "normal", "acp"],
      },
    }),
  );
  expect(parseExternalAgents([{ ...registration, provider: "devin" }])).toEqual([
    { ...registration, provider: "devin" },
  ]);
});

it("registers Pi with native RPC and preserves its CLI model configuration", async () => {
  mount();
  await userEvent.selectOptions(screen.getByLabelText("Setup template"), "pi");
  expect(screen.getByText(/Pi uses native RPC/)).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Absolute executable path"), "/opt/bin/pi");
  await userEvent.click(screen.getByRole("button", { name: "Register agent" }));
  await waitFor(() =>
    expect(invoke).toHaveBeenCalledWith("external_save_agent", {
      registration: {
        provider: "pi",
        id: "pi",
        name: "Pi",
        program: "/opt/bin/pi",
        args: ["--mode", "rpc"],
      },
    }),
  );
  expect(parseExternalAgents([{ ...registration, provider: "pi" }])).toEqual([
    { ...registration, provider: "pi" },
  ]);
});

it.each(["muse", "muse_api_key"])(
  "registers %s with a native SDK foreground host",
  async (provider) => {
    mount();
    await userEvent.selectOptions(screen.getByLabelText("Setup template"), provider);
    expect(screen.getByText(/Muse requires CLI 1.4.23/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Absolute executable path"), "/opt/bin/muse");
    await userEvent.click(screen.getByRole("button", { name: "Register agent" }));
    await waitFor(() =>
      expect(invoke).toHaveBeenCalledWith("external_save_agent", {
        registration: {
          provider,
          id: provider.replaceAll("_", "-"),
          name: provider === "muse" ? "Muse" : "Muse API key",
          program: "/opt/bin/muse",
          args: ["serve"],
        },
      }),
    );
    expect(parseExternalAgents([{ ...registration, provider }])).toEqual([
      { ...registration, provider },
    ]);
  },
);

it.each([
  ["pi_inception", "Pi · Inception"],
  ["pi_deepseek", "Pi · DeepSeek"],
  ["pi_openrouter", "Pi · OpenRouter"],
])("registers %s as an explicit isolated vault-key lane", async (provider, name) => {
  mount();
  await userEvent.selectOptions(screen.getByLabelText("Setup template"), provider);
  expect(screen.getByText(/Pi 1.5.2 is required/)).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Absolute executable path"), "/opt/bin/pi");
  await userEvent.click(screen.getByRole("button", { name: "Register agent" }));
  await waitFor(() =>
    expect(invoke).toHaveBeenCalledWith("external_save_agent", {
      registration: {
        provider,
        id: provider.replaceAll("_", "-"),
        name,
        program: "/opt/bin/pi",
        args: [
          "--mode",
          "rpc",
          "--no-extensions",
          "--no-skills",
          "--no-prompt-templates",
          "--no-mcp",
        ],
      },
    }),
  );
  expect(parseExternalAgents([{ ...registration, provider }])[0]?.provider).toBe(provider);
});

it("registers Hermes with an explicit Python environment and owned foreground setup", async () => {
  mount();
  await userEvent.selectOptions(screen.getByLabelText("Setup template"), "hermes");
  expect(screen.getByLabelText("Arguments (JSON array)")).toHaveValue("[]");
  expect(
    screen.getByText(/Select the Python executable in the documented Hermes environment/),
  ).toBeVisible();
  await userEvent.type(
    screen.getByLabelText("Absolute executable path"),
    "/hermes/.venv/bin/python",
  );
  await userEvent.click(screen.getByRole("button", { name: "Register agent" }));
  await waitFor(() =>
    expect(invoke).toHaveBeenCalledWith("external_save_agent", {
      registration: {
        provider: "hermes",
        id: "hermes",
        name: "Hermes",
        program: "/hermes/.venv/bin/python",
        args: [],
      },
    }),
  );
  expect(
    parseExternalAgents([{ ...registration, provider: "hermes", args: [] }])[0]?.provider,
  ).toBe("hermes");
});

it.each([
  ["cursor_api_key", "Cursor API key", ["acp"]],
  ["grok_api_key", "Grok API key", ["--no-auto-update", "agent", "stdio"]],
])(
  "registers the isolated %s template without accepting a credential in its configuration",
  async (provider, label, args) => {
    mount();
    await userEvent.selectOptions(screen.getByLabelText("Setup template"), provider);
    await userEvent.type(screen.getByLabelText("Absolute executable path"), registration.program);
    await userEvent.click(screen.getByRole("button", { name: "Register agent" }));
    await waitFor(() =>
      expect(invoke).toHaveBeenCalledWith("external_save_agent", {
        registration: {
          provider,
          id: provider.replaceAll("_", "-"),
          name: label,
          program: registration.program,
          args,
        },
      }),
    );
  },
);
