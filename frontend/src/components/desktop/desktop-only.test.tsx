import { render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DesktopOnly, DesktopPage, DesktopSetting, DesktopTab } from "./desktop-only";
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

  it("says where these settings live in a browser or on a phone, rather than an empty card", () => {
    env.shell = { ...MAC_MAIN, platform: "android" };
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

describe("DesktopPage", () => {
  it("is the window's own content inside the desktop app", () => {
    render(<DesktopPage>{<p>quick ask</p>}</DesktopPage>);
    expect(screen.getByText("quick ask")).toBeInTheDocument();
  });

  it("is one screen saying where it opens in a browser, and none of the window", () => {
    env.shell = null;
    render(<DesktopPage>{<p>quick ask</p>}</DesktopPage>);
    expect(screen.getByRole("main")).toHaveTextContent("This opens in the AgenticOS desktop app.");
    expect(screen.getAllByRole("link", { name: "About the desktop app" })).toHaveLength(1);
    expect(screen.queryByText("quick ask")).toBeNull();
  });

  it("draws nothing before hydration, so the app never flashes the browser screen", () => {
    expect(renderToString(<DesktopPage>{<p>quick ask</p>}</DesktopPage>)).toBe("");
  });
});

describe("DesktopTab", () => {
  it("is its sections inside the app, whatever the app's state", () => {
    env.query = { data: undefined, error: new Error("malformed") };
    render(<DesktopTab>{<p>sections</p>}</DesktopTab>);
    expect(screen.getByText("sections")).toBeInTheDocument();
  });

  it("is one card in a browser", () => {
    env.shell = null;
    render(<DesktopTab>{<p>sections</p>}</DesktopTab>);
    expect(screen.getAllByText("These settings belong to the AgenticOS desktop app.")).toHaveLength(
      1,
    );
    expect(screen.queryByText("sections")).toBeNull();
  });

  it("draws nothing before hydration", () => {
    expect(renderToString(<DesktopTab>{<p>sections</p>}</DesktopTab>)).toBe("");
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
