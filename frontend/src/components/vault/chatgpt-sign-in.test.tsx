import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render as baseRender, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { toast } from "sonner";

import { ChatGPTSignInSteps, InlineChatGPTSignIn } from "./chatgpt-sign-in";
import { AddSecretDialog, RotateSecretDialog } from "./secret-dialog";
import { ApiError } from "@/lib/api-error";
import { useAuthStore } from "@/stores";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";
import type { Secret, SecretKindInfo } from "@/types/secrets";

/**
 * Signing in with ChatGPT, the one secret nobody types.
 *
 * What these pin is the part a person cannot see go wrong: the tab is opened
 * inside the click (or a popup blocker eats it), the pasted address goes to the
 * sign-in endpoint rather than to `POST /secrets`, and a sign-in is somebody's
 * own subscription, so it starts private.
 */

const AUTHORIZE = "https://auth.openai.com/oauth/authorize?state=s";
const CALLBACK = "http://localhost:1455/auth/callback?code=c&state=s";

const PURPOSES = {
  items: [
    {
      id: "openai_codex",
      label: "ChatGPT (Codex subscription)",
      category: "model_provider",
      kind: "openai_codex",
      help_url: null,
      description: "Run models on a ChatGPT subscription.",
      icon: "",
    },
    {
      id: "custom",
      label: "Something else",
      category: "other",
      kind: "api_key",
      help_url: null,
      description: "A key for a service this deployment does not know about yet.",
      icon: "",
    },
  ],
  total: 2,
};

const api = vi.hoisted(() => ({ post: vi.fn(), put: vi.fn() }));

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: {
      ...actual.apiClient,
      get: vi
        .fn()
        .mockImplementation(async (path: string) =>
          path === "/secrets/purposes" ? PURPOSES : { items: [], total: 0 },
        ),
      post: api.post,
      put: api.put,
    },
  };
});

const held: { permissions: Permission[] } = { permissions: [] };

vi.mock("@/hooks", async () => {
  const actual = await vi.importActual<typeof import("@/hooks")>("@/hooks");
  return {
    ...actual,
    usePermissions: () => ({
      can: (permission: Permission) => held.permissions.includes(permission),
    }),
  };
});

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

