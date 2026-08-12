import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EmbedsPanel } from "./embeds-panel";
import {
  DEFAULT_PAGE_CONFIG,
  DEFAULT_WIDGET_CONFIG,
  type Embed,
  type EmbedKind,
} from "@/types/embeds";

/**
 * The panel that publishes an agent to the public internet.
 *
 * Two things it exists to get right. **The surfaces have to be visible**: a
 * widget, a socket and a page were one *Publish as widget* button with the other
 * two inside its form, which is how somebody looking for either found neither.
 * And **an allow-list is not decoration**: the key in a script tag is public by
 * construction, so on the two kinds admitted by an origin it is the whole of what
 * protects the agent - and on a page it is meaningless and must not be asked for.
 */

const state = {
  embeds: [] as Embed[],
  isLoading: false,
  create: { mutate: vi.fn(), isPending: false },
  update: { mutate: vi.fn(), isPending: false },
  remove: { mutateAsync: vi.fn(), isPending: false },
};

const copied = { value: false };
const copy = vi.fn();

vi.mock("@/hooks", () => ({ useEmbeds: () => state }));
vi.mock("@/hooks/use-copy-to-clipboard", () => ({
  useCopyToClipboard: () => ({ copy, copied: copied.value }),
}));

function embed(overrides: Partial<Embed> = {}): Embed {
  return {
    id: "e-1",
    agent_id: "a-1",
    name: "Website widget",
    kind: "widget",
    config: DEFAULT_WIDGET_CONFIG,
    public_key: "pk_live_abc",
    auth_mode: "public",
    has_jwt_secret: false,
    allowed_origins: ["https://acme.com"],
    context: null,
    context_variables: [],
    is_active: true,
    rate_limit_per_minute: 10,
    snippet: '<script src="https://app.test/embed.js" data-key="pk_live_abc"></script>',
    socket_url: "wss://app.test/api/v1/embed/pk_live_abc/ws",
    page_url: null,
    ...overrides,
  };
}

function page(overrides: Partial<Embed> = {}): Embed {
  return embed({
    name: "Hosted page",
    kind: "page",
    config: DEFAULT_PAGE_CONFIG,
    allowed_origins: [],
    snippet: null,
    socket_url: null,
    page_url: "https://chat.test/e/pk_live_abc",
    ...overrides,
  });
}

beforeEach(() => {
  state.embeds = [];
  state.isLoading = false;
  state.create = { mutate: vi.fn(), isPending: false };
  state.update = { mutate: vi.fn(), isPending: false };
  state.remove = { mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false };
  copied.value = false;
  copy.mockReset();
});

const CARD: Record<EmbedKind | "api", string> = {
  widget: "Website widget",
  socket: "Raw WebSocket",
  page: "Hosted page",
  api: "Public API",
};

async function pick(surface: EmbedKind | "api") {
  await userEvent.click(screen.getByRole("button", { name: new RegExp(CARD[surface]) }));
}

