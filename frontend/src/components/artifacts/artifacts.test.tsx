import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AgentFilter } from "./agent-filter";
import { ArtifactCard } from "./artifact-card";
import {
  ARTIFACT_SANDBOX,
  ArtifactFrame,
  ArtifactFrameView,
  requestedLink,
} from "./artifact-frame";
import { PublicArtifact } from "./public-artifact";
import { PublicLinkCard } from "./public-link-card";
import {
  EmbedSnippet,
  PublicLinkSettings,
  endOfDay,
  localDate,
  originLines,
} from "./public-link-settings";
import { VersionPicker } from "./version-picker";
import { ApiError } from "@/lib/api-error";
import type { Artifact, ArtifactPublicLink, ArtifactVersion } from "@/types/artifact";

const useArtifactViewMock = vi.fn();
const unlockMock = vi.fn();
vi.mock("@/hooks/use-artifacts", () => ({
  useArtifactView: (...args: unknown[]) => useArtifactViewMock(...args),
  usePublicArtifactUnlock: () => unlockMock(),
}));
const toastError = vi.fn();
vi.mock("sonner", () => ({ toast: { error: (...args: unknown[]) => toastError(...args) } }));

function version(number: number, overrides: Partial<ArtifactVersion> = {}): ArtifactVersion {
  return {
    id: `v${number}`,
    number,
    media_type: "text/html",
    size_bytes: 10,
    run_id: null,
    created_at: "2026-09-22T10:00:00Z",
    ...overrides,
  };
}

