import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VoiceCard } from "./voice-card";
import type { SpeechToTextSpec } from "@/types/agents";

interface Org {
  id: string;
  chat_dictation: "off" | "browser" | "server";
  speech_to_text_provider: string | null;
  speech_to_text_model: string | null;
  speech_to_text_language: string | null;
}

const state = vi.hoisted(() => ({
  org: null as Org | null,
  providers: [] as {
    provider: string;
    name: string;
    credentialed: boolean;
    models: { id: string; name: string; description: string }[];
  }[],
}));

vi.mock("@/hooks", () => ({
  useOrganizationList: () => ({ data: state.org ? [state.org] : [] }),
}));
vi.mock("@/hooks/use-model-providers", () => ({
  useSpeechToTextProviders: () => ({ providers: state.providers, languages: ["en", "pl", "de"] }),
}));
vi.mock("@/stores", () => ({
  useOrgStore: (select: (s: { activeOrgId: string }) => unknown) =>
    select({ activeOrgId: "org-1" }),
}));

function model(id: string) {
  return { id, name: id, description: "" };
}

function mount(value: SpeechToTextSpec | null = null) {
  const onChange = vi.fn();
  render(<VoiceCard value={value} onChange={onChange} />);
  return { onChange };
}

beforeEach(() => {
  state.org = {
    id: "org-1",
    chat_dictation: "server",
    speech_to_text_provider: "openai",
    speech_to_text_model: "gpt-4o-transcribe",
    speech_to_text_language: "en",
  };
  state.providers = [
    { provider: "openai", name: "OpenAI", credentialed: false, models: [model("whisper-1")] },
    {
      provider: "groq",
      name: "Groq",
      credentialed: true,
      models: [model("whisper-large-v3"), model("whisper-large-v3-turbo")],
    },
  ];
});

describe("the agent's Voice card", () => {
  it("inherits by default and names what it inherits", () => {
    mount();

    expect(screen.getByRole("radio", { name: "Inherit" })).toHaveAttribute("aria-checked", "true");
    expect(
      screen.getByText("From the organization: OpenAI · gpt-4o-transcribe"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Language")).toHaveTextContent("Inherit (English)");
    expect(screen.queryByLabelText("Provider")).not.toBeInTheDocument();
  });

  it("chooses a whole pair at once, on a provider this organization can use", async () => {
    const { onChange } = mount();

    await userEvent.click(screen.getByRole("radio", { name: "Choose" }));

    // In the spec's order, with an explicit null, so the draft compares equal to
    // what the server stores.
    expect(onChange).toHaveBeenCalledWith({
      provider: "groq",
      model: "whisper-large-v3",
      language: null,
    });
    expect(Object.keys(onChange.mock.calls[0]![0])).toEqual(["provider", "model", "language"]);
  });

  it("marks a provider without credentials and keeps it unselectable", async () => {
    mount({ provider: "groq", model: "whisper-large-v3", language: null });

    await userEvent.click(screen.getByLabelText("Provider"));

    expect(screen.getByRole("option", { name: "OpenAI (no credentials)" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("switching provider takes that provider's first model", async () => {
    state.providers[0]!.credentialed = true;
    const { onChange } = mount({ provider: "groq", model: "whisper-large-v3", language: "pl" });

    await userEvent.click(screen.getByLabelText("Provider"));
    await userEvent.click(screen.getByRole("option", { name: "OpenAI" }));

    expect(onChange).toHaveBeenCalledWith({
      provider: "openai",
      model: "whisper-1",
      language: "pl",
    });
  });

  it("changes the model alone", async () => {
    const { onChange } = mount({ provider: "groq", model: "whisper-large-v3", language: null });

    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(screen.getByRole("option", { name: "whisper-large-v3-turbo" }));

    expect(onChange).toHaveBeenCalledWith({
      provider: "groq",
      model: "whisper-large-v3-turbo",
      language: null,
    });
  });

  it("pins a language on its own, keeping the organization's provider", async () => {
    const { onChange } = mount();

    await userEvent.click(screen.getByLabelText("Language"));
    await userEvent.click(screen.getByRole("option", { name: "Polish (pl)" }));

    expect(onChange).toHaveBeenCalledWith({ provider: null, model: null, language: "pl" });
  });

  it("returns to inherit as no block at all", async () => {
    const { onChange } = mount({ provider: "groq", model: "whisper-large-v3", language: null });

    await userEvent.click(screen.getByRole("radio", { name: "Inherit" }));

    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("keeps a pinned language when the pair goes back to inherit", async () => {
    const { onChange } = mount({ provider: "groq", model: "whisper-large-v3", language: "pl" });

    await userEvent.click(screen.getByRole("radio", { name: "Inherit" }));

    expect(onChange).toHaveBeenCalledWith({ provider: null, model: null, language: "pl" });
  });

  it("inheriting the language back clears the block", async () => {
    const { onChange } = mount({ provider: null, model: null, language: "pl" });

    await userEvent.click(screen.getByLabelText("Language"));
    await userEvent.click(screen.getByRole("option", { name: "Inherit (English)" }));

    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("says inheriting from an organization with no language is auto-detect", () => {
    state.org!.speech_to_text_language = null;
    mount();

    expect(screen.getByLabelText("Language")).toHaveTextContent("Inherit (auto-detect)");
  });

  it("says the override reaches only channel bots where chat dictates in the browser", () => {
    state.org!.chat_dictation = "browser";
    mount();

    expect(screen.getByText(/runs in the browser, so this only changes/)).toBeInTheDocument();
  });

  it("says the same where chat dictation is off", () => {
    state.org!.chat_dictation = "off";
    mount();

    expect(
      screen.getByText(/is off in this organization, so this only changes/),
    ).toBeInTheDocument();
  });

  it("says dictation needs a provider here when the organization has none", () => {
    state.org!.speech_to_text_provider = null;
    state.org!.speech_to_text_model = null;
    mount();

    expect(screen.getByText(/unavailable until you choose one here/)).toBeInTheDocument();
    expect(screen.getByText(/nothing to inherit/)).toBeInTheDocument();
  });

  it("says dictation runs on this agent's provider when the organization has none", () => {
    state.org!.speech_to_text_provider = null;
    state.org!.speech_to_text_model = null;
    mount({ provider: "groq", model: "whisper-large-v3", language: null });

    expect(screen.getByText(/runs on the one chosen here/)).toBeInTheDocument();
  });

  it("chooses the first offered provider when none has credentials", async () => {
    state.providers.forEach((entry) => (entry.credentialed = false));
    const { onChange } = mount();

    await userEvent.click(screen.getByRole("radio", { name: "Choose" }));

    expect(onChange).toHaveBeenCalledWith({
      provider: "openai",
      model: "whisper-1",
      language: null,
    });
  });

  it("cannot choose anything while the catalog offers nothing", () => {
    state.providers = [];
    state.org = null;
    mount();

    expect(screen.getByRole("radio", { name: "Choose" })).toBeDisabled();
    expect(screen.queryByText(/so this only changes/)).not.toBeInTheDocument();
  });

  it("is read-only for a caller who may not edit the agent", () => {
    render(<VoiceCard value={null} onChange={vi.fn()} disabled />);

    expect(screen.getByRole("radio", { name: "Choose" })).toBeDisabled();
    expect(screen.getByLabelText("Language")).toBeDisabled();
  });
});
