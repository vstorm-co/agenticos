import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { OrgTextToSpeechSettings } from "./org-text-to-speech-settings";
import { toast } from "sonner";
import { ApiError } from "@/lib/api-error";
import type { OrganizationTextToSpeech } from "@/types";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const state = vi.hoisted(() => ({ save: vi.fn(), failure: false, keyProps: vi.fn() }));
vi.mock("@/hooks", () => ({ useOrganizations: () => ({ setVoiceSettings: state.save }) }));
vi.mock("@/hooks/use-model-providers", () => ({
  useTextToSpeechProviders: () => ({
    isError: state.failure,
    providers: [
      {
        provider: "openai",
        name: "OpenAI",
        account_voices: false,
        models: [
          {
            id: "current",
            name: "Current",
            voices: [
              { id: "coral", name: "Coral" },
              { id: "alloy", name: "Alloy" },
            ],
          },
          { id: "older", name: "Older", voices: [{ id: "alloy", name: "Alloy" }] },
        ],
      },
      {
        provider: "elevenlabs",
        name: "ElevenLabs",
        account_voices: true,
        models: [{ id: "eleven_v4", name: "Eleven v4", voices: [] }],
      },
    ],
  }),
}));
vi.mock("@/components/vault/speech-key-field", () => ({
  SpeechKeyField: (props: {
    provider: string;
    onChange: (id: string) => void;
    orgVisibleOnly: boolean;
  }) => {
    state.keyProps(props);
    return <button onClick={() => props.onChange(`key-${props.provider}`)}>Choose key</button>;
  },
}));
const saved: OrganizationTextToSpeech = {
  enabled: true,
  provider: "openai",
  model: "current",
  voice: "coral",
  secret_id: "key-openai",
};
beforeEach(() => {
  state.save.mockReset();
  state.save.mockResolvedValue(undefined);
  state.keyProps.mockClear();
  state.failure = false;
});
async function expand() {
  await userEvent.click(screen.getByRole("button", { name: "Text to speech" }));
}

it("opens when enabled and refuses spending until the provider and shared key are chosen", async () => {
  render(<OrgTextToSpeechSettings org={{ id: "o1" }} />);
  await userEvent.click(screen.getByRole("switch", { name: "Text to speech" }));
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("organization-wide key");
  expect(state.save).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("combobox", { name: "Provider" }));
  await userEvent.click(screen.getByRole("option", { name: "OpenAI" }));
  expect(screen.queryByRole("alert")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Choose key" }));
  expect(state.keyProps.mock.lastCall?.[0].orgVisibleOnly).toBe(true);
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await waitFor(() => expect(state.save).toHaveBeenCalledWith("o1", { text_to_speech: saved }));
});

it("disables a configured default without discarding its provider or key", async () => {
  render(<OrgTextToSpeechSettings org={{ id: "o1", text_to_speech: saved }} />);
  await userEvent.click(screen.getByRole("switch", { name: "Text to speech" }));
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await waitFor(() =>
    expect(state.save).toHaveBeenCalledWith("o1", { text_to_speech: { ...saved, enabled: false } }),
  );
});

it("clears the key on a provider change and saves an account voice trimmed", async () => {
  render(<OrgTextToSpeechSettings org={{ id: "o1", text_to_speech: saved }} />);
  await expand();
  await userEvent.click(screen.getByRole("combobox", { name: "Provider" }));
  await userEvent.click(screen.getByRole("option", { name: "ElevenLabs" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Voice" }), {
    target: { value: "  account-voice  " },
  });
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
  expect(state.save).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Choose key" }));
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await waitFor(() =>
    expect(state.save).toHaveBeenCalledWith("o1", {
      text_to_speech: {
        enabled: true,
        provider: "elevenlabs",
        model: "eleven_v4",
        voice: "account-voice",
        secret_id: "key-elevenlabs",
      },
    }),
  );
});

it("changes model voices only when the new model cannot use the current voice", async () => {
  render(<OrgTextToSpeechSettings org={{ id: "o1", text_to_speech: saved }} />);
  await expand();
  await userEvent.click(screen.getByRole("combobox", { name: "Voice" }));
  await userEvent.click(screen.getByRole("option", { name: "Alloy" }));
  await userEvent.click(screen.getByRole("combobox", { name: "Model" }));
  await userEvent.click(screen.getByRole("option", { name: "Older" }));
  expect(screen.getByRole("combobox", { name: "Voice" })).toHaveTextContent("Alloy");
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("combobox", { name: "Voice" })).toHaveTextContent("Coral");
  await userEvent.click(screen.getByRole("combobox", { name: "Model" }));
  await userEvent.click(screen.getByRole("option", { name: "Older" }));
  expect(screen.getByRole("combobox", { name: "Voice" })).toHaveTextContent("Alloy");
});