function artifact(overrides: Partial<Artifact> = {}): Artifact {
  return {
    id: "a1",
    name: "weekly-report",
    title: "Weekly report",
    visibility: "private",
    owner_user_id: "u1",
    agent_id: "ag1",
    environment_id: null,
    environment_name: null,
    public_url: null,
    published_at: "2026-09-22T10:00:00Z",
    current_version: version(3),
    created_at: "2026-09-01T10:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

function link(overrides: Partial<ArtifactPublicLink> = {}): ArtifactPublicLink {
  return {
    expires_at: null,
    pinned_version_id: null,
    pinned_version: null,
    password_protected: false,
    view_count: 0,
    last_viewed_at: null,
    embed_origins: [],
    embed_url: null,
    ...overrides,
  };
}

/** A message as the framed page's platform script would post it. */
function postFromFrame(frame: HTMLIFrameElement, data: unknown) {
  act(() => {
    window.dispatchEvent(new MessageEvent("message", { data, source: frame.contentWindow }));
  });
}

describe("the frame", () => {
  beforeEach(() => vi.clearAllMocks());

  it("never grants the page this console's origin", () => {
    render(
      <ArtifactFrameView url="https://api.example/api/v1/artifact-content/t" title="Report" />,
    );
    const frame = screen.getByTitle("Report");
    expect(frame.getAttribute("sandbox")).toBe(ARTIFACT_SANDBOX);
    expect(ARTIFACT_SANDBOX).not.toContain("allow-same-origin");
    expect(ARTIFACT_SANDBOX).not.toContain("allow-top-navigation");
    // A popup is a navigation, which no `connect-src` governs - a way out.
    expect(ARTIFACT_SANDBOX).not.toContain("allow-popups");
    expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(frame.getAttribute("src")).toBe("https://api.example/api/v1/artifact-content/t");
  });

  it("loads the version asked for from a fresh address", () => {
    useArtifactViewMock.mockReturnValue({ isLoading: false, data: { url: "https://x/c/t" } });
    render(<ArtifactFrame artifactId="a1" versionId="v2" title="Report" />);
    expect(useArtifactViewMock).toHaveBeenCalledWith("a1", "v2", true);
    expect(screen.getByTitle("Report").getAttribute("src")).toBe("https://x/c/t");
  });

  it("says a pruned or withdrawn version is not available", () => {
    useArtifactViewMock.mockReturnValue({ isLoading: false, data: undefined });
    render(<ArtifactFrame artifactId="a1" versionId="gone" title="Report" />);
    expect(screen.getByText("This version is not available")).toBeInTheDocument();
    expect(screen.queryByTitle("Report")).toBeNull();
  });

  it("shows a skeleton while the address is minted", () => {
    useArtifactViewMock.mockReturnValue({ isLoading: true, data: undefined });
    const { container } = render(<ArtifactFrame artifactId="a1" versionId={null} title="R" />);
    expect(container.querySelector("iframe")).toBeNull();
  });
});

describe("a link inside the page", () => {
  afterEach(() => vi.restoreAllMocks());

  it("opens in a new tab only after a person reads the address and agrees", async () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    render(<ArtifactFrameView url="https://api/c/t" title="Report" />);
    const frame = screen.getByTitle("Report") as HTMLIFrameElement;

    postFromFrame(frame, { type: "agenticos:open-link", href: "https://docs.example.com/q3" });
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("https://docs.example.com/q3")).toBeInTheDocument();
    expect(open).not.toHaveBeenCalled();

    await userEvent.click(within(dialog).getByRole("button", { name: "Open link" }));
    expect(open).toHaveBeenCalledWith(
      "https://docs.example.com/q3",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("keeps the address the person is reading while the page posts another", async () => {
    // A page may keep posting; taking the newest would swap the address being
    // checked for one the reader never saw, just before the click.
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    render(<ArtifactFrameView url="https://api/c/t" title="Report" />);
    const frame = screen.getByTitle("Report") as HTMLIFrameElement;

    postFromFrame(frame, { type: "agenticos:open-link", href: "https://docs.example.com/q3" });
    const dialog = await screen.findByRole("dialog");
    postFromFrame(frame, { type: "agenticos:open-link", href: "https://evil.example/leak" });

    expect(within(dialog).getByText("https://docs.example.com/q3")).toBeInTheDocument();
    expect(within(dialog).queryByText("https://evil.example/leak")).toBeNull();
    await userEvent.click(within(dialog).getByRole("button", { name: "Open link" }));
    expect(open).toHaveBeenCalledWith(
      "https://docs.example.com/q3",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("opens nothing when the person cancels", async () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    render(<ArtifactFrameView url="https://api/c/t" title="Report" />);
    postFromFrame(screen.getByTitle("Report") as HTMLIFrameElement, {
      type: "agenticos:open-link",
      href: "https://docs.example.com/",
    });
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(open).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("asks nothing for a message from any other window", () => {
    render(<ArtifactFrameView url="https://api/c/t" title="Report" />);
    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { type: "agenticos:open-link", href: "https://evil.example/" },
          source: window,
        }),
      );
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("what counts as a link request", () => {
  const frame = { contentWindow: window } as unknown as HTMLIFrameElement;
  const message = (data: unknown, source: unknown = window) =>
    new MessageEvent("message", { data, source: source as Window });

  it("takes an http or https address from the frame's own window", () => {
    expect(
      requestedLink(message({ type: "agenticos:open-link", href: "http://a.example/" }), frame),
    ).toBe("http://a.example/");
  });

  it.each([
    ["no frame", { type: "agenticos:open-link", href: "https://a/" }, null],
    ["not an object", "https://a/", frame],
    ["null", null, frame],
    ["another type", { type: "other", href: "https://a/" }, frame],
    ["no address", { type: "agenticos:open-link" }, frame],
    ["a script address", { type: "agenticos:open-link", href: "javascript:alert(1)" }, frame],
    ["not an address", { type: "agenticos:open-link", href: "::::" }, frame],
  ])("refuses %s", (_label, data, target) => {
    expect(requestedLink(message(data), target as HTMLIFrameElement | null)).toBeNull();
  });
});

describe("the list card", () => {
  it("says who else can read it", () => {
    useArtifactViewMock.mockReturnValue({ isLoading: false, data: undefined });
    render(
      <ArtifactCard artifact={artifact({ visibility: "org", public_url: "https://x/a/k" })} />,
    );
    expect(screen.getByText("Whole organization")).toBeInTheDocument();
    expect(screen.getByText("Public link")).toBeInTheDocument();
    expect(screen.getByRole("link").getAttribute("href")).toBe("/artifacts/a1");
    expect(screen.getByText(/Version 3/)).toBeInTheDocument();
  });

  it("stacks one sheet per earlier version and names the version on the page", () => {
    useArtifactViewMock.mockReturnValue({ isLoading: false, data: undefined });
    const { container } = render(<ArtifactCard artifact={artifact()} />);

    expect(container.querySelectorAll(".peek-sheet")).toHaveLength(2);
    expect(screen.getByText("v3")).toBeInTheDocument();
  });

  it("shows no reach badge for a private page", () => {
    render(<ArtifactCard artifact={artifact({ current_version: null })} />);
    expect(screen.queryByText("Whole organization")).toBeNull();
    expect(screen.queryByText("Public link")).toBeNull();
    expect(screen.getByText(/Version 0/)).toBeInTheDocument();
  });

  it("names the environment a page was published from, when it is not the default", () => {
    render(
      <ArtifactCard artifact={artifact({ current_version: null, environment_name: "staging" })} />,
    );
    expect(screen.getByText("staging")).toHaveAttribute("title", "Published from this environment");
  });
});

describe("the public link card", () => {
  it("offers a manager a link to create when there is none", async () => {
    const onEnable = vi.fn();
    render(
      <PublicLinkCard
        publicUrl={null}
        link={link()}
        canManage
        busy={false}
        onEnable={onEnable}
        onDisable={vi.fn()}
      />,
    );
    expect(
      screen.getByText("Only people this artifact is shared with can open it."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Opened|Not opened/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Create a public link" }));
    expect(onEnable).toHaveBeenCalled();
  });

  it("lets a manager replace or turn off a live link", async () => {
    const onEnable = vi.fn();
    const onDisable = vi.fn();
    render(
      <PublicLinkCard
        publicUrl="https://console.example/a/key"
        link={link()}
        canManage
        busy={false}
        onEnable={onEnable}
        onDisable={onDisable}
      />,
    );
    expect(screen.getByLabelText("Public link")).toHaveValue("https://console.example/a/key");
    expect(screen.getByText("Not opened yet")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Replace the link" }));
    await userEvent.click(screen.getByRole("button", { name: "Turn off" }));
    expect(onEnable).toHaveBeenCalled();
    expect(onDisable).toHaveBeenCalled();
  });

  it("shows a reader the link, how often it was opened, and nothing to press", () => {
    render(
      <PublicLinkCard
        publicUrl="https://console.example/a/key"
        link={link({ view_count: 4, last_viewed_at: "2026-09-29T10:00:00Z" })}
        canManage={false}
        busy={false}
        onEnable={vi.fn()}
        onDisable={vi.fn()}
      />,
    );
    expect(screen.getByText(/Opened 4 times, last/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Turn off" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Replace the link" })).toBeNull();
  });
});

describe("the version picker", () => {
  it("is not drawn for a page with one version and nothing pinned", () => {
    const { container } = render(
      <VersionPicker versions={[version(1)]} value={null} onChange={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("pins a version and goes back to following the latest", async () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <VersionPicker versions={[version(2), version(1)]} value={null} onChange={onChange} />,
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Version" }));
    await userEvent.click(screen.getByRole("option", { name: /Version 1/ }));
    expect(onChange).toHaveBeenLastCalledWith("v1");

    rerender(<VersionPicker versions={[version(2), version(1)]} value="v1" onChange={onChange} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Version" }));
    await userEvent.click(screen.getByRole("option", { name: "Latest version" }));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });
});

describe("the agent filter", () => {
  const agents = [
    { id: "ag1", name: "Reporter" },
    { id: "ag2", name: "Analyst" },
  ];

  it("is not drawn with one publisher and no filter on", () => {
    const { container } = render(
      <AgentFilter agents={agents.slice(0, 1)} value={null} onChange={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("narrows to one agent and back to every agent", async () => {
    const onChange = vi.fn();
    const { rerender } = render(<AgentFilter agents={agents} value={null} onChange={onChange} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Filter by agent" }));
    await userEvent.click(screen.getByRole("option", { name: "Analyst" }));
    expect(onChange).toHaveBeenLastCalledWith("ag2");

    rerender(<AgentFilter agents={[]} value="ag2" onChange={onChange} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Filter by agent" }));
    await userEvent.click(screen.getByRole("option", { name: "Every agent" }));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });
});

describe("the public link settings", () => {
  beforeEach(() => vi.clearAllMocks());

  function renderSettings(
    overrides: Partial<ArtifactPublicLink> = {},
    onSave = vi.fn().mockResolvedValue(undefined),
  ) {
    render(
      <PublicLinkSettings
        link={link(overrides)}
        versions={[version(2), version(1)]}
        saving={false}
        onSave={onSave}
      />,
    );
    return onSave;
  }

  it("saves the expiry, the pinned version and the embedding sites together", async () => {
    const onSave = renderSettings();
    fireEvent.change(screen.getByLabelText("Stops opening after"), {
      target: { value: "2026-10-14" },
    });
    await userEvent.click(screen.getByRole("combobox", { name: "Shows" }));
    await userEvent.click(screen.getByRole("option", { name: "v1" }));
    await userEvent.type(
      screen.getByLabelText("Sites that may embed it"),
      "https://a.example.com{enter}{enter} https://b.example.com ",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save link settings" }));

    expect(onSave).toHaveBeenCalledWith({
      expires_at: endOfDay("2026-10-14"),
      pinned_version_id: "v1",
      embed_origins: ["https://a.example.com", "https://b.example.com"],
    });
  });

  it("clears what was set when the fields are emptied", async () => {
    const onSave = renderSettings({ expires_at: "2026-10-14T21:59:59Z", pinned_version_id: "v2" });
    fireEvent.change(screen.getByLabelText("Stops opening after"), { target: { value: "" } });
    await userEvent.click(screen.getByRole("combobox", { name: "Shows" }));
    await userEvent.click(screen.getByRole("option", { name: "Latest version" }));
    await userEvent.click(screen.getByRole("button", { name: "Save link settings" }));
    expect(onSave).toHaveBeenCalledWith({
      expires_at: null,
      pinned_version_id: null,
      embed_origins: [],
    });
  });

  it("shows a refusal under the field it names, not in a toast", async () => {
    const refusal = new ApiError(400, "Bad", {
      error: {
        code: "BAD_REQUEST",
        message: "Bad",
        details: { fields: [{ field: "embed_origins", message: "Not a site origin." }] },
      },
    });
    renderSettings({}, vi.fn().mockRejectedValue(refusal));
    await userEvent.click(screen.getByRole("button", { name: "Save link settings" }));
    expect(await screen.findByText("Not a site origin.")).toBeInTheDocument();
    expect(toastError).not.toHaveBeenCalled();
  });

  it("toasts a failure that names no field", async () => {
    renderSettings({}, vi.fn().mockRejectedValue(new ApiError(503, "Down")));
    await userEvent.click(screen.getByRole("button", { name: "Save link settings" }));
    expect(toastError).toHaveBeenCalled();
  });

  it("sets a password, and forgets what was typed once it is saved", async () => {
    const onSave = renderSettings();
    expect(screen.getByRole("button", { name: "Set password" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Password"), "hunter22");
    await userEvent.click(screen.getByRole("button", { name: "Set password" }));
    expect(onSave).toHaveBeenCalledWith({ password: "hunter22" });
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.queryByRole("button", { name: "Remove password" })).toBeNull();
  });

  it("keeps what was typed when the password is refused", async () => {
    const refusal = new ApiError(422, "Short", {
      detail: [{ loc: ["body", "password"], msg: "Too short", type: "string_too_short" }],
    });
    renderSettings({}, vi.fn().mockRejectedValue(refusal));
    await userEvent.type(screen.getByLabelText("Password"), "abc");
    await userEvent.click(screen.getByRole("button", { name: "Set password" }));
    expect(screen.getByLabelText("Password")).toHaveValue("abc");
  });

  it("changes or removes a password that is set, and says an embed needs none", async () => {
    const onSave = renderSettings({ password_protected: true });
    expect(screen.getByText(/cannot be embedded/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change password" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remove password" }));
    expect(onSave).toHaveBeenCalledWith({ password: null });
  });
});

describe("the embed code", () => {
  it.each([
    ["the link is off", link({ embed_origins: ["https://a.example.com"] })],
    ["no site may embed it", link({ embed_url: "https://api/e/k" })],
    [
      "it asks for a password",
      link({
        embed_url: "https://api/e/k",
        embed_origins: ["https://a"],
        password_protected: true,
      }),
    ],
  ])("is not offered when %s", (_label, settings) => {
    const { container } = render(<EmbedSnippet link={settings} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("is an iframe of the embed address", () => {
    render(
      <EmbedSnippet link={link({ embed_url: "https://api/e/k", embed_origins: ["https://a"] })} />,
    );
    expect(screen.getByText(/<iframe src="https:\/\/api\/e\/k"/)).toBeInTheDocument();
  });
});

describe("the settings' helpers", () => {
  it("reads a stored expiry as the reader's date and writes the end of that day", () => {
    const stored = endOfDay("2026-10-14");
    expect(stored).not.toBeNull();
    expect(localDate(stored)).toBe("2026-10-14");
    expect(localDate(null)).toBe("");
    expect(endOfDay("")).toBeNull();
  });

  it("reads one site per line and drops the blanks", () => {
    expect(originLines(" https://a \n\n https://b\n")).toEqual(["https://a", "https://b"]);
  });
});

describe("the public page", () => {
  beforeEach(() => vi.clearAllMocks());

  const opened = {
    password_required: false as const,
    title: "Weekly report",
    published_at: "2026-09-22T10:00:00Z",
    view: { url: "https://api/c/t", expires_at: "", version: version(3) },
  };
  const locked = {
    password_required: true as const,
    title: null,
    published_at: null,
    view: null,
  };

  it("shows the page and when it was published, and nothing about who made it", () => {
    render(<PublicArtifact artifact={opened} publicKey="k" />);
    expect(screen.getByRole("heading", { name: "Weekly report" })).toBeInTheDocument();
    expect(screen.getByText(/Updated/)).toBeInTheDocument();
    expect(screen.getByTitle("Weekly report").getAttribute("src")).toBe("https://api/c/t");
  });

  it("asks for the password first and says nothing else about the page", async () => {
    const mutate = vi.fn();
    unlockMock.mockReturnValue({ mutate, data: undefined, error: null, isPending: false });
    render(<PublicArtifact artifact={locked} publicKey="k" />);

    expect(screen.getByRole("heading", { name: "This page is protected" })).toBeInTheDocument();
    expect(screen.queryByText("Weekly report")).toBeNull();
    expect(screen.getByRole("button", { name: "Open the page" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Password"), "hunter22{enter}");
    expect(mutate).toHaveBeenCalledWith("hunter22");
  });

  it("says a wrong password in the form", () => {
    unlockMock.mockReturnValue({
      mutate: vi.fn(),
      data: undefined,
      error: new ApiError(403, "That password is not right."),
      isPending: false,
    });
    render(<PublicArtifact artifact={locked} publicKey="k" />);
    expect(screen.getByText("That password is not right.")).toBeInTheDocument();
  });

  it("says any other failure as the failure it was", () => {
    unlockMock.mockReturnValue({
      mutate: vi.fn(),
      data: undefined,
      error: new ApiError(429, "Too many requests. Try again shortly."),
      isPending: false,
    });
    render(<PublicArtifact artifact={locked} publicKey="k" />);
    expect(screen.getByText(/Too many requests|too many/i)).toBeInTheDocument();
  });

  it("shows the page once the password was right", () => {
    unlockMock.mockReturnValue({ mutate: vi.fn(), data: opened, error: null, isPending: false });
    render(<PublicArtifact artifact={locked} publicKey="k" />);
    expect(screen.getByTitle("Weekly report")).toBeInTheDocument();
  });
});
