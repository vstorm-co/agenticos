import { describe, expect, it } from "vitest";
import {
  architectSetupHints,
  proactivitySetupHints,
  systemAgentSetupHints,
  voiceSetupHints,
} from "./setup-hints";

describe("saved configuration hints", () => {
  it("offers optional voice setup without treating browser dictation as broken", () => {
    expect(voiceSetupHints({})).toEqual([]);
    expect(voiceSetupHints({ speech_to_text_provider: "provider" })).toEqual([]);
    expect(
      voiceSetupHints({ speech_to_text_provider: "provider", speech_to_text_model: null }),
    ).toEqual(["voiceModel"]);
    expect(
      voiceSetupHints({ speech_to_text_provider: null, speech_to_text_model: "model" }),
    ).toEqual(["voiceModel"]);
    expect(
      voiceSetupHints({ speech_to_text_provider: "provider", speech_to_text_model: "model" }),
    ).toEqual([]);
    expect(
      voiceSetupHints({
        speech_to_text_provider: null,
        speech_to_text_model: null,
        speech_to_text_secret_id: null,
      }),
    ).toEqual(["voiceModel"]);
    expect(
      voiceSetupHints({
        speech_to_text_provider: "provider",
        speech_to_text_model: "model",
        speech_to_text_secret_id: null,
      }),
    ).toEqual(["voiceKey"]);
    expect(
      voiceSetupHints({
        speech_to_text_provider: "provider",
        speech_to_text_model: "model",
        speech_to_text_secret_id: "key",
      }),
    ).toEqual([]);
  });
  it("distinguishes disabled suggestions, an incomplete enabled configuration and unknown data", () => {
    expect(proactivitySetupHints({})).toEqual([]);
    expect(proactivitySetupHints({ proactive_enabled: false })).toEqual(["proactivityOff"]);
    expect(
      proactivitySetupHints({ proactive_enabled: true, proactive_model_profile_id: null }),
    ).toEqual(["proactivityModel"]);
    expect(
      proactivitySetupHints({ proactive_enabled: true, proactive_model_profile_id: "model" }),
    ).toEqual([]);
  });
  it("does not flag the briefing as a second model to configure", () => {
    expect(systemAgentSetupHints({ role: "daily_briefing", model_profile_id: null })).toEqual([]);
    expect(systemAgentSetupHints({ role: "memory_maintenance", model_profile_id: null })).toEqual([
      "memoryModel",
    ]);
    expect(
      systemAgentSetupHints({ role: "memory_maintenance", model_profile_id: "model" }),
    ).toEqual([]);
  });
  it("uses the Architect's explicit status, leaving a disabled Architect alone", () => {
    expect(architectSetupHints({ status: "needs_model" })).toEqual(["architectModel"]);
    expect(architectSetupHints({ status: "ready" })).toEqual([]);
    expect(architectSetupHints({ status: "disabled" })).toEqual([]);
    expect(architectSetupHints({ status: "unavailable" })).toEqual([]);
  });
});
