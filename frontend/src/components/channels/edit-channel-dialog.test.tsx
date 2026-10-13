import { describe, expect, it } from "vitest";

import { botPatch, type ChannelBotDraft } from "./edit-channel-dialog";
import type { ChannelBot } from "@/types/channels";

function bot(overrides: Partial<ChannelBot> = {}): ChannelBot {
  return {
    id: "b1",
    platform: "slack",
    name: "Jarvis",
    is_active: true,
    webhook_mode: false,
    webhook_url: null,
    api_base_url: null,
    has_webhook_secret: false,
    has_slack_signing_secret: false,
    has_slack_app_token: false,
    connection: null,
    transcribe_voice_notes: true,
    speech_to_text_provider: null,
    speech_to_text_model: null,
    agents: [],
    created_at: "2026-08-31T09:00:00Z",
    ...overrides,
  };
}

function draft(overrides: Partial<ChannelBotDraft> = {}): ChannelBotDraft {
  return {
    name: "Jarvis",
    token: "",
    serverUrl: "",
    webhookSecret: "",
    signingSecret: "",
    appToken: "",
    transcription: { mode: "inherit", provider: null, model: null },
    ...overrides,
  };
}

describe("the patch an edited bot sends", () => {
  it("sends nothing when nobody typed anything", () => {
    // A save on an untouched dialog must not reseal the stored credentials
    // under a new key version, and must not be a write at all.
    expect(botPatch(bot(), draft())).toEqual({});
  });

  it("leaves a credential alone when its field is blank", () => {
    // The whole reason a blank input cannot mean "clear it": the backend reads
    // an omitted field as keep and an empty string as a value, so submitting
    // every input would wipe every credential nobody retyped.
    const patch = botPatch(
      bot({ has_slack_signing_secret: true, has_slack_app_token: true }),
      draft({ name: "Jarvis renamed" }),
    );

    expect(patch).toEqual({ name: "Jarvis renamed" });
  });

  it("sends the app token a Socket Mode bot was missing", () => {
    const patch = botPatch(bot(), draft({ appToken: "xapp-1-A0000-abc" }));

    expect(patch).toEqual({ slack_app_token: "xapp-1-A0000-abc" });
  });

  it("sends both Slack credentials when both were typed", () => {
    const patch = botPatch(
      bot(),
      draft({ signingSecret: "a-signing-secret", appToken: "xapp-1-A0000-abc" }),
    );

    expect(patch).toEqual({
      slack_signing_secret: "a-signing-secret",
      slack_app_token: "xapp-1-A0000-abc",
    });
  });

  it("does not send a name equal to the one already stored", () => {
    const patch = botPatch(bot({ name: "Jarvis" }), draft({ name: "  Jarvis  " }));

    expect(patch).toEqual({});
  });

  it("does not send an emptied name, which would be a rename to nothing", () => {
    const patch = botPatch(bot(), draft({ name: "   ", appToken: "xapp-1-A0000-abc" }));

    expect(patch).toEqual({ slack_app_token: "xapp-1-A0000-abc" });
  });

  it("replaces the bot token when a new one is pasted", () => {
    const patch = botPatch(bot(), draft({ token: "xoxb-a-replacement-token" }));

    expect(patch).toEqual({ token: "xoxb-a-replacement-token" });
  });

  it("keeps Slack credentials out of a Mattermost patch", () => {
    // The dialog does not render those inputs for Mattermost, but the draft
    // survives a reopen on another row - and a Slack secret on a Mattermost
    // bot is a field the backend has no use for.
    const patch = botPatch(
      bot({ platform: "mattermost", api_base_url: "https://mm.acme.com" }),
      draft({ signingSecret: "leftover", appToken: "leftover", webhookSecret: "mm-token" }),
    );

    expect(patch).toEqual({ webhook_secret: "mm-token" });
  });

  it("keeps Mattermost fields out of a Slack patch", () => {
    const patch = botPatch(
      bot({ platform: "slack" }),
      draft({ serverUrl: "https://mm.acme.com", webhookSecret: "leftover" }),
    );

    expect(patch).toEqual({});
  });

  it("sends a changed Mattermost server but not an unchanged one", () => {
    const acme = bot({ platform: "mattermost", api_base_url: "https://mm.acme.com" });

    expect(botPatch(acme, draft({ serverUrl: "https://mm.acme.com" }))).toEqual({});
    expect(botPatch(acme, draft({ serverUrl: "https://mm.globex.com" }))).toEqual({
      api_base_url: "https://mm.globex.com",
    });
  });

  it("keeps a Telegram bot to the two fields it has", () => {
    const patch = botPatch(
      bot({ platform: "telegram" }),
      draft({ token: "111:AAA-replacement", serverUrl: "x", appToken: "x", webhookSecret: "x" }),
    );

    expect(patch).toEqual({ token: "111:AAA-replacement" });
  });
});

describe("the transcription half of an edited bot's patch", () => {
  it("sends nothing while the choice is what the bot already does", () => {
    const paired = bot({
      speech_to_text_provider: "groq",
      speech_to_text_model: "whisper-large-v3",
    });

    expect(botPatch(bot(), draft())).toEqual({});
    expect(
      botPatch(
        paired,
        draft({ transcription: { mode: "choose", provider: "groq", model: "whisper-large-v3" } }),
      ),
    ).toEqual({});
    expect(
      botPatch(
        bot({ transcribe_voice_notes: false }),
        draft({ transcription: { mode: "off", provider: null, model: null } }),
      ),
    ).toEqual({});
  });

  it("turns a bot off with the switch alone, which clears its pair on the server", () => {
    const paired = bot({
      speech_to_text_provider: "groq",
      speech_to_text_model: "whisper-large-v3",
    });

    expect(
      botPatch(paired, draft({ transcription: { mode: "off", provider: null, model: null } })),
    ).toEqual({ transcribe_voice_notes: false });
  });

  it("returns a bot with its own pair to inherit by clearing the pair", () => {
    // A null pair means inherit now; it used to mean off.
    const paired = bot({
      speech_to_text_provider: "groq",
      speech_to_text_model: "whisper-large-v3",
    });

    expect(botPatch(paired, draft())).toEqual({
      speech_to_text_provider: null,
      speech_to_text_model: null,
    });
  });

  it("turns an off bot back on to inherit", () => {
    expect(botPatch(bot({ transcribe_voice_notes: false }), draft())).toEqual({
      transcribe_voice_notes: true,
    });
  });

  it("turns an off bot on with a pair of its own in one patch", () => {
    expect(
      botPatch(
        bot({ transcribe_voice_notes: false }),
        draft({ transcription: { mode: "choose", provider: "openai", model: "whisper-1" } }),
      ),
    ).toEqual({
      transcribe_voice_notes: true,
      speech_to_text_provider: "openai",
      speech_to_text_model: "whisper-1",
    });
  });

  it("sends both halves when only the model moved", () => {
    const paired = bot({
      speech_to_text_provider: "groq",
      speech_to_text_model: "whisper-large-v3",
    });

    expect(
      botPatch(
        paired,
        draft({
          transcription: { mode: "choose", provider: "groq", model: "whisper-large-v3-turbo" },
        }),
      ),
    ).toEqual({ speech_to_text_provider: "groq", speech_to_text_model: "whisper-large-v3-turbo" });
  });
});
