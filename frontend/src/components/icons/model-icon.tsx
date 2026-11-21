import { Cpu } from "lucide-react";

import { ProviderIcon } from "@/components/vault/provider-icon";
import { PickerMark } from "@/components/icons/picker-mark";

const MAKERS: Readonly<Record<string, string>> = {
  alibaba: "alibaba",
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
  const maker = namespace
    ? MAKERS[namespace]
    : provider
      ? MAKERS[provider.toLowerCase()]
      : undefined;
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
