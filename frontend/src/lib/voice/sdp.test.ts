import { describe, expect, it, vi } from "vitest";

import { audioOnlyOffer, consoleVoiceUrl, embedVoiceUrl } from "./sdp";

function fakePc(sdp: string | null) {
  return {
    createOffer: vi.fn().mockResolvedValue({ type: "offer", sdp }),
    setLocalDescription: vi.fn().mockResolvedValue(undefined),
    localDescription: sdp === null ? null : { sdp },
  } as unknown as RTCPeerConnection;
}

describe("sdp", () => {
  it("returns an audio-only offer", async () => {
    await expect(audioOnlyOffer(fakePc("v=0\r\nm=audio 9 UDP 111\r\n"))).resolves.toContain(
      "m=audio",
    );
  });

  it("refuses to send an offer that carries a data channel", async () => {
    await expect(
      audioOnlyOffer(fakePc("v=0\r\nm=audio 9 x\r\nm=application 9 x\r\n")),
    ).rejects.toThrow("data channel");
  });

  it("refuses an offer with no audio in it", async () => {
    await expect(audioOnlyOffer(fakePc(null))).rejects.toThrow("audio");
  });

  it("puts the organization in the console url and nothing secret in either", () => {
    expect(consoleVoiceUrl("wss://x", "org 1")).toBe(
      "wss://x/api/v1/ws/voice?organization_id=org%201",
    );
    expect(consoleVoiceUrl("wss://x", null)).toBe("wss://x/api/v1/ws/voice");
    expect(embedVoiceUrl("wss://x", "pk", "v".repeat(32), null)).toBe(
      `wss://x/api/v1/embed/pk/voice/ws?visitor=${"v".repeat(32)}`,
    );
    expect(embedVoiceUrl("wss://x", "p k", null, "t1")).toBe(
      "wss://x/api/v1/embed/p%20k/voice/ws?token=t1",
    );
    expect(embedVoiceUrl("wss://x", "pk", null, null)).toBe("wss://x/api/v1/embed/pk/voice/ws");
  });
});
