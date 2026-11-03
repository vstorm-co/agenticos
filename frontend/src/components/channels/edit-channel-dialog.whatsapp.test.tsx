import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { botPatch, EditChannelDialog, type ChannelBotDraft } from "./edit-channel-dialog";
import type { ChannelBot } from "@/types/channels";

vi.mock("@/hooks/use-channel-bots", () => ({
  useCopySlackManifest: () => ({ mutate: vi.fn(), isPending: false }),
  useDownloadTeamsPackage: () => ({ mutate: vi.fn(), isPending: false }),
  useChannelBot: () => null,
  useWhatsAppTemplates: () => ({
    data: [{ name: "late_answer", language: "en_US", body: "Answer: {{1}} - thanks" }],
    isLoading: false,
    isError: false,
  }),
}));
vi.mock("@/components/channels/transcription-fields", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/channels/transcription-fields")>()),
  TranscriptionFields: () => null,
}));

const CALLBACK = "https://agenticos.example.com/api/v1/whatsapp/webhook/b1";

function bot(overrides: Partial<ChannelBot> = {}): ChannelBot {
  return {
    id: "b1",
    platform: "whatsapp",
    name: "Support line",
    is_active: true,
    webhook_mode: true,
    webhook_url: null,
    api_base_url: null,
    access_policy: {
      mode: "open",
      whitelist: [],
      allowed_groups: [],
      require_link: false,
      rate_limit_rpm: 10,
      denied_message: "Denied",
    },
    has_webhook_secret: true,
    has_slack_signing_secret: false,
    has_slack_app_token: false,
    has_command_token: false,
    command_url: null,
    whatsapp_phone_number_id: "106540352242922",
    whatsapp_account_id: "102290129340398",
    has_whatsapp_verify_token: true,
    whatsapp_callback_url: CALLBACK,
    ack_reaction: null,
    stream_answers: true,
    step_display: "timeline",
    rate_answers: true,
    connection: null,
    transcribe_voice_notes: true,
    speech_to_text_provider: null,
    speech_to_text_model: null,
    speech_to_text_secret_id: null,
    agents: [],
    created_at: "2026-11-02T09:00:00Z",
    ...overrides,
  };
}

function draft(overrides: Partial<ChannelBotDraft> = {}): ChannelBotDraft {
  return {
    name: "Support line",
    token: "",
    serverUrl: "",
    webhookSecret: "",
    signingSecret: "",
    appToken: "",
    commandToken: "",
    discordGuilds: "",
    whatsappPhoneNumberId: "106540352242922",
    whatsappAccountId: "102290129340398",
    whatsappVerifyToken: "",
    whatsappLateTemplate: null,
    webhookMode: true,
    respondToBroadcasts: false,
    answerStyle: {
      ack_reaction: null,
      stream_answers: true,
      step_display: "timeline",
      rate_answers: true,
    },
    transcription: { mode: "inherit", provider: null, model: null, secretId: null },
    ...overrides,
  };
}

function show(current: ChannelBot, onSubmit = vi.fn().mockResolvedValue(undefined)) {
  render(
    <EditChannelDialog
      bot={current}
      onOpenChange={vi.fn()}
      onSubmit={onSubmit}
      isPending={false}
    />,
  );
  return onSubmit;
}

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label, { exact: false }), { target: { value } });
}

