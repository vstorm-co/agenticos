import { afterEach, describe, expect, it, vi } from "vitest";

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { CapabilityCatalogEntry } from "@/types/agents";

import { CAPABILITY_ART } from "./art.generated";
import { CapabilityArt, CapabilityCard } from "./capability-card";
import { CapabilityGallery, type CapabilityShelf } from "./capability-gallery";

const CHARTS: CapabilityCatalogEntry = {
  recommended: null,
  id: "charts",
  name: "Charts",
  category: "analysis",
  description: "Draw a chart so the user can see the numbers rather than read them.",
  side_effecting: false,
  scopes: [],
  tools: [{ id: "create_chart", name: "create_chart", description: "Draw a chart." }],
  contracts: [],
  config_schema: null,
  requires_secret: null,
};

const SANDBOX: CapabilityCatalogEntry = {
  ...CHARTS,
  id: "sandbox",
  name: "Sandbox",
  side_effecting: true,
  description: "Read, write and run things in a workspace.",
  tools: [],
};

const CLOCK: CapabilityCatalogEntry = {
  ...CHARTS,
  id: "clock",
  name: "Date and time",
  category: "utility",
  tools: [],
};

const BINDING = {
  id: "",
  config: {},
  approval: "default" as const,
  tool_approval: {},
  tool_overrides: {},
  secret_id: null,
  enabled: true,
};

/** Every capability the registry ships, each of which has a scene. */
const REGISTERED = [
  "artifacts",
  "ask_user",
  "browser_use",
  "channel_tools",
  "charts",
  "clock",
  "code_execution",
  "coding_agent",
  "compaction",
  "context",
  "conversation_search",
  "guardrails",
  "image_generation",
  "knowledge",
  "media",
  "memory_files",
  "memory_mem0",
  "planning",
  "sandbox",
  "skills",
  "subagents",
  "system_reminders",
  "thinking",
  "tool_output_limits",
  "tool_search",
  "web_fetch",
  "web_research",
];

afterEach(() => {
  vi.restoreAllMocks();
});

describe("the capability art", () => {
  it("draws every registered capability", () => {
    expect(Object.keys(CAPABILITY_ART).sort()).toEqual(REGISTERED);
  });

  it("renders the scene for a capability it has one for", () => {
    const { container } = render(<CapabilityArt id="charts" name="Charts" />);

    expect(container.querySelector(".v-B svg")).not.toBeNull();
    expect(container.querySelector(".cap-art")).not.toHaveClass("is-off");
  });

  it("falls back to an initial for a capability added after the art", () => {
    const { container } = render(<CapabilityArt id="teleport" name="Teleport" off />);

    expect(screen.getByText("T")).toBeInTheDocument();
    expect(container.querySelector(".cap-art")).toHaveClass("is-off");
    expect(container.querySelector(".v-B")).not.toBeNull();
  });
});

describe("a capability card", () => {
  function renderCard(props: Partial<Parameters<typeof CapabilityCard>[0]> = {}) {
    const onFocus = vi.fn();
    const onToggle = vi.fn();
    render(
      <CapabilityCard
        entry={CHARTS}
        enabled={false}
        focused={false}
        onFocus={onFocus}
        onToggle={onToggle}
        {...props}
      />,
    );
    return { onFocus, onToggle };
  }

  it("grants from its switch and opens settings from the art, the name and the button", async () => {
    const { onFocus, onToggle } = renderCard();

    await userEvent.click(screen.getByRole("switch", { name: /Charts/ }));
    expect(onToggle).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getAllByRole("button", { name: "Charts" })[0]!);
    await userEvent.click(screen.getByText("Charts"));
    await userEvent.click(screen.getByRole("button", { name: "Charts settings" }));
    expect(onFocus).toHaveBeenCalledTimes(3);
    expect(screen.getByText("1 tool")).toBeInTheDocument();
  });

  it("marks a capability that acts on the world, and one being read", () => {
    renderCard({ entry: SANDBOX, enabled: true, focused: true });

    expect(screen.getByLabelText("acts on the world")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Sandbox" })[0]!).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(screen.getByText("Built in, no tools")).toBeInTheDocument();
  });

  it("marks a capability the starter agent has as recommended", () => {
    renderCard({ entry: { ...CHARTS, recommended: { ...BINDING, id: "charts" } } });

    expect(screen.getByText("Recommended")).toBeInTheDocument();
  });

  it("recommends nothing the starter agent leaves out", () => {
    renderCard();

    expect(screen.queryByText("Recommended")).not.toBeInTheDocument();
  });

  it("frames the isometric diorama with a rule", () => {
    renderCard();
    expect(screen.getAllByRole("button", { name: "Charts" })[0]!).toHaveClass("border-b");
  });
});

describe("the capability gallery", () => {
  const SHELVES: CapabilityShelf[] = [
    { name: "analysis", label: "Work with data", entries: [CHARTS, SANDBOX] },
    { name: "utility", label: "Everyday", entries: [CLOCK] },
  ];

  function renderGallery(props: Partial<Parameters<typeof CapabilityGallery>[0]> = {}) {
    const handlers = { onOpen: vi.fn(), onClose: vi.fn(), onToggle: vi.fn() };
    render(
      <CapabilityGallery
        shelves={SHELVES}
        enabled={new Set(["charts"])}
        openedId={null}
        detail={<p>the detail</p>}
        {...handlers}
        {...props}
      />,
    );
    return handlers;
  }

  it("shelves each category with how many of it are on", () => {
    renderGallery();

    const data = screen.getByRole("region", { name: "Work with data" });
    expect(within(data).getByText("1 of 2 on")).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: "Everyday" })).getByText("0 of 1 on"),
    ).toBeInTheDocument();
    expect(screen.queryByText("the detail")).not.toBeInTheDocument();
  });

  it("pages a shelf sideways from its arrows", async () => {
    const scrollBy = vi.fn();
    Element.prototype.scrollBy = scrollBy;
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(400);
    renderGallery();

    await userEvent.click(screen.getByRole("button", { name: "More in Work with data" }));
    await userEvent.click(screen.getByRole("button", { name: "Earlier in Work with data" }));

    expect(scrollBy.mock.calls.map(([options]) => options.left)).toEqual([340, -340]);
  });

  it("opens a card's settings and toggles from the card", async () => {
    const { onOpen, onToggle } = renderGallery();

    await userEvent.click(screen.getByRole("button", { name: "Sandbox settings" }));
    await userEvent.click(screen.getByRole("switch", { name: /Date and time/ }));

    expect(onOpen).toHaveBeenCalledWith("sandbox");
    expect(onToggle).toHaveBeenCalledWith("clock");
  });

  it("holds the opened capability's settings in a panel that closes", async () => {
    const { onClose } = renderGallery({ openedId: "charts" });

    const panel = screen.getByRole("dialog");
    expect(within(panel).getByRole("heading", { name: "Charts settings" })).toBeInTheDocument();
    expect(within(panel).getByText("the detail")).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: /close/i }));

    expect(onClose).toHaveBeenCalled();
  });
});
