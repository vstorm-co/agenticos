import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DesktopOnly, DesktopSetting } from "./desktop-only";
import { DESKTOP_STATE, MAC_MAIN } from "./fixtures";

const env = vi.hoisted(() => ({
  shell: null as unknown,
  query: { data: undefined as unknown, error: null as Error | null },
}));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => env.shell }));
vi.mock("@/hooks/use-desktop", () => ({ useDesktopState: () => env.query }));

beforeEach(() => {
  env.shell = MAC_MAIN;
  env.query = { data: DESKTOP_STATE, error: null };
});

describe("DesktopOnly", () => {
  it("draws the settings from the desktop app's state", () => {
    render(
      <DesktopOnly>{(state) => <p>{state.window.badge ? "counting" : "quiet"}</p>}</DesktopOnly>,
    );
    expect(screen.getByText("counting")).toBeInTheDocument();
  });

  it("says where these settings live in a browser, rather than an empty card", () => {
    env.shell = null;
    render(<DesktopOnly>{() => <p>settings</p>}</DesktopOnly>);
    expect(
      screen.getByText("These settings belong to the AgenticOS desktop app."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "About the desktop app" })).toHaveAttribute(
      "href",
      "https://vstorm-co.github.io/agenticos/desktop/",
    );
    expect(screen.queryByText("settings")).toBeNull();
  });

  it("says so when the app's answer could not be read, and draws nothing while it loads", () => {
    env.query = { data: undefined, error: new Error("malformed: look") };
    const { unmount } = render(<DesktopOnly>{() => <p>settings</p>}</DesktopOnly>);
    expect(screen.getByRole("alert")).toHaveTextContent("did not say what its settings are");
    unmount();

    env.query = { data: undefined, error: null };
    const { container } = render(<DesktopOnly>{() => <p>settings</p>}</DesktopOnly>);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("DesktopSetting", () => {
  it("names its control and says what it means, when there is something to say", () => {
    render(
      <>
        <DesktopSetting id="a" label="Open at login" hint="On sign-in">
          <input aria-labelledby="a" />
        </DesktopSetting>
        <DesktopSetting id="b" label="Bare">
          <input aria-labelledby="b" />
        </DesktopSetting>
      </>,
    );
    expect(screen.getByRole("textbox", { name: "Open at login" })).toBeInTheDocument();
    expect(screen.getByText("On sign-in")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Bare" })).toBeInTheDocument();
  });
});