describe("choosing a surface", () => {
  it("shows a placeholder rather than an empty state while loading", () => {
    state.isLoading = true;
    render(<EmbedsPanel agentId="a-1" canManage />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByText("Not published to any site yet.")).toBeNull();
  });

  it("says so when the agent is published nowhere", () => {
    render(<EmbedsPanel agentId="a-1" canManage />);

    expect(screen.getByText("Not published to any site yet.")).toBeInTheDocument();
  });

  it("offers all four surfaces, not one with the rest hidden inside it", () => {
    // The defect this panel was rebuilt for: the socket and the hosted page were
    // reachable only by first publishing a widget.
    render(<EmbedsPanel agentId="a-1" canManage />);

    for (const name of Object.values(CARD)) {
      expect(screen.getByRole("button", { name: new RegExp(name) })).toBeInTheDocument();
    }
  });

  it("says the dashboard needs nothing, so its absence is not a gap", () => {
    render(<EmbedsPanel agentId="a-1" canManage />);

    expect(screen.getByText(/already chat with it in the dashboard/)).toBeInTheDocument();
  });

  it("offers no way to publish to somebody who may not publish", () => {
    render(<EmbedsPanel agentId="a-1" canManage={false} />);

    expect(screen.queryByRole("button", { name: /Website widget/ })).toBeNull();
  });

  it("says the API is a credential rather than an object to configure", async () => {
    // A card that opened an empty form would leave somebody hunting for the
    // setting it does not have.
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("api");

    expect(screen.getByText(/nothing on this screen to configure/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Allowed sites")).toBeNull();
  });
});

describe("an existing widget", () => {
  it("leads with the snippet, which is the only step a customer performs", () => {
    state.embeds = [embed()];
    render(<EmbedsPanel agentId="a-1" canManage />);

    expect(screen.getByText(/data-key="pk_live_abc"/)).toBeInTheDocument();
  });

  it("copies the snippet rather than the key alone", async () => {
    state.embeds = [embed()];
    render(<EmbedsPanel agentId="a-1" canManage />);

    await userEvent.click(screen.getByRole("button", { name: "Copy the snippet" }));

    expect(copy).toHaveBeenCalledWith(state.embeds[0]!.snippet);
  });

  it("offers the socket beside the script tag, not only in the docs", () => {
    // The whole of #516: the protocol was published and tested, and the only way
    // to discover it was to read the manual.
    state.embeds = [embed()];
    render(<EmbedsPanel agentId="a-1" canManage />);

    expect(screen.getByText("wss://app.test/api/v1/embed/pk_live_abc/ws")).toBeInTheDocument();
    expect(screen.getByText("Script tag - for a site you do not control")).toBeInTheDocument();
  });

  it("says a client of one's own must send an allowed Origin, and where 4003 is explained", () => {
    state.embeds = [embed()];
    render(<EmbedsPanel agentId="a-1" canManage />);

    expect(screen.getByText(/must set one that is on the allowed-sites list/)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Frames and close codes" });
    expect(link).toHaveAttribute("href", expect.stringContaining("#the-raw-websocket"));
  });

  it("shows the integration to somebody who may not manage the embed", () => {
    // Reading the integration is not managing it: `agents:publish` gates the
    // switch and the delete, not the address of a published socket.
    state.embeds = [embed()];
    render(<EmbedsPanel agentId="a-1" canManage={false} />);

    expect(screen.getByRole("button", { name: "Copy the socket URL" })).toBeInTheDocument();
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("names the sites it may be opened from", () => {
    state.embeds = [embed({ allowed_origins: ["https://acme.com", "https://www.acme.com"] })];
    render(<EmbedsPanel agentId="a-1" canManage />);

    expect(screen.getByText("https://acme.com, https://www.acme.com")).toBeInTheDocument();
  });

  it("says a widget allowed nowhere cannot open", () => {
    state.embeds = [embed({ allowed_origins: [] })];
    render(<EmbedsPanel agentId="a-1" canManage />);

    expect(screen.getByText(/cannot open anywhere/)).toBeInTheDocument();
  });

  it("marks a paused embed and pauses a live one", async () => {
    state.embeds = [embed()];
    render(<EmbedsPanel agentId="a-1" canManage />);

    await userEvent.click(screen.getByRole("switch", { name: "Pause Website widget" }));

    expect(state.update.mutate).toHaveBeenCalledWith({ id: "e-1", is_active: false });
  });

  it("warns that removal is immediate and the key cannot come back", async () => {
    state.embeds = [embed()];
    render(<EmbedsPanel agentId="a-1" canManage />);

    await userEvent.click(screen.getByRole("button", { name: "Remove Website widget" }));

    // `ConfirmDialog` is built on Radix's Dialog, not AlertDialog.
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/stops working immediately/)).toBeInTheDocument();
    expect(within(dialog).getByText(/cannot be reissued/)).toBeInTheDocument();
  });

  it("removes the embed once the warning is accepted", async () => {
    state.embeds = [embed()];
    render(<EmbedsPanel agentId="a-1" canManage />);

    await userEvent.click(screen.getByRole("button", { name: "Remove Website widget" }));
    // Anchored: the dialog's confirm button is named exactly "Remove", and the
    // card's trigger behind it is "Remove Website widget".
    await userEvent.click(screen.getByRole("button", { name: /^Remove$/ }));

    expect(state.remove.mutateAsync).toHaveBeenCalledWith("e-1");
  });
});

describe("a row shows the integrations its kind actually has", () => {
  it("gives a page a link and neither a script tag nor a socket", () => {
    // A script tag shown beside a link is a line somebody would paste, and it
    // would never work: a page has no allow-list to admit a third-party site.
    state.embeds = [page()];
    render(<EmbedsPanel agentId="a-1" canManage />);

    expect(screen.getByText("https://chat.test/e/pk_live_abc")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy the snippet" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Copy the socket URL" })).toBeNull();
  });

  it("says what protects a link, because it is only the key", () => {
    state.embeds = [page()];
    render(<EmbedsPanel agentId="a-1" canManage />);

    expect(screen.getByText(/Anyone with the link can talk to this agent/)).toBeInTheDocument();
  });

  it("shows a page no allow-list at all, rather than an empty one reading as broken", () => {
    state.embeds = [page()];
    render(<EmbedsPanel agentId="a-1" canManage />);

    expect(screen.queryByText(/cannot open anywhere/)).toBeNull();
  });

  it("gives a socket integration the socket and no script tag", () => {
    state.embeds = [
      embed({ name: "Kiosk", kind: "socket", config: { kind: "socket" }, snippet: null }),
    ];
    render(<EmbedsPanel agentId="a-1" canManage />);

    expect(screen.getByRole("button", { name: "Copy the socket URL" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy the snippet" })).toBeNull();
  });

  it("names the surface on the row, so a list of three is readable", () => {
    state.embeds = [embed(), page({ id: "e-2" })];
    render(<EmbedsPanel agentId="a-1" canManage />);

    // The card grid is hidden while rows exist only if a surface is being
    // configured; here both the badges and the cards carry these names, so the
    // count is what distinguishes a badge from its card.
    expect(screen.getAllByText("Website widget").length).toBeGreaterThan(1);
    expect(screen.getAllByText("Hosted page").length).toBeGreaterThan(1);
  });
});

describe("publishing a widget", () => {
  it("refuses to publish with no site allowed, and says why", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("widget");

    expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
    expect(screen.getByText(/a widget allowed nowhere cannot open/)).toBeInTheDocument();
  });

  it("refuses to publish without a name", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("widget");

    await userEvent.type(screen.getByLabelText("Allowed sites"), "https://acme.com");
    await userEvent.clear(screen.getByLabelText("Name"));

    expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
  });

  it("splits the origin list on newlines and commas, trimming as it goes", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("widget");

    await userEvent.type(
      screen.getByLabelText("Allowed sites"),
      " https://acme.com , {enter} https://www.acme.com {enter}{enter}",
    );
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));

    expect(state.create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ allowed_origins: ["https://acme.com", "https://www.acme.com"] }),
      expect.anything(),
    );
  });

  it("sends a widget config, tagged so the backend knows which surface it is", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("widget");

    await userEvent.type(screen.getByLabelText("Allowed sites"), "https://acme.com");
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));

    const [payload] = state.create.mutate.mock.calls.at(-1)!;
    expect(payload.config.kind).toBe("widget");
    expect(payload.auth_mode).toBe("public");
    expect(payload.jwt_secret).toBeNull();
  });

  it("asks for a signing secret only once sign-in is required", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("widget");

    expect(screen.queryByLabelText("Signing secret")).toBeNull();

    await userEvent.click(screen.getByLabelText("Who can use it"));
    await userEvent.click(screen.getByRole("option", { name: /Signed-in users only/ }));

    expect(screen.getByLabelText("Signing secret")).toBeInTheDocument();
  });

  it("refuses a signing secret too short for the backend to accept", async () => {
    // Sent, it comes back a 422 naming a field the form could have named first.
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("widget");

    await userEvent.type(screen.getByLabelText("Allowed sites"), "https://acme.com");
    await userEvent.click(screen.getByLabelText("Who can use it"));
    await userEvent.click(screen.getByRole("option", { name: /Signed-in users only/ }));
    await userEvent.type(screen.getByLabelText("Signing secret"), "short");

    expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
  });

  it("sends the secret with a jwt widget", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("widget");

    await userEvent.type(screen.getByLabelText("Allowed sites"), "https://acme.com");
    await userEvent.click(screen.getByLabelText("Who can use it"));
    await userEvent.click(screen.getByRole("option", { name: /Signed-in users only/ }));
    await userEvent.type(screen.getByLabelText("Signing secret"), "a-very-long-secret");
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));

    expect(state.create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ auth_mode: "jwt", jwt_secret: "a-very-long-secret" }),
      expect.anything(),
    );
  });

  it("sends per-placement context as null when it is left blank", async () => {
    // `""` would be prepended to every first message as an empty instruction.
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("widget");

    await userEvent.type(screen.getByLabelText("Allowed sites"), "https://acme.com");
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));

    expect(state.create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ context: null }),
      expect.anything(),
    );
  });

  it("takes the accent from the swatch as well as from the field", async () => {
    // Two controls, one value: a colour picked from the swatch and a hex typed
    // into the field have to reach the same place.
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("widget");

    const swatch = document.getElementById("embed-accent") as HTMLInputElement;
    fireEvent.change(swatch, { target: { value: "#00ff00" } });
    await userEvent.type(screen.getByLabelText("Allowed sites"), "https://acme.com");
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));

    const [payload] = state.create.mutate.mock.calls.at(-1)!;
    expect(payload.config.accent).toBe("#00ff00");
  });

  it("abandons the form on cancel", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("widget");

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByLabelText("Allowed sites")).toBeNull();
    expect(state.create.mutate).not.toHaveBeenCalled();
  });
});

