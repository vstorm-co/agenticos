import { Cpu } from "lucide-react";

import { ProviderIcon } from "@/components/vault/provider-icon";
import { PickerMark } from "@/components/icons/picker-mark";

const MAKERS: Readonly<Record<string, string>> = {
  alibaba: "alibaba",
  alibaba_coding_plan: "alibaba",
  github_copilot: "github",
  kimi_code: "moonshotai",
  ollama_cloud: "ollama",
  openai_chatgpt: "openai",
  amazon: "bedrock",
  anthropic: "anthropic",
  cohere: "cohere",
  deepseek: "deepseek",
  elevenlabs: "elevenlabs",
  glm: "zai",
  google: "google",
  google_cloud: "google",
  kimi: "moonshotai",
  meta: "meta",
  "meta-llama": "meta",
  microsoft: "microsoft",
  mistral: "mistral",
  mistralai: "mistral",
  moonshot: "moonshotai",
  moonshotai: "moonshotai",
  nousresearch: "nous_portal",
  nous_portal: "nous_portal",
  openai: "openai",
  openai_codex: "openai",
  qwen: "alibaba",
  "x-ai": "xai",
  xai: "xai",
  "z-ai": "zai",
  zai: "zai",
  zhipu: "zai",
  zhipuai: "zai",
};

/** Names returned by subscription gateways often have no vendor namespace. */
const FAMILIES: readonly (readonly [RegExp, string])[] = [
  [/^claude(?:[-_.]|$)/, "anthropic"],
  [/^gemini(?:[-_.]|$)/, "google"],
  [/^(?:gpt|chatgpt|codex|o[134])(?:[-_.]|$)/, "openai"],
  [/^(?:qwen|qwq)(?:\d|[-_.]|$)/, "alibaba"],
  [/^deepseek(?:[-_.]|$)/, "deepseek"],
  [/^(?:kimi|moonshot)(?:[-_.]|$)/, "moonshotai"],
  [/^(?:llama|meta-llama)(?:\d|[-_.]|$)/, "meta"],
  [/^(?:glm|chatglm)(?:\d|[-_.]|$)/, "zai"],
  [/^grok(?:[-_.]|$)/, "xai"],
  [/^(?:mistral|mixtral|codestral|ministral|magistral|devstral|pixtral)(?:[-_.]|$)/, "mistral"],
  [/^phi(?:[-_.]|$)/, "microsoft"],
  [/^nova(?:[-_.]|$)/, "bedrock"],
  [/^(?:minimax|abab)(?:\d|[-_.]|$)/, "minimax"],
  [/^command(?:[-_.]|$)/, "cohere"],
  [/^mercury(?:[-_.]|$)/, "inception"],
];

/** Model namespaces identify the maker; aggregators identify only the transport. */
export function ModelIcon({
  model,
  provider,
  className,
}: {
  model: string;
  provider?: string;
  className?: string;
}) {
  const namespace = /^([^/:]+)[/:]/.exec(model.trim())?.[1]?.toLowerCase();
  const name = model.trim().toLowerCase().split(/[/:]/).at(-1) ?? "";
  const family = FAMILIES.find(([pattern]) => pattern.test(name))?.[1];
  const maker =
    (namespace ? MAKERS[namespace] : undefined) ??
    family ??
    (!namespace && provider ? MAKERS[provider.toLowerCase()] : undefined);
  return (
    <PickerMark className={className}>
      {maker ? <ProviderIcon provider={maker} brand={maker} /> : <Cpu aria-hidden />}
    </PickerMark>
  );
}

/** The same model label is mirrored into Select's trigger and shown in its list. */
export function ModelLabel({
  model,
  provider,
  label,
}: {
  model: string;
  provider?: string;
  label: string;
}) {
  return (
    <span className="flex min-w-0 items-center gap-2">
      <ModelIcon model={model} provider={provider} />
      <span className="truncate">{label}</span>
    </span>
  );
}
