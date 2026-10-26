import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useUnsavedChangesStore, type UnsavedSource } from "@/stores/unsaved-changes-store";
import { UnsavedChangesGuard } from "./unsaved-changes-guard";

const router = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

function hold(id = "editor", source: Partial<UnsavedSource> = {}) {
  const held = { discard: vi.fn(), ...source };
  act(() => useUnsavedChangesStore.getState().register(id, held));
  return held;
}

function page(...links: { href: string; label: string; target?: string; download?: boolean }[]) {
  render(
    <>
      {links.map(({ href, label, target, download }) => (
        <a key={label} href={href} target={target} download={download}>
          {label}
        </a>
      ))}
      <UnsavedChangesGuard />
    </>,
  );
}

const asked = () => screen.queryByRole("dialog", { name: "You have unsaved changes" });

beforeEach(() => {
  useUnsavedChangesStore.setState({ sources: {}, prompt: null, saving: false });
  window.history.replaceState(null, "", "/datasets/ds-1");
});
afterEach(() => vi.clearAllMocks());

describe("UnsavedChangesGuard", () => {
  it("has the browser ask before the tab closes, only while something is held", () => {
    page();
    const free = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(free);
    expect(free.defaultPrevented).toBe(false);

    hold();
    const held = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(held);
    expect(held.defaultPrevented).toBe(true);
  });

  it("asks before a link leaves, and goes there once the change is discarded", async () => {
    page({ href: "/agents?tab=all#top", label: "Agents" });
    const editor = hold();
    await userEvent.click(screen.getByRole("link", { name: "Agents" }));
    expect(asked()).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(editor.discard).toHaveBeenCalled();
    expect(router.push).toHaveBeenCalledWith("/agents?tab=all#top");
  });

  it("stays on the page when asked to, with Escape as much as with the button", async () => {
    page({ href: "/agents", label: "Agents" });
    hold();
    await userEvent.click(screen.getByRole("link", { name: "Agents" }));
    await userEvent.click(screen.getByRole("button", { name: "Stay" }));
    expect(asked()).toBeNull();

    await userEvent.click(screen.getByRole("link", { name: "Agents" }));
    await userEvent.keyboard("{Escape}");
    expect(asked()).toBeNull();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("offers Save only where every held change can be saved, and says so while saving", async () => {
    let finish: (saved: boolean) => void = () => {};
    page({ href: "/agents", label: "Agents" });
    hold("grading", { save: () => new Promise<boolean>((resolve) => (finish = resolve)) });
    hold("editor");
    await userEvent.click(screen.getByRole("link", { name: "Agents" }));
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.getByText(/Stay to finish them, or discard them/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Stay" }));

    act(() => useUnsavedChangesStore.getState().unregister("editor"));
    await userEvent.click(screen.getByRole("link", { name: "Agents" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();
    // Escape while saving leaves the question where it is.
    await userEvent.keyboard("{Escape}");
    expect(asked()).toBeInTheDocument();
    await act(async () => finish(true));
    expect(router.push).toHaveBeenCalledWith("/agents");
  });

  it("lets through what is not leaving this app's page", async () => {
    page(
      { href: "https://example.com/docs", label: "Elsewhere" },
      { href: "/report.csv", label: "File", download: true },
      { href: "/agents", label: "New tab", target: "_blank" },
      { href: "/datasets/ds-1#cases", label: "Here" },
      { href: "/agents", label: "Agents" },
    );
    hold();
    for (const name of ["Elsewhere", "File", "New tab", "Here"]) {
      fireEvent.click(screen.getByRole("link", { name }));
      expect(asked()).toBeNull();
    }
    fireEvent.click(screen.getByRole("link", { name: "Agents" }), { metaKey: true });
    fireEvent.click(screen.getByRole("link", { name: "Agents" }), { button: 1 });
    const handled = new MouseEvent("click", { bubbles: true, cancelable: true });
    handled.preventDefault();
    screen.getByRole("link", { name: "Agents" }).dispatchEvent(handled);
    fireEvent.click(document.body);
    expect(asked()).toBeNull();
  });

  it("does not hold links once nothing is unsaved", () => {
    page({ href: "/agents", label: "Agents" });
    fireEvent.click(screen.getByRole("link", { name: "Agents" }));
    expect(asked()).toBeNull();
  });

  it("asks before Back leaves, and goes back past its own entry once discarded", async () => {
    const go = vi.spyOn(window.history, "go").mockImplementation(() => {});
    page();
    const length = window.history.length;
    hold();
    expect(window.history.length).toBe(length + 1);
    expect((window.history.state as Record<string, unknown>).__unsavedHeld).toBe(true);

    // Forward onto the held entry is not leaving.
    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate", { state: { __unsavedHeld: true } }));
    });
    expect(asked()).toBeNull();

    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate", { state: null }));
    });
    expect(asked()).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(go).toHaveBeenCalledWith(-2);
  });

  it("pushes no second entry for a page that already has one", () => {
    window.history.replaceState({ __unsavedHeld: true }, "", "/datasets/ds-1");
    page();
    const length = window.history.length;
    hold();
    expect(window.history.length).toBe(length);
  });
});