describe("setting up a WhatsApp bot (#2076)", () => {
  it("shows the callback url and never the verify token", () => {
    show(bot());

    expect(screen.getByText(CALLBACK)).toBeInTheDocument();
    expect(screen.getByText(/the one you chose/i)).toBeInTheDocument();
    expect(screen.getByText(/subscribe the messages field/i)).toBeInTheDocument();
    const verify = screen.getByLabelText("Verify token", { exact: false });
    expect(verify).toHaveAttribute("type", "password");
    expect(verify).toHaveValue("");
  });

  it("shows a down bot with its reason", () => {
    show(bot({ connection: { state: "down", reason: "Meta refused the access token" } }));

    expect(screen.getByText("Meta refused the access token")).toBeInTheDocument();
  });

  it("says nothing of a connection that is up or unknown", () => {
    show(bot({ connection: { state: "up", reason: null } }));

    expect(screen.queryByText(/not connected|refused/i)).not.toBeInTheDocument();
  });

  it("saves a changed number id and nothing else", () => {
    const onSubmit = show(bot());
    type("Phone number ID", "999999999");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSubmit).toHaveBeenCalledWith("b1", { whatsapp_phone_number_id: "999999999" });
  });

  it("holds Save back for an id that is not digits and for a short secret", () => {
    show(bot());
    type("Phone number ID", "not-a-number");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

    type("Phone number ID", "106540352242922");
    type("App secret", "short");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

    type("App secret", "long-enough-secret");
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("offers no group mentions switch: every WhatsApp chat is private", () => {
    show(bot());

    expect(screen.queryByRole("switch", { name: "Respond to group mentions" })).toBeNull();
  });

  it("lists Meta's steps as a numbered list", () => {
    show(bot());

    const [steps, ...others] = screen.getAllByRole("list").filter((list) => list.tagName === "OL");
    expect(others).toEqual([]);
    expect(within(steps!).getAllByRole("listitem")).toHaveLength(4);
  });

  it("says a down bot cannot send replies, with the reason on its own line", () => {
    show(bot({ connection: { state: "down", reason: "Meta refused the access token" } }));

    const label = screen.getByText("Can't send replies");
    expect(label).toBeInTheDocument();
    expect(screen.queryByText("Not connected")).not.toBeInTheDocument();
    const reason = screen.getByText("Meta refused the access token");
    expect(reason).not.toBe(label);
    expect(reason.parentElement).toBe(label.parentElement);
    expect(reason.tagName).toBe("SPAN");
    expect(reason).toHaveClass("block");
  });
});

describe("the late-answer template (#2076)", () => {
  const LATE = { name: "late_answer", language: "en_US" };

  it("warns when no late-answer template is set", () => {
    show(bot());

    expect(screen.getByRole("status")).toHaveTextContent(/no late-answer template is set/i);
  });

  it("does not warn once one is set", () => {
    show(bot({ whatsapp_late_template: { ...LATE, body: "Answer: {{1}} - thanks" } }));

    expect(screen.queryByText(/no late-answer template is set/i)).toBeNull();
  });

  it("saves the template picked in the dialog", async () => {
    const onSubmit = show(bot());
    await userEvent.click(screen.getByLabelText("Late-answer template"));
    await userEvent.click(screen.getByRole("option", { name: "late_answer · en_US" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSubmit).toHaveBeenCalledWith("b1", { whatsapp_late_template: LATE });
  });

  it("sends the chosen late-answer template, and null to clear it", () => {
    const stored = bot({ whatsapp_late_template: { ...LATE, body: "x {{1}}" } });

    expect(botPatch(bot(), draft({ whatsappLateTemplate: LATE }))).toEqual({
      whatsapp_late_template: LATE,
    });
    expect(botPatch(stored, draft({ whatsappLateTemplate: null }))).toEqual({
      whatsapp_late_template: null,
    });
  });

  it("sends no template when it did not change", () => {
    const stored = bot({ whatsapp_late_template: { ...LATE, body: "x {{1}}" } });

    expect(botPatch(stored, draft({ whatsappLateTemplate: LATE }))).toEqual({});
    expect(botPatch(bot(), draft({ whatsappLateTemplate: null }))).toEqual({});
  });

  it("never sends a template for another platform", () => {
    const slack = bot({ platform: "slack", webhook_mode: false });

    expect(botPatch(slack, draft({ webhookMode: false, whatsappLateTemplate: LATE }))).toEqual({});
  });
});

describe("the patch an edited WhatsApp bot sends", () => {
  it("sends nothing when nobody typed anything", () => {
    expect(botPatch(bot(), draft())).toEqual({});
  });

  it("sends only the secrets that were typed, never a null", () => {
    const patch = botPatch(
      bot(),
      draft({ webhookSecret: "new-app-secret", whatsappVerifyToken: "new-verify-token" }),
    );

    expect(patch).toEqual({
      webhook_secret: "new-app-secret",
      whatsapp_verify_token: "new-verify-token",
    });
  });

  it("sends a changed id, and not an emptied one", () => {
    expect(botPatch(bot(), draft({ whatsappPhoneNumberId: "777777777" }))).toEqual({
      whatsapp_phone_number_id: "777777777",
    });
    expect(botPatch(bot(), draft({ whatsappAccountId: "" }))).toEqual({});
  });

  it("never sends whatsapp keys or webhook_mode for another platform", () => {
    const slack = bot({
      platform: "slack",
      webhook_mode: false,
      whatsapp_phone_number_id: undefined,
      whatsapp_account_id: undefined,
    });
    const patch = botPatch(
      slack,
      draft({ webhookMode: false, whatsappPhoneNumberId: "123456", whatsappVerifyToken: "tok" }),
    );

    expect(Object.keys(patch).filter((key) => key.startsWith("whatsapp"))).toEqual([]);
  });

  it("does not send webhook_mode for a WhatsApp bot", () => {
    expect(botPatch(bot(), draft({ webhookMode: false }))).toEqual({});
  });
});
