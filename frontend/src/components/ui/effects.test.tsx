import { act, render, screen } from "@testing-library/react";
import { useEffect, type ReactNode } from "react";
import { renderToString } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GeneratedImage } from "./generated-image";
import { VoiceGlow } from "./voice-glow";
import { useVoiceGlowStore } from "@/stores/voice-glow-store";

const env = vi.hoisted(() => ({ audio: false, reduced: false, mounted: true }));

vi.mock("voice-glow", async (importOriginal) => {
  const actual = await importOriginal<typeof import("voice-glow")>();
  return {
    ...actual,
    isAudioSupported: () => env.audio,
    // Draws what the glow was asked for, around what it wraps.
    VoiceBeam: (props: {
      children: ReactNode;
      colorVariant?: string;
      idle?: number;
      strength?: number;
      paused?: boolean;
      active?: boolean;
      processing?: boolean;
      stream?: MediaStream | null;
    }) => (
      <div
        data-testid="beam"
        data-variant={props.colorVariant}
        data-idle={String(props.idle)}
        data-strength={String(props.strength)}
        data-paused={String(props.paused)}
        data-active={String(props.active)}
        data-processing={String(props.processing)}
        data-stream={props.stream ? "live" : "none"}
      >
        {props.children}
      </div>
    ),
  };
});
vi.mock("motion/react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("motion/react")>()),
  useReducedMotion: () => env.reduced,
}));
vi.mock("@/hooks/use-mounted", () => ({ useMounted: () => env.mounted }));

const STREAM = {} as MediaStream;

function glow(children: ReactNode = <textarea aria-label="Message" />) {
  return (
    <VoiceGlow stream={STREAM} active processing>
      {children}
    </VoiceGlow>
  );
}

/** A glow that is mounted but shows and analyses nothing. */
function expectSilenced(beam: HTMLElement) {
  expect(beam).toHaveAttribute("data-strength", "0");
  expect(beam).toHaveAttribute("data-paused", "true");
  expect(beam).toHaveAttribute("data-active", "false");
  expect(beam).toHaveAttribute("data-processing", "false");
  expect(beam).toHaveAttribute("data-stream", "none");
}

beforeEach(() => {
  env.audio = false;
  env.reduced = false;
  env.mounted = true;
  useVoiceGlowStore.setState({ style: "subtle" });
});

/**
 * The decorative layer, which has one rule in common: it wraps something and
 * must never be the reason that something is not there. jsdom has no WebGL, no
 * Web Audio and no canvas, which is the same position as a browser that has
 * turned them off - so these tests are the fallback path as much as they are
 * the happy one.
 */
describe("the effect wrappers", () => {
  it("VoiceGlow leaves what it wraps alone where there is no Web Audio", () => {
    render(glow());

    expect(screen.getByLabelText("Message")).toBeInTheDocument();
    expect(screen.queryByTestId("beam")).not.toBeInTheDocument();
  });

  it("GeneratedImage draws the plain picture where the shader cannot run", () => {
    // jsdom has no WebGL, which is the same position as a browser that refuses
    // one: the image is what matters and it is still there.
    render(<GeneratedImage src="/api/files/f-1" alt="chart.png" />);

    expect(screen.getByAltText("chart.png")).toBeInTheDocument();
  });
});

/**
 * The person's Voice glow preference, and the motion setting that overrides it.
 */
describe("VoiceGlow styles", () => {
  beforeEach(() => {
    env.audio = true;
  });

  it("renders only what it wraps on the server, where Web Audio is unknown", () => {
    // The server snapshot says no audio, so the first client render - which
    // reads the same snapshot while hydrating - draws the same tree.
    const html = renderToString(glow());

    expect(html).toContain("<textarea");
    expect(html).not.toContain("data-testid");
  });

  it("is a quiet neutral edge by default", () => {
    render(glow());

    const beam = screen.getByTestId("beam");
    expect(beam).toHaveAttribute("data-variant", "mono");
    expect(beam).toHaveAttribute("data-idle", "0");
    expect(beam).toHaveAttribute("data-strength", "0.25");
    expect(beam).toHaveAttribute("data-stream", "live");
    expect(beam).toHaveAttribute("data-active", "true");
  });

  it("is the colourful glow when the person asked for vivid", () => {
    useVoiceGlowStore.setState({ style: "vivid" });
    render(glow());

    const beam = screen.getByTestId("beam");
    expect(beam).toHaveAttribute("data-variant", "colorful");
    expect(beam).toHaveAttribute("data-idle", "0.45");
    // The library's own default strength, not the subtle one.
    expect(beam).toHaveAttribute("data-strength", "undefined");
  });

  it("shows nothing when the person turned it off", () => {
    useVoiceGlowStore.setState({ style: "off" });
    render(glow());

    expectSilenced(screen.getByTestId("beam"));
    expect(screen.getByLabelText("Message")).toBeInTheDocument();
  });

  it("shows nothing under reduced motion, whatever the preference", () => {
    // A glow that cannot move says nothing.
    env.reduced = true;
    useVoiceGlowStore.setState({ style: "vivid" });
    render(glow());

    expectSilenced(screen.getByTestId("beam"));
  });

  it("shows nothing before mount, so the server and first client render agree", () => {
    env.mounted = false;
    render(glow());

    expectSilenced(screen.getByTestId("beam"));
  });

  it("never remounts what it wraps when the style changes", () => {
    // The composer inside holds a draft, focus and a caret; a style switch
    // that remounted it would lose all three.
    const mounts = vi.fn();
    function Child() {
      useEffect(() => {
        mounts();
      }, []);
      return <textarea aria-label="Message" defaultValue="" />;
    }
    render(glow(<Child />));
    const box = screen.getByLabelText("Message") as HTMLTextAreaElement;
    box.value = "half a thought";

    act(() => useVoiceGlowStore.setState({ style: "off" }));
    act(() => useVoiceGlowStore.setState({ style: "subtle" }));

    expect(mounts).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Message")).toBe(box);
    expect(box.value).toBe("half a thought");
  });
});