it("preserves unavailable saved choices and displays the server's refusal", async () => {
  state.save.mockRejectedValue(
    new ApiError(400, "Bad key", {
      error: {
        code: "BAD_REQUEST",
        message: "Bad key",
        details: { fields: [{ field: "text_to_speech", message: "Choose an organization key" }] },
      },
    }),
  );
  const { rerender } = render(
    <OrgTextToSpeechSettings
      org={{ id: "o1", text_to_speech: { ...saved, model: "retired", voice: "unknown" } }}
    />,
  );
  await expand();
  expect(screen.getByRole("combobox", { name: "Model" })).toHaveTextContent("retired");
  expect(screen.getByRole("combobox", { name: "Voice" })).toHaveTextContent("unknown");
  await userEvent.click(screen.getByRole("switch", { name: "Text to speech" }));
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Choose an organization key");
  state.failure = true;
  rerender(
    <OrgTextToSpeechSettings
      org={{ id: "o1", text_to_speech: { ...saved, provider: "withdrawn" } }}
    />,
  );
  expect(screen.getByRole("status")).toHaveTextContent("could not be loaded");
  expect(screen.getByRole("combobox", { name: "Provider" })).toHaveTextContent("withdrawn");
});

it("clears an incomplete disabled default and reports a failed save without dropping edits", async () => {
  state.save.mockRejectedValueOnce(new Error("offline"));
  render(<OrgTextToSpeechSettings org={{ id: "o1", text_to_speech: saved }} />);
  await expand();
  await userEvent.click(screen.getByRole("combobox", { name: "Provider" }));
  await userEvent.click(screen.getByRole("option", { name: "ElevenLabs" }));
  await userEvent.click(screen.getByRole("switch", { name: "Text to speech" }));
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await waitFor(() => expect(toast.error).toHaveBeenCalled());
  expect(screen.getByRole("combobox", { name: "Provider" })).toHaveTextContent("ElevenLabs");
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await waitFor(() => expect(state.save).toHaveBeenLastCalledWith("o1", { text_to_speech: null }));
});

it("keeps an omitted account voice null so the server can refuse it explicitly", async () => {
  render(<OrgTextToSpeechSettings org={{ id: "o1", text_to_speech: saved }} />);
  await expand();
  await userEvent.click(screen.getByRole("combobox", { name: "Provider" }));
  await userEvent.click(screen.getByRole("option", { name: "ElevenLabs" }));
  await userEvent.click(screen.getByRole("button", { name: "Choose key" }));
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await waitFor(() =>
    expect(state.save).toHaveBeenCalledWith("o1", {
      text_to_speech: {
        enabled: true,
        provider: "elevenlabs",
        model: "eleven_v4",
        voice: null,
        secret_id: "key-elevenlabs",
      },
    }),
  );
});

it("reopens the form on every header switch change after manual collapse", async () => {
  render(<OrgTextToSpeechSettings org={{ id: "o1", text_to_speech: saved }} />);
  const toggle = screen.getByRole("switch", { name: "Text to speech" });
  const heading = screen.getByRole("button", { name: "Text to speech" });
  await userEvent.click(toggle);
  expect(heading).toHaveAttribute("aria-expanded", "true");
  await userEvent.click(heading);
  expect(heading).toHaveAttribute("aria-expanded", "false");
  await userEvent.click(toggle);
  expect(heading).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("combobox", { name: "Provider" })).toBeVisible();
});
