import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { QuickAskVoice } from "./quick-ask-voice";
import { initialCall } from "@/lib/voice/call-reducer";
import type { VoiceSession, useVoiceSession } from "@/hooks/use-voice-session";
import { useChatStore, useConversationStore } from "@/stores";
const env = vi.hoisted(() => ({
  session: null as VoiceSession | null,
  callbacks: undefined as Parameters<typeof useVoiceSession>[0],
}));
vi.mock("@/hooks/use-voice-session", () => ({
  useVoiceSession: (options: Parameters<typeof useVoiceSession>[0]) => {
    env.callbacks = options;
    return env.session;
  },
}));
vi.mock("@/hooks/use-voice-readiness", () => ({
  useVoiceReadiness: () => ({ readiness: { available: true, transport: "relay" }, failed: false }),
}));
vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({ agents: [{ id: "agent", name: "Support" }] }),
}));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => true }) }));
vi.mock("@/components/voice/voice-call-view", () => ({
  callActive: (s: VoiceSession) => s.call.phase === "live",
  VoiceCallBar: () => <p>Live call</p>,
  VoiceCallFeed: () => <p>Live captions</p>,
  showVoiceApproval: vi.fn(),
}));
beforeEach(() => {
  env.session = {
    call: initialCall,
    localStream: null,
    remoteStream: null,
    start: vi.fn(async () => {}),
    end: vi.fn(),
    setMuted: vi.fn(),
    pressToTalk: vi.fn(),
    decide: vi.fn(),
    answer: vi.fn(),
    dismissUnavailable: vi.fn(),
    dismiss: vi.fn(),
  };
  useChatStore.getState().clearMessages();
  useConversationStore.getState().reset();
});
const props = () => ({
  agentId: "agent",
  conversationId: "chat",
  active: true,
  disabled: false,
  onConversation: vi.fn(),
  onActiveChange: vi.fn(),
});
it("starts the selected agent's voice transport in the current Quick Ask conversation", async () => {
  const args = props();
  render(<QuickAskVoice {...args} />);
  await userEvent.click(screen.getByRole("button", { name: "Start a voice call" }));
  expect(env.session?.start).toHaveBeenCalledWith({
    kind: "console",
    agentId: "agent",
    conversationId: "chat",
    transport: "relay",
  });
});
it("blocks calls during a text turn or dictation", async () => {
  render(<QuickAskVoice {...props()} disabled />);
  expect(screen.getByRole("button", { name: "Start a voice call" })).toBeDisabled();
});
it("keeps saved voice turns in the text transcript and adopts its conversation", () => {
  const args = props();
  render(<QuickAskVoice {...args} />);
  act(() => {
    env.callbacks?.onConversation?.("voice-chat");
    env.callbacks?.onTurnSaved?.({
      id: "voice-message",
      role: "assistant",
      content: "Answer",
      interrupted: false,
      turn_id: "turn",
    });
  });
  expect(args.onConversation).toHaveBeenCalledWith("voice-chat");
  expect(useConversationStore.getState().currentConversationId).toBe("voice-chat");
  expect(useChatStore.getState().messages).toEqual([
    expect.objectContaining({ id: "voice-message", content: "Answer", agentId: "agent" }),
  ]);
});
it("shows the shared live controls and stops recording when the tab is left", () => {
  if (!env.session) throw new Error("missing fixture");
  env.session.call = { ...initialCall, phase: "live" };
  const args = props();
  const view = render(<QuickAskVoice {...args} />);
  expect(screen.getByText("Live call")).toBeVisible();
  expect(screen.getByText("Live captions")).toBeVisible();
  expect(args.onActiveChange).toHaveBeenCalledWith(true);
  view.rerender(<QuickAskVoice {...args} active={false} />);
  expect(env.session.end).toHaveBeenCalledOnce();
});