function render(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return baseRender(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

/** A tab opened inside the click, so the test can see where it was sent. */
function fakeTab() {
  const tab = { opener: {} as unknown, location: { href: "" }, close: vi.fn() };
  vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
  return tab;
}

const STORED: Secret = {
  id: "s1",
  name: "My ChatGPT",
  description: null,
  kind: "openai_codex",
  hint: "abcd",
  purpose: "openai_codex",
};

const CODEX: SecretKindInfo = {
  kind: "openai_codex",
  name: "ChatGPT sign-in",
  description: "A ChatGPT subscription's sign-in.",
  json_schema: {
    type: "object",
    properties: {
      kind: { const: "openai_codex", type: "string" },
      access_token: { type: "string", format: "password", title: "Access token" },
    },
    required: ["access_token"],
  },
};

const API_KEY: SecretKindInfo = {
  kind: "api_key",
  name: "API key",
  description: "A single token.",
  json_schema: {
    type: "object",
    properties: {
      kind: { const: "api_key", type: "string" },
      api_key: { type: "string", format: "password", title: "Api Key" },
    },
    required: ["api_key"],
  },
};

/** A 400 naming the pasted address, in the envelope the server sends. */
function refusedPaste(message: string) {
  const body = {
    error: {
      code: "BAD_REQUEST",
      message,
      details: { fields: [{ field: "callback_url", message }] },
    },
  };
  return new ApiError(400, message, body);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
  held.permissions = [Perm.secretsEdit];
  api.post.mockImplementation(async (path: string) =>
    path === "/secrets/openai-codex/sign-in" ? { authorization_url: AUTHORIZE } : STORED,
  );
  api.put.mockResolvedValue(STORED);
});

describe("starting a sign-in", () => {
  const mount = () =>
    render(<ChatGPTSignInSteps callbackUrl="" onCallbackUrlChange={vi.fn()} idPrefix="t" />);

  it("sends the tab it opened inside the click to ChatGPT, cut off from this page", async () => {
    const tab = fakeTab();
    mount();

    await userEvent.click(screen.getByRole("button", { name: "Sign in with ChatGPT" }));

    await waitFor(() => expect(tab.location.href).toBe(AUTHORIZE));
    expect(window.open).toHaveBeenCalledWith("", "_blank");
    expect(tab.opener).toBeNull();
    // Left behind for when a blocker ate the tab, or somebody closed it.
    expect(screen.getByRole("link", { name: "Open the sign-in again" })).toHaveAttribute(
      "href",
      AUTHORIZE,
    );
  });

  it("still offers the sign-in as a link when no tab could be opened", async () => {
    vi.spyOn(window, "open").mockReturnValue(null);
    mount();

    await userEvent.click(screen.getByRole("button", { name: "Sign in with ChatGPT" }));

    expect(await screen.findByRole("link", { name: "Open the sign-in again" })).toBeVisible();
  });

  it("closes the empty tab and says why when the sign-in cannot start", async () => {
    const tab = fakeTab();
    api.post.mockRejectedValue(new ApiError(403, "Missing permission"));
    mount();

    await userEvent.click(screen.getByRole("button", { name: "Sign in with ChatGPT" }));

    await waitFor(() => expect(tab.close).toHaveBeenCalled());
    expect(toast.error).toHaveBeenCalled();
  });

  it("tells the person the address will not load, before it does not", () => {
    mount();
    expect(screen.getByText(/does not load\. That is expected/)).toBeVisible();
  });
});

describe("the inline sign-in beside a model picker", () => {
  const mount = (onCreated = vi.fn()) => {
    render(<InlineChatGPTSignIn suggestedName="ChatGPT" onCreated={onCreated} />);
    return onCreated;
  };

  it("is a sentence, not a form, for a caller who may not store secrets", () => {
    held.permissions = [];
    mount();
    expect(screen.queryByRole("button", { name: "Save sign-in" })).toBeNull();
    expect(screen.getByText(/permission/)).toBeVisible();
  });

  it("stores the pasted address as a private sign-in and hands back its id", async () => {
    const onCreated = mount();

    expect(screen.getByRole("button", { name: "Save sign-in" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Address ChatGPT sent you to"), CALLBACK);
    await userEvent.click(screen.getByRole("button", { name: "Save sign-in" }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("s1"));
    expect(api.post).toHaveBeenCalledWith("/secrets/openai-codex", {
      name: "ChatGPT",
      callback_url: CALLBACK,
      visibility: "private",
    });
    expect(screen.getByLabelText("Address ChatGPT sent you to")).toHaveValue("");
  });

  it("names the sign-in for whose it is, so a second person's does not collide", async () => {
    useAuthStore.setState({
      user: {
        id: "u-2",
        email: "anna@acme.test",
        full_name: "Anna Nowak",
        is_active: true,
        created_at: "2026-10-18T00:00:00Z",
      },
    });
    onTestFinished(() => {
      useAuthStore.setState({ user: null });
    });
    mount();

    await userEvent.type(screen.getByLabelText("Address ChatGPT sent you to"), CALLBACK);
    await userEvent.click(screen.getByRole("button", { name: "Save sign-in" }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        "/secrets/openai-codex",
        expect.objectContaining({ name: "ChatGPT - Anna Nowak" }),
      ),
    );
  });

  it("puts a refused paste under the field it was pasted into", async () => {
    api.post.mockRejectedValue(refusedPaste("This sign-in has expired"));
    const onCreated = mount();

    await userEvent.type(screen.getByLabelText("Address ChatGPT sent you to"), CALLBACK);
    await userEvent.click(screen.getByRole("button", { name: "Save sign-in" }));

    expect(await screen.findByText("This sign-in has expired")).toBeVisible();
    expect(onCreated).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();

    // Editing the paste clears a refusal about the old one.
    await userEvent.type(screen.getByLabelText("Address ChatGPT sent you to"), "x");
    expect(screen.queryByText("This sign-in has expired")).toBeNull();
  });

  it("toasts a refusal that is not about the paste", async () => {
    api.post.mockRejectedValue(new ApiError(500, "Internal server error"));
    mount();

    await userEvent.type(screen.getByLabelText("Address ChatGPT sent you to"), CALLBACK);
    await userEvent.click(screen.getByRole("button", { name: "Save sign-in" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });
});

describe("adding a ChatGPT sign-in to the vault", () => {
  const open = (onSubmit = vi.fn()) => {
    render(
      <AddSecretDialog
        open
        onOpenChange={vi.fn()}
        kinds={[API_KEY, CODEX]}
        onSubmit={onSubmit}
        isPending={false}
        purposeId="openai_codex"
      />,
    );
    return onSubmit;
  };

  it("asks for the address instead of the token fields its schema has", async () => {
    open();

    expect(await screen.findByLabelText("Address ChatGPT sent you to")).toBeVisible();
    expect(screen.queryByLabelText(/Access token/)).toBeNull();
  });

  it("starts private, because it is somebody's own subscription", async () => {
    open();

    await screen.findByLabelText("Address ChatGPT sent you to");
    expect(screen.getByRole("combobox", { name: "Who can use it" })).toHaveTextContent("Only me");
  });

  it("finishes the sign-in rather than posting a value", async () => {
    const onSubmit = open();

    await userEvent.type(await screen.findByLabelText("Address ChatGPT sent you to"), CALLBACK);
    await userEvent.click(screen.getByRole("button", { name: "Store key" }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/secrets/openai-codex", {
        name: "ChatGPT (Codex subscription)",
        description: null,
        visibility: "private",
        callback_url: CALLBACK,
      }),
    );
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("puts a refused paste under the address field", async () => {
    api.post.mockRejectedValue(refusedPaste("Paste the whole address"));
    open();

    await userEvent.type(await screen.findByLabelText("Address ChatGPT sent you to"), "nope");
    await userEvent.click(screen.getByRole("button", { name: "Store key" }));

    expect(await screen.findByText("Paste the whole address")).toBeVisible();
  });

  it("is not a shape a custom secret can take", async () => {
    render(
      <AddSecretDialog
        open
        onOpenChange={vi.fn()}
        kinds={[API_KEY, CODEX]}
        onSubmit={vi.fn()}
        isPending={false}
        purposeId="custom"
      />,
    );

    await userEvent.click(await screen.findByRole("combobox", { name: "Kind" }));
    expect(screen.getByRole("option", { name: "API key" })).toBeVisible();
    expect(screen.queryByRole("option", { name: "ChatGPT sign-in" })).toBeNull();
  });
});

describe("reconnecting a ChatGPT sign-in", () => {
  const open = (onSubmit = vi.fn()) => {
    render(
      <RotateSecretDialog
        secret={STORED}
        onOpenChange={vi.fn()}
        kinds={[CODEX]}
        onSubmit={onSubmit}
        isPending={false}
      />,
    );
    return onSubmit;
  };

  it("is a sign-in again, not a value to type", () => {
    open();

    expect(screen.getByRole("dialog")).toHaveTextContent("Reconnect My ChatGPT");
    expect(screen.getByLabelText("Address ChatGPT sent you to")).toBeVisible();
    expect(screen.queryByLabelText(/Access token/)).toBeNull();
  });

  it("puts the new sign-in in place of the old one, keeping the id", async () => {
    const onSubmit = open();

    await userEvent.type(screen.getByLabelText("Address ChatGPT sent you to"), CALLBACK);
    await userEvent.click(screen.getByRole("button", { name: "Reconnect" }));

    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith("/secrets/s1/openai-codex", { callback_url: CALLBACK }),
    );
    expect(onSubmit).not.toHaveBeenCalled();
    expect(toast.success).toHaveBeenCalledWith("Reconnected My ChatGPT to ChatGPT");
  });

  it("puts a refused paste under the address field", async () => {
    api.put.mockRejectedValue(refusedPaste("ChatGPT did not accept this sign-in"));
    open();

    await userEvent.type(screen.getByLabelText("Address ChatGPT sent you to"), CALLBACK);
    await userEvent.click(screen.getByRole("button", { name: "Reconnect" }));

    expect(await screen.findByText("ChatGPT did not accept this sign-in")).toBeVisible();
  });
});