describe("publishing a hosted page", () => {
  it("publishes with no site named at all", async () => {
    // The defect this rebuild fixes. The shortest integration this product has is
    // "send somebody a link", and the form refused it without an allowed site -
    // a field that means nothing on a page we serve ourselves.
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("page");

    expect(screen.queryByLabelText("Allowed sites")).toBeNull();
    expect(screen.getByRole("button", { name: "Publish" })).toBeEnabled();

    await userEvent.click(screen.getByRole("button", { name: "Publish" }));

    const [payload] = state.create.mutate.mock.calls.at(-1)!;
    expect(payload.config.kind).toBe("page");
    expect(payload.allowed_origins).toEqual([]);
  });

  it("offers no token auth, because the token would travel in the URL", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("page");

    expect(screen.queryByLabelText("Who can use it")).toBeNull();
  });

  it("says what protects the link before it is published, not after", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("page");

    expect(screen.getByText(/Anyone with the link can talk to this agent/)).toBeInTheDocument();
  });

  it("carries the page's own branding rather than a widget's", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("page");

    await userEvent.type(screen.getByLabelText("Page title"), "Refunds");
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));

    const [payload] = state.create.mutate.mock.calls.at(-1)!;
    expect(payload.config).toMatchObject({ kind: "page", title: "Refunds", logo: "agent" });
  });

  it("warns about a required variable its own URL cannot fill", async () => {
    // The backend refuses this combination; meeting the refusal after filling in
    // a form is the experience showing the reason here exists to prevent.
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("page");

    await userEvent.click(screen.getByRole("button", { name: "Add a variable" }));
    await userEvent.type(screen.getByLabelText("Variable 1 name"), "plan");
    await userEvent.click(screen.getByRole("checkbox", { name: "Required" }));

    expect(screen.getByText(/Required and not URL-safe: plan/)).toBeInTheDocument();
  });
});

