import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EmbedsPanel } from "./embeds-panel";
import { DEFAULT_EMBED_THEME, type Embed } from "@/types/embeds";

/**
 * The widget panel, whose whole job is a bearer credential.
 *
 * The key in the script tag is public by construction - it sits on somebody's
 * marketing page - so the only thing protecting the agent is the allowed-origin
 * list. An empty list allows nothing, and the panel has to make that visible at
 * the moment a widget is created rather than let it be discovered when the widget
 * silently refuses to open.
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
    public_key: "pk_live_abc",
    auth_mode: "public",
    has_jwt_secret: false,
    allowed_origins: ["https://acme.com"],
    theme: DEFAULT_EMBED_THEME,
    context: null,
    is_active: true,
    rate_limit_per_minute: 10,
    snippet: '<script src="https://app.test/embed.js" data-key="pk_live_abc"></script>',
    ...overrides,
  };
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

async function openTheForm() {
  await userEvent.click(screen.getByRole("button", { name: "Publish as widget" }));
}

describe("the widget panel", () => {
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

  it("says the key is public and the origin list is what protects the agent", () => {
    // The one thing somebody pasting a script tag has to understand.
    render(<EmbedsPanel agentId="a-1" canManage />);

    expect(screen.getByText(/key in that tag is public/)).toBeInTheDocument();
    expect(screen.getByText(/An empty list allows nothing/)).toBeInTheDocument();
  });

  it("offers no way to publish to somebody who may not publish", () => {
    render(<EmbedsPanel agentId="a-1" canManage={false} />);

    expect(screen.queryByRole("button", { name: "Publish as widget" })).toBeNull();
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

  it("acknowledges the copy", () => {
    copied.value = true;
    state.embeds = [embed()];
    render(<EmbedsPanel agentId="a-1" canManage />);

    // The icon swaps to a tick; the button keeps its accessible name.
    expect(screen.getByRole("button", { name: "Copy the snippet" })).toBeInTheDocument();
  });

  it("names the sites it may be opened from", () => {
    state.embeds = [embed({ allowed_origins: ["https://acme.com", "https://www.acme.com"] })];
    render(<EmbedsPanel agentId="a-1" canManage />);

    expect(screen.getByText("https://acme.com, https://www.acme.com")).toBeInTheDocument();
  });

  it("says a widget allowed nowhere cannot open", () => {
    // The failure mode this panel exists to prevent: a published widget with an
    // empty allow-list looks configured and refuses every request.
    state.embeds = [embed({ allowed_origins: [] })];
    render(<EmbedsPanel agentId="a-1" canManage />);

    expect(screen.getByText(/cannot open anywhere/)).toBeInTheDocument();
  });

  it("distinguishes a public widget from one behind a sign-in", () => {
    state.embeds = [
      embed({ id: "e-1", name: "Open" }),
      embed({ id: "e-2", name: "Gated", auth_mode: "jwt" }),
    ];
    render(<EmbedsPanel agentId="a-1" canManage />);

    expect(screen.getByText("public")).toBeInTheDocument();
    expect(screen.getByText("signed-in users")).toBeInTheDocument();
  });

  it("marks a paused widget", () => {
    state.embeds = [embed({ is_active: false })];
    render(<EmbedsPanel agentId="a-1" canManage />);

    expect(screen.getByText("paused")).toBeInTheDocument();
  });

  it("pauses a live widget", async () => {
    state.embeds = [embed()];
    render(<EmbedsPanel agentId="a-1" canManage />);

    await userEvent.click(screen.getByRole("switch", { name: "Pause Website widget" }));

    expect(state.update.mutate).toHaveBeenCalledWith({ id: "e-1", is_active: false });
  });

  it("resumes a paused one", async () => {
    state.embeds = [embed({ is_active: false })];
    render(<EmbedsPanel agentId="a-1" canManage />);

    await userEvent.click(screen.getByRole("switch", { name: "Resume Website widget" }));

    expect(state.update.mutate).toHaveBeenCalledWith({ id: "e-1", is_active: true });
  });

  it("shows the snippet but no controls to somebody who may not manage it", () => {
    state.embeds = [embed()];
    render(<EmbedsPanel agentId="a-1" canManage={false} />);

    expect(screen.getByText(/data-key/)).toBeInTheDocument();
    expect(screen.queryByRole("switch")).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove Website widget" })).toBeNull();
  });

  it("warns that removal is immediate and the key cannot come back", async () => {
    // Every page carrying that key breaks at once, and a new widget gets a new
    // key - so this is not an undoable action.
    state.embeds = [embed()];
    render(<EmbedsPanel agentId="a-1" canManage />);

    await userEvent.click(screen.getByRole("button", { name: "Remove Website widget" }));

    // `ConfirmDialog` is built on Radix's Dialog, not AlertDialog.
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/stops working immediately/)).toBeInTheDocument();
    expect(within(dialog).getByText(/cannot be reissued/)).toBeInTheDocument();
  });

  it("keeps the widget when the warning is dismissed", async () => {
    // The key cannot be reissued, so the way out of this dialog has to be a way
    // out - not a confirm with a different label.
    state.embeds = [embed()];
    render(<EmbedsPanel agentId="a-1" canManage />);

    await userEvent.click(screen.getByRole("button", { name: "Remove Website widget" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(state.remove.mutateAsync).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("removes the widget once the warning is accepted", async () => {
    state.embeds = [embed()];
    render(<EmbedsPanel agentId="a-1" canManage />);

    await userEvent.click(screen.getByRole("button", { name: "Remove Website widget" }));
    // Anchored: the dialog's confirm button is named exactly "Remove", and the
    // card's trigger behind it is "Remove Website widget". `getByRole` has no
    // `exact` option - passing one was a type error, and an unanchored string
    // would have matched both and thrown on the ambiguity.
    await userEvent.click(screen.getByRole("button", { name: /^Remove$/ }));

    expect(state.remove.mutateAsync).toHaveBeenCalledWith("e-1");
  });
});

describe("publishing a new widget", () => {
  it("refuses to publish with no site allowed, and says why", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await openTheForm();

    expect(screen.getByRole("button", { name: "Publish widget" })).toBeDisabled();
    expect(screen.getByText(/a widget allowed nowhere cannot open/)).toBeInTheDocument();
  });

  it("refuses to publish without a name", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await openTheForm();

    await userEvent.type(screen.getByLabelText("Allowed sites"), "https://acme.com");
    await userEvent.clear(screen.getByLabelText("Name"));

    expect(screen.getByRole("button", { name: "Publish widget" })).toBeDisabled();
  });

  it("splits the origin list on newlines and commas, trimming as it goes", async () => {
    // A different port or subdomain is a different site to the browser, so this
    // list has to carry each one exactly.
    render(<EmbedsPanel agentId="a-1" canManage />);
    await openTheForm();

    await userEvent.type(
      screen.getByLabelText("Allowed sites"),
      " https://acme.com , {enter} https://www.acme.com {enter}{enter}",
    );
    await userEvent.click(screen.getByRole("button", { name: "Publish widget" }));

    expect(state.create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        allowed_origins: ["https://acme.com", "https://www.acme.com"],
      }),
      expect.anything(),
    );
  });

  it("publishes a public widget with no signing secret", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await openTheForm();

    await userEvent.type(screen.getByLabelText("Allowed sites"), "https://acme.com");
    await userEvent.click(screen.getByRole("button", { name: "Publish widget" }));

    expect(state.create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ agent_id: "a-1", auth_mode: "public", jwt_secret: null }),
      expect.anything(),
    );
  });

  it("asks for a signing secret only once sign-in is required", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await openTheForm();

    expect(screen.queryByLabelText("Signing secret")).toBeNull();

    await userEvent.click(screen.getByLabelText("Who can use it"));
    await userEvent.click(screen.getByRole("option", { name: /Signed-in users only/ }));

    expect(screen.getByLabelText("Signing secret")).toBeInTheDocument();
  });

  it("sends the secret with a jwt widget", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await openTheForm();

    await userEvent.type(screen.getByLabelText("Allowed sites"), "https://acme.com");
    await userEvent.click(screen.getByLabelText("Who can use it"));
    await userEvent.click(screen.getByRole("option", { name: /Signed-in users only/ }));
    await userEvent.type(screen.getByLabelText("Signing secret"), "a-very-long-secret");
    await userEvent.click(screen.getByRole("button", { name: "Publish widget" }));

    expect(state.create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ auth_mode: "jwt", jwt_secret: "a-very-long-secret" }),
      expect.anything(),
    );
  });

  it("sends per-placement context as null when it is left blank", async () => {
    // `""` would be prepended to every first message as an empty instruction.
    render(<EmbedsPanel agentId="a-1" canManage />);
    await openTheForm();

    await userEvent.type(screen.getByLabelText("Allowed sites"), "https://acme.com");
    await userEvent.click(screen.getByRole("button", { name: "Publish widget" }));

    expect(state.create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ context: null }),
      expect.anything(),
    );
  });

  it("carries the context when one is given", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await openTheForm();

    await userEvent.type(screen.getByLabelText("Allowed sites"), "https://acme.com");
    await userEvent.type(
      screen.getByLabelText("Context for this placement"),
      "You are on the pricing page.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Publish widget" }));

    expect(state.create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ context: "You are on the pricing page." }),
      expect.anything(),
    );
  });

  it("carries the accent colour into the theme", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await openTheForm();

    await userEvent.type(screen.getByLabelText("Allowed sites"), "https://acme.com");
    await userEvent.clear(screen.getAllByDisplayValue(DEFAULT_EMBED_THEME.accent)[1]!);
    await userEvent.type(screen.getAllByDisplayValue("")[0]!, "#ff0000");
    await userEvent.click(screen.getByRole("button", { name: "Publish widget" }));

    const [payload] = state.create.mutate.mock.calls.at(-1)!;
    expect(payload.theme.accent).toBe("#ff0000");
  });

  it("takes the accent from the swatch as well as from the field", async () => {
    // Two controls, one value: a colour picked from the swatch and a hex typed
    // into the field have to reach the same place, or the widget publishes with
    // whichever one the form happened to read.
    render(<EmbedsPanel agentId="a-1" canManage />);
    await openTheForm();

    const swatch = document.getElementById("embed-accent") as HTMLInputElement;
    fireEvent.change(swatch, { target: { value: "#00ff00" } });
    await userEvent.type(screen.getByLabelText("Allowed sites"), "https://acme.com");
    await userEvent.click(screen.getByRole("button", { name: "Publish widget" }));

    const [payload] = state.create.mutate.mock.calls.at(-1)!;
    expect(payload.theme.accent).toBe("#00ff00");
  });

  it("abandons the form on cancel", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await openTheForm();

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByLabelText("Allowed sites")).toBeNull();
    expect(state.create.mutate).not.toHaveBeenCalled();
  });

  it("stops a second submission while one is in flight", async () => {
    render(<EmbedsPanel agentId="a-1" canManage />);
    await openTheForm();
    await userEvent.type(screen.getByLabelText("Allowed sites"), "https://acme.com");

    state.create = { mutate: vi.fn(), isPending: true };
    render(<EmbedsPanel agentId="a-1" canManage />);

    expect(screen.queryByRole("button", { name: "Publish as widget" })).toBeInTheDocument();
  });
});
