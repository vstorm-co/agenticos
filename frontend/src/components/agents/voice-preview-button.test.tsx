import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import type { VoiceSpec } from "@/types/agents";

import { VoicePreviewButton } from "./voice-preview-button";

const previewVoice = vi.hoisted(() => vi.fn());
vi.mock("@/lib/voice-api", () => ({ previewVoice }));
const toastError = vi.hoisted(() => vi.fn());
vi.mock("sonner", () => ({ toast: { error: toastError } }));

const BLOCK: VoiceSpec = {
  provider: "openai",
  model: "gpt-realtime",
  deployment: null,
  base_model: null,
  secret_id: "s1",
  voice: "marin",
  language: null,
  max_call_seconds: null,
  voice_note: null,
};

/** Every `<audio>` the button makes: played, paused, and told when it ends. */
const players: {
  src: string;
  play: ReturnType<typeof vi.fn>;
  pause: ReturnType<typeof vi.fn>;
  onended: (() => void) | null;
}[] = [];

beforeEach(() => {
  players.length = 0;
  previewVoice.mockReset().mockResolvedValue(new Blob(["RIFF"], { type: "audio/wav" }));
  toastError.mockReset();
  vi.stubGlobal(
    "Audio",
    vi.fn(function (this: unknown, src: string) {
      const player = { src, play: vi.fn(async () => {}), pause: vi.fn(), onended: null };
      players.push(player);
      return player;
    }),
  );
  URL.createObjectURL = vi.fn(() => "blob:voice");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => vi.unstubAllGlobals());

const listen = () => screen.getByRole("button", { name: "Listen to this voice" });

describe("VoicePreviewButton", () => {
  it("plays the draft's voice, and stops it on a second press", async () => {
    render(<VoicePreviewButton agentId="a1" block={BLOCK} />);

    fireEvent.click(listen());
    const stop = await screen.findByRole("button", { name: "Stop" });
    expect(previewVoice).toHaveBeenCalledWith("a1", BLOCK, "en");
    expect(players[0]!.play).toHaveBeenCalled();

    fireEvent.click(stop);
    expect(players[0]!.pause).toHaveBeenCalled();
    expect(listen()).toBeInTheDocument();
  });

  it("goes back to ▶ when the sentence ends, and fetches the same voice only once", async () => {
    render(<VoicePreviewButton agentId="a1" block={BLOCK} />);
    fireEvent.click(listen());
    await screen.findByRole("button", { name: "Stop" });
    act(() => players[0]!.onended!());

    fireEvent.click(listen());
    await screen.findByRole("button", { name: "Stop" });
    expect(previewVoice).toHaveBeenCalledOnce();
    expect(players).toHaveLength(2);
  });

  it("asks for a key before it can play", () => {
    render(<VoicePreviewButton agentId="a1" block={{ ...BLOCK, secret_id: null }} />);
    expect(listen()).toBeDisabled();
    expect(listen()).toHaveAttribute("title", "Choose a key to listen to this voice");
  });

  it("says why a preview failed and offers it again", async () => {
    previewVoice.mockRejectedValue(
      new ApiError(503, "The voice provider did not answer in time.", null),
    );
    render(<VoicePreviewButton agentId="a1" block={BLOCK} />);

    fireEvent.click(listen());

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(listen()).not.toBeDisabled();
  });

  it("lets go of the audio when it leaves the page", async () => {
    const { unmount } = render(<VoicePreviewButton agentId="a1" block={BLOCK} />);
    fireEvent.click(listen());
    await screen.findByRole("button", { name: "Stop" });

    unmount();

    expect(players[0]!.pause).toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:voice");
  });
});