describe("publishing a raw socket", () => {
  it("asks for the origins that admit a handshake and nothing to style", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("socket");

    expect(screen.getByLabelText("Allowed sites")).toBeInTheDocument();
    expect(document.getElementById("embed-accent")).toBeNull();
  });

  it("says a client of one's own sends no Origin unless it sets one", async () => {
    // The first thing that goes wrong, and what 4003 looks like when it does.
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("socket");

    expect(screen.getByText(/sends nothing unless you set it/)).toBeInTheDocument();
  });

  it("sends a socket config with no styling in it", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("socket");

    await userEvent.type(screen.getByLabelText("Allowed sites"), "https://acme.com");
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));

    const [payload] = state.create.mutate.mock.calls.at(-1)!;
    expect(payload.config).toEqual({ kind: "socket" });
  });
});

describe("what the integration must supply", () => {
  it("declares a variable with the embed", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("widget");

    await userEvent.type(screen.getByLabelText("Allowed sites"), "https://acme.test");
    await userEvent.click(screen.getByRole("button", { name: "Add a variable" }));
    await userEvent.type(screen.getByLabelText("Variable 1 name"), "plan");
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));

    expect(state.create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        context_variables: [{ name: "plan", required: false, description: "", url_safe: false }],
      }),
      expect.anything(),
    );
  });

  it("corrects a name to the shape the backend accepts as it is typed", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("widget");

    await userEvent.click(screen.getByRole("button", { name: "Add a variable" }));
    await userEvent.type(screen.getByLabelText("Variable 1 name"), "Plan Name");

    expect(screen.getByLabelText("Variable 1 name")).toHaveValue("plan_name");
  });

  it("does not declare a row somebody started and left blank", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("widget");

    await userEvent.type(screen.getByLabelText("Allowed sites"), "https://acme.test");
    await userEvent.click(screen.getByRole("button", { name: "Add a variable" }));
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));

    expect(state.create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ context_variables: [] }),
      expect.anything(),
    );
  });

  it("offers URL-safe on a page and nowhere else", async () => {
    // `url_safe` is about a URL. A widget reads `window.AgenticOSContext` from a
    // page the operator controls, so the control would mean nothing there.
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("widget");
    await userEvent.click(screen.getByRole("button", { name: "Add a variable" }));

    expect(screen.queryByRole("checkbox", { name: "URL-safe" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await pick("page");
    await userEvent.click(screen.getByRole("button", { name: "Add a variable" }));
    await userEvent.type(screen.getByLabelText("Variable 1 name"), "plan");
    await userEvent.click(screen.getByRole("checkbox", { name: "URL-safe" }));
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));

    expect(state.create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        context_variables: [{ name: "plan", required: false, description: "", url_safe: true }],
      }),
      expect.anything(),
    );
  });

  it("takes a declared variable away again", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await pick("widget");

    await userEvent.click(screen.getByRole("button", { name: "Add a variable" }));
    await userEvent.type(screen.getByLabelText("Variable 1 name"), "plan");
    await userEvent.click(screen.getByRole("button", { name: "Remove plan" }));

    expect(screen.queryByLabelText("Variable 1 name")).toBeNull();
  });
});
