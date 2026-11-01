import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SystemAgentChoice } from "./system-agent-choice";

const query = vi.hoisted(() => vi.fn());
const only = vi.hoisted(() => ({ seeded: false, model: true }));
vi.mock("@/hooks/use-agents", () => ({
  useAgentsOfKind: (kind: string) => {
    query(kind);
    const seed = {
      id: "seed",
      name: "Default",
      kind,
      system_key: "seeded",
      status: "published",
      current_version_id: "v1",
      published_model: only.model ? { label: "gpt-4.1-mini" } : null,
    };
    if (only.seeded) return { agents: [seed], isLoading: false, error: null };
    return {
      agents: [
        seed,
        {
          id: "own",
          name: "My assistant",
          kind,
          system_key: null,
          status: "published",
          current_version_id: "v2",
          published_model: { label: "Private model" },
        },
        {
          id: "draft",
          name: "Unpublished assistant",
          kind,
          system_key: null,
          status: "draft",
          current_version_id: null,
          published_model: null,
        },
      ],
      isLoading: false,
      error: null,
    };
  },
}));

describe("a system agent selected where it runs", () => {
  beforeEach(() => {
    only.seeded = false;
    only.model = true;
  });

  it("loads only the right kind when expanded and passes the selected identity", async () => {
    query.mockClear();
    const change = vi.fn();
    render(<SystemAgentChoice kind="improver" value={null} onChange={change} />);
    expect(query).not.toHaveBeenCalled();
    await userEvent.click(screen.getByText("Authoring assistant"));
    expect(query).toHaveBeenCalledWith("improver");
    await userEvent.click(screen.getByRole("combobox", { name: "Run with" }));
    expect(
      screen.getByRole("option", { name: "Unpublished assistant · Not published" }),
    ).toHaveAttribute("data-disabled");
    await userEvent.click(screen.getByRole("option", { name: "My assistant" }));
    expect(change).toHaveBeenCalledWith("own");
  });

  it("keeps a missing selection visible instead of adopting the default", async () => {
    render(<SystemAgentChoice kind="generator" value="deleted" onChange={vi.fn()} />);
    await userEvent.click(screen.getByText("Case generator"));
    expect(screen.getByText("Selected agent is unavailable")).toBeInTheDocument();
  });

  it("names the helper by what it does inside the Improve wizard", async () => {
    render(<SystemAgentChoice kind="improver" value={null} onChange={vi.fn()} wizard />);
    await userEvent.click(screen.getByText("Helper that writes the changes"));
    expect(screen.getByText(/reads the feedback and writes the changes/)).toBeInTheDocument();
  });

  it("names the organization's default helper and its model", async () => {
    render(<SystemAgentChoice kind="improver" value={null} onChange={vi.fn()} />);
    await userEvent.click(screen.getByText("Authoring assistant"));
    expect(screen.getByRole("combobox", { name: "Run with" })).toHaveTextContent(
      "Default · gpt-4.1-mini (default)",
    );
  });

  it("offers no choice when the kind has no alternative, and links to the helper", async () => {
    only.seeded = true;
    render(<SystemAgentChoice kind="judge" value={null} onChange={vi.fn()} />);
    await userEvent.click(screen.getByText("Judge"));
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.getByText(/Runs with Default · gpt-4\.1-mini/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Change it on its page" })).toHaveAttribute(
      "href",
      "/agents/seed",
    );
  });

  it("keeps the choice open while a custom helper is stored, so it can be reset", async () => {
    only.seeded = true;
    render(<SystemAgentChoice kind="judge" value="gone" onChange={vi.fn()} />);
    await userEvent.click(screen.getByText("Judge"));
    expect(screen.getByRole("combobox", { name: "Run with" })).toBeInTheDocument();
  });

  it("names a default helper with no published model by its name alone", async () => {
    only.model = false;
    render(<SystemAgentChoice kind="improver" value={null} onChange={vi.fn()} />);
    await userEvent.click(screen.getByText("Authoring assistant"));
    expect(screen.getByRole("combobox", { name: "Run with" })).toHaveTextContent(
      /^Default \(default\)$/,
    );
  });

  it("keeps an open list's trigger on screen when content above pushes it away", async () => {
    render(<SystemAgentChoice kind="improver" value={null} onChange={vi.fn()} />);
    await userEvent.click(screen.getByText("Authoring assistant"));
    const trigger = screen.getByRole("combobox", { name: "Run with" });
    let top = 100;
    vi.spyOn(trigger, "getBoundingClientRect").mockImplementation(
      () => ({ top, bottom: top + 36, left: 0, right: 200, width: 200, height: 36 }) as DOMRect,
    );
    const scroll = vi.spyOn(trigger, "scrollIntoView").mockImplementation(() => {
      top = 100;
    });
    await userEvent.click(trigger);
    await new Promise((resolve) => requestAnimationFrame(resolve));
    top = 300;
    await new Promise((resolve) => requestAnimationFrame(resolve));
    expect(scroll).not.toHaveBeenCalled();
    top = window.innerHeight + 200;
    await waitFor(() => expect(scroll).toHaveBeenCalledWith({ block: "nearest" }));
    top = -50;
    await waitFor(() => expect(scroll).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "true");
  });
});
