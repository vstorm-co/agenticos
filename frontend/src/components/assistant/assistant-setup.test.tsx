import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ROUTES } from "@/lib/constants";
import type { AssistantState } from "@/types/assistant";

import { AssistantSetup, TYPING_MS } from "./assistant-setup";

const push = vi.hoisted(() => vi.fn());
vi.mock("@/lib/locale-navigation", () => ({ useRouter: () => ({ push }) }));

function assistant(overrides: Partial<AssistantState> = {}): AssistantState {
  return {
    status: "needs_model",
    agent_id: "a1",
    slug: "ai-architect",
    name: "AI Architect",
    greeting: null,
    avatar_url: null,
    avatar_color: null,
    model_profile_id: null,
    collection_ids: [],
    can_use: true,
    can_configure: true,
    ...overrides,
  };
}

function mount(overrides: Partial<AssistantState> = {}) {
  render(<AssistantSetup assistant={assistant(overrides)} agentId="a1" />);
}

/** Lets the walkthrough type out every message. */
function typeEverything() {
  for (let step = 0; step < 6; step += 1) {
    act(() => {
      vi.advanceTimersByTime(TYPING_MS);
    });
  }
}

beforeEach(() => {
  vi.useFakeTimers();
  push.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the AI Architect with no model", () => {
  it("offers to explain before anybody opens it", () => {
    mount();

    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByText(/I'm not connected to a model yet/));

    expect(screen.getByRole("dialog", { name: "Connecting a model" })).toBeVisible();
  });

  it("types the walkthrough one message at a time", () => {
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Open AI Architect" }));

    expect(screen.getByText(/Hi, I'm AI Architect/)).toBeInTheDocument();
    expect(screen.getByText("AI Architect is typing…")).toBeInTheDocument();
    expect(screen.queryByText(/Step 1: get an API key/)).toBeNull();

    act(() => {
      vi.advanceTimersByTime(TYPING_MS);
    });

    expect(screen.getByText(/Step 1: get an API key/)).toBeInTheDocument();
    expect(screen.queryByText(/Step 2/)).toBeNull();
  });

  it("walks an administrator to the settings that connect the model", () => {
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Open AI Architect" }));
    typeEverything();

    expect(screen.getByText(/Step 2: open Settings → Assistant/)).toBeInTheDocument();
    expect(screen.getByText(/Step 3: choose a model and save/)).toBeInTheDocument();
    expect(screen.getByText(/That's it/)).toBeInTheDocument();
    expect(screen.queryByText(/is typing/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Open assistant settings" }));
    expect(push).toHaveBeenCalledWith(ROUTES.SETTINGS_ASSISTANT);
  });

  it("tells anybody else who can do it, and offers no button they could not use", () => {
    mount({ can_configure: false });
    fireEvent.click(screen.getByRole("button", { name: "Open AI Architect" }));
    typeEverything();

    expect(screen.getByText(/only an administrator of your organization/)).toBeInTheDocument();
    expect(screen.queryByText(/That's it/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Open assistant settings" })).toBeNull();
  });

  it("closes from its header and its button alike, keeping the conversation", () => {
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Open AI Architect" }));

    // Hidden rather than unmounted, so the walkthrough is not typed out again.
    const dialog = screen.getByRole("dialog");
    fireEvent.click(screen.getAllByRole("button", { name: "Close" })[0]!);
    expect(dialog).toHaveClass("hidden");

    fireEvent.click(screen.getByRole("button", { name: "Open AI Architect" }));
    expect(dialog).not.toHaveClass("hidden");
    fireEvent.click(screen.getByRole("button", { name: "Close", expanded: true }));
    expect(dialog).toHaveClass("hidden");
  });
});
