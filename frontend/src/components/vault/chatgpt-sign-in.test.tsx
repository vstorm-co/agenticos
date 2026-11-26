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
/** Codex offers a device code first; pasting the address is the folded fallback. */
const openPaste = () => userEvent.click(screen.getByText("Paste an address instead"));
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

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn() } }));

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
    await openPaste();

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
    await userEvent.click(await screen.findByText("Paste an address instead"));

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
    await userEvent.click(await screen.findByText("Paste an address instead"));

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

  it("is a sign-in again, not a value to type", async () => {
    open();
    await openPaste();

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
    await openPaste();

    await userEvent.type(screen.getByLabelText("Address ChatGPT sent you to"), CALLBACK);
    await userEvent.click(screen.getByRole("button", { name: "Reconnect" }));

    expect(await screen.findByText("ChatGPT did not accept this sign-in")).toBeVisible();
  });
});

describe("official ChatGPT application consent", () => {
  const official = { ...STORED, kind: "openai_chatgpt" as const, purpose: "openai_chatgpt" };
  const officialKind = { ...CODEX, kind: "openai_chatgpt" as const };
  const callback = "http://127.0.0.1:1455/auth/callback?code=c&state=s";

  it("opens the independent official flow and explains its loopback callback", async () => {
    const tab = fakeTab();
    api.post.mockResolvedValue({ authorization_url: AUTHORIZE });
    render(
      <ChatGPTSignInSteps
        kind="openai_chatgpt"
        callbackUrl=""
        onCallbackUrlChange={vi.fn()}
        idPrefix="official"
      />,
    );
    expect(screen.getByText(/public Responses API/)).toBeVisible();
    expect(screen.getByLabelText("Address ChatGPT sent you to")).toHaveAttribute(
      "placeholder",
      "http://127.0.0.1:1455/auth/callback?code=…",
    );
    await userEvent.click(screen.getByRole("button", { name: "Sign in with ChatGPT" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/secrets/openai-chatgpt/sign-in"));
    expect(tab.location.href).toBe(AUTHORIZE);
  });

  it.each([true, false])(
    "stores explicit plan consent %s without mixing Codex grants",
    async (granted) => {
      const created = vi.fn();
      api.post.mockResolvedValue({ connection: official, plan_usage_granted: granted });
      render(
        <InlineChatGPTSignIn
          kind="openai_chatgpt"
          suggestedName="Official ChatGPT"
          onCreated={created}
        />,
      );
      await userEvent.type(screen.getByLabelText("Address ChatGPT sent you to"), callback);
      await userEvent.click(screen.getByRole("button", { name: "Save sign-in" }));
      await waitFor(() => expect(created).toHaveBeenCalledWith("s1"));
      expect(api.post).toHaveBeenCalledWith("/secrets/openai-chatgpt", {
        name: "Official ChatGPT",
        callback_url: callback,
        visibility: "private",
      });
      if (granted) expect(toast.warning).not.toHaveBeenCalled();
      else expect(toast.warning).toHaveBeenCalledWith(expect.stringContaining("cannot run models"));
    },
  );

  it.each([true, false])(
    "reconnects an official grant with explicit plan consent %s",
    async (granted) => {
      api.put.mockResolvedValue({ connection: official, plan_usage_granted: granted });
      render(
        <RotateSecretDialog
          secret={official}
          onOpenChange={vi.fn()}
          kinds={[officialKind]}
          onSubmit={vi.fn()}
          isPending={false}
        />,
      );
      await userEvent.type(screen.getByLabelText("Address ChatGPT sent you to"), callback);
      await userEvent.click(screen.getByRole("button", { name: "Reconnect" }));
      await waitFor(() =>
        expect(api.put).toHaveBeenCalledWith("/secrets/s1/openai-chatgpt", {
          callback_url: callback,
        }),
      );
      await waitFor(() => expect(toast.success).toHaveBeenCalled());
      if (granted) expect(toast.warning).not.toHaveBeenCalled();
      else expect(toast.warning).toHaveBeenCalled();
    },
  );
});

it("stores an official grant privately from the vault and never offers token entry", async () => {
  const purpose = {
    ...PURPOSES.items[0]!,
    id: "openai_chatgpt",
    label: "ChatGPT plan usage (official)",
    kind: "openai_chatgpt",
  };
  PURPOSES.items.push(purpose);
  onTestFinished(() => {
    PURPOSES.items.splice(PURPOSES.items.indexOf(purpose), 1);
  });
  const official = { ...STORED, kind: "openai_chatgpt" as const, purpose: "openai_chatgpt" };
  api.post.mockResolvedValue({ connection: official, plan_usage_granted: true });
  render(
    <AddSecretDialog
      open
      onOpenChange={vi.fn()}
      kinds={[{ ...CODEX, kind: "openai_chatgpt" }]}
      onSubmit={vi.fn()}
      isPending={false}
      purposeId="openai_chatgpt"
    />,
  );
  expect(await screen.findByLabelText("Address ChatGPT sent you to")).toBeVisible();
  expect(screen.getByRole("combobox", { name: "Who can use it" })).toBeDisabled();
  expect(screen.getByText(/Only you can run models on this grant/)).toBeVisible();
  expect(screen.queryByLabelText(/Access token/)).not.toBeInTheDocument();
  const callback = "http://127.0.0.1:1455/auth/callback?code=c&state=s";
  await userEvent.type(screen.getByLabelText("Address ChatGPT sent you to"), callback);
  await userEvent.click(screen.getByRole("button", { name: "Store key" }));
  await waitFor(() =>
    expect(api.post).toHaveBeenCalledWith("/secrets/openai-chatgpt", {
      name: "ChatGPT plan usage (official)",
      description: null,
      visibility: "private",
      callback_url: callback,
    }),
  );
});

describe("signing in to Codex with a device code", () => {
  const DEVICE = {
    state: "st-1",
    user_code: "ABCD-1234",
    verification_url: "https://auth.openai.com/codex/device",
    interval_seconds: 1,
  };

  it("shows the code, opens ChatGPT and stores the approved sign-in without a paste", async () => {
    const tab = fakeTab();
    let polls = 0;
    api.post.mockImplementation(async (url: string) => {
      if (url === "/secrets/openai-codex/device") return DEVICE;
      if (url === "/secrets/openai-codex/device/st-1") return { authorized: ++polls > 1 };
      if (url === "/secrets/openai-codex") return { ...STORED, id: "new-secret" };
      throw new Error(url);
    });
    const onCreated = vi.fn();
    render(<InlineChatGPTSignIn suggestedName="ChatGPT" onCreated={onCreated} />);

    await userEvent.click(screen.getByRole("button", { name: "Sign in with a code" }));

    expect(await screen.findByText("ABCD-1234")).toBeVisible();
    await waitFor(() => expect(tab.location.href).toBe(DEVICE.verification_url));
    await waitFor(
      () =>
        expect(api.post).toHaveBeenCalledWith(
          "/secrets/openai-codex",
          expect.objectContaining({ device_state: "st-1", visibility: "private" }),
        ),
      { timeout: 4000 },
    );
    expect(api.post).not.toHaveBeenCalledWith(
      "/secrets/openai-codex",
      expect.objectContaining({ callback_url: expect.anything() }),
    );
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("new-secret"));
  });

  it("reports an expired code and lets the person start again", async () => {
    vi.spyOn(window, "open").mockReturnValue(null);
    api.post.mockImplementation(async (url: string) => {
      if (url === "/secrets/openai-codex/device") return DEVICE;
      throw new ApiError(400, "This device sign-in has expired");
    });
    render(<InlineChatGPTSignIn suggestedName="ChatGPT" onCreated={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: "Sign in with a code" }));

    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.getByRole("button", { name: "Sign in with a code" })).toBeEnabled();
  });

  it("reconnects a stored sign-in with the approved code", async () => {
    vi.spyOn(window, "open").mockReturnValue(null);
    api.post.mockImplementation(async (url: string) =>
      url === "/secrets/openai-codex/device" ? DEVICE : { authorized: true },
    );
    api.put.mockResolvedValue(STORED);
    render(
      <RotateSecretDialog
        secret={STORED}
        onOpenChange={vi.fn()}
        kinds={[API_KEY, CODEX]}
        onSubmit={vi.fn()}
        isPending={false}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Sign in with a code" }));
    expect(await screen.findByText("Approved.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Reconnect" }));

    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith("/secrets/s1/openai-codex", { device_state: "st-1" }),
    );
  });
});
