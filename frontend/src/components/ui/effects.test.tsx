import { act, render, screen } from "@testing-library/react";
import { useEffect, type ReactNode } from "react";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GeneratedImage } from "./generated-image";
import { VoiceGlow } from "./voice-glow";
import { useVoiceGlowStore } from "@/stores/voice-glow-store";

const env = vi.hoisted(() => ({ audio: false, reduced: false, mounted: true }));

/** A Web Audio graph that records what was connected and answers a fixed level. */
const audioGraph = vi.hoisted(() => {
  const graph = {
    level: 0.1,
    sources: [] as {
      connect: ReturnType<typeof import("vitest").vi.fn>;
      disconnect: ReturnType<typeof import("vitest").vi.fn>;
    }[],
    analysers: [] as { disconnect: ReturnType<typeof import("vitest").vi.fn> }[],
    context: null as unknown,
  };
  return graph;
});

vi.mock("voice-glow", async (importOriginal) => {
  const actual = await importOriginal<typeof import("voice-glow")>();
  return {
    ...actual,
    isAudioSupported: () => env.audio,
    getAudioContext: () => audioGraph.context,
  };
});
vi.mock("@/hooks/use-reduced-motion", () => ({ useReducedMotion: () => env.reduced }));
vi.mock("@/hooks/use-mounted", () => ({ useMounted: () => env.mounted }));

const STREAM = {} as MediaStream;

function fakeContext() {
  return {
    createMediaStreamSource: vi.fn(() => {
      const source = { connect: vi.fn(), disconnect: vi.fn() };
      audioGraph.sources.push(source);
      return source;
    }),
    createAnalyser: vi.fn(() => {
      const analyser = {
        fftSize: 0,
        disconnect: vi.fn(),
        getFloatTimeDomainData: (samples: Float32Array) => samples.fill(audioGraph.level),
      };
      audioGraph.analysers.push(analyser);
      return analyser;
    }),
  };
}

function glow(
  children: ReactNode = <textarea aria-label="Message" />,
  props = { active: true, processing: false },
) {
  return (
    <VoiceGlow stream={STREAM} active={props.active} processing={props.processing}>
      {children}
    </VoiceGlow>
  );
}

beforeEach(() => {
  env.audio = false;
  env.reduced = false;
  env.mounted = true;
  audioGraph.level = 0.1;
  audioGraph.sources = [];
  audioGraph.analysers = [];
  audioGraph.context = fakeContext();
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
    expect(screen.queryByTestId("voice-glow")).not.toBeInTheDocument();
  });

  it("GeneratedImage draws the plain picture where the shader cannot run", () => {
    // jsdom has no WebGL, which is the same position as a browser that refuses
    // one: the image is what matters and it is still there.
    render(<GeneratedImage src="/api/files/f-1" alt="chart.png" />);

    expect(screen.getByAltText("chart.png")).toBeInTheDocument();
  });
});

/**
 * The person's Voice glow preference, the motion setting that overrides it, and
 * the level it reads from the microphone.
 */
describe("VoiceGlow", () => {
  beforeEach(() => {
    env.audio = true;
    vi.useFakeTimers({ toFake: ["requestAnimationFrame", "cancelAnimationFrame"] });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders only what it wraps on the server, where Web Audio is unknown", () => {
    const html = renderToString(glow());

    expect(html).toContain("<textarea");
    expect(html).not.toContain("voice-glow");
  });

  it("is the quiet ink bloom by default, behind and below the box", () => {
    render(glow());

    const bloom = screen.getByTestId("voice-glow");
    expect(bloom).toHaveAttribute("data-style", "subtle");
    expect(bloom).toHaveAttribute("aria-hidden", "true");
    expect(bloom).toHaveClass("-z-10");
  });

  it("is the colourful bloom when the person asked for vivid", () => {
    useVoiceGlowStore.setState({ style: "vivid" });
    render(glow());

    expect(screen.getByTestId("voice-glow")).toHaveAttribute("data-style", "vivid");
  });

  it("writes the microphone's level to the bloom and lets the audio go when it stops", () => {
    audioGraph.level = 0.1;
    const view = render(glow());

    act(() => vi.advanceTimersToNextFrame());
    const bloom = screen.getByTestId("voice-glow");
    // RMS 0.1 x gain 7 = 0.7, reached at the attack rate from rest.
    expect(Number(bloom.style.getPropertyValue("--voice-level"))).toBeCloseTo(0.7 * 0.35, 3);
    act(() => vi.advanceTimersToNextFrame());
    expect(Number(bloom.style.getPropertyValue("--voice-level"))).toBeGreaterThan(0.245);

    view.rerender(glow(undefined, { active: false, processing: false }));

    expect(audioGraph.sources[0]?.disconnect).toHaveBeenCalled();
    expect(audioGraph.analysers[0]?.disconnect).toHaveBeenCalled();
    expect(screen.queryByTestId("voice-glow")).not.toBeInTheDocument();
  });

  it("falls slowly after a loud moment rather than snapping shut", () => {
    audioGraph.level = 1;
    render(glow());
    act(() => vi.advanceTimersToNextFrame());
    const bloom = screen.getByTestId("voice-glow");
    const peak = Number(bloom.style.getPropertyValue("--voice-level"));

    audioGraph.level = 0;
    act(() => vi.advanceTimersToNextFrame());

    expect(Number(bloom.style.getPropertyValue("--voice-level"))).toBeCloseTo(peak * 0.92, 3);
  });

  it("sweeps instead of listening while the recording is transcribing", () => {
    render(glow(undefined, { active: false, processing: true }));

    expect(screen.getByTestId("voice-glow")).toHaveAttribute("data-processing", "true");
    expect(audioGraph.sources).toHaveLength(0);
  });

  it("listens to nothing when the page has no audio context to give it", () => {
    audioGraph.context = null;
    render(glow());

    expect(screen.getByTestId("voice-glow")).toBeInTheDocument();
    expect(audioGraph.sources).toHaveLength(0);
  });

  it.each([
    ["the person turned it off", () => useVoiceGlowStore.setState({ style: "off" })],
    [
      "reduced motion is on, whatever the preference",
      () => {
        env.reduced = true;
        useVoiceGlowStore.setState({ style: "vivid" });
      },
    ],
    [
      "the page has not mounted yet",
      () => {
        env.mounted = false;
      },
    ],
  ])("draws nothing when %s", (_label, arrange) => {
    arrange();
    render(glow());

    expect(screen.queryByTestId("voice-glow")).not.toBeInTheDocument();
    expect(audioGraph.sources).toHaveLength(0);
    expect(screen.getByLabelText("Message")).toBeInTheDocument();
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
