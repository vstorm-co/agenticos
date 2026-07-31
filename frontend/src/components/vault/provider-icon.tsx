"use client";

import type { IconType } from "@lobehub/icons/es/types";

import AlibabaCloud from "@lobehub/icons/es/AlibabaCloud/components/Mono";
import Anthropic from "@lobehub/icons/es/Anthropic/components/Mono";
import Azure from "@lobehub/icons/es/Azure/components/Mono";
import Bedrock from "@lobehub/icons/es/Bedrock/components/Mono";
import Cerebras from "@lobehub/icons/es/Cerebras/components/Mono";
import DeepSeek from "@lobehub/icons/es/DeepSeek/components/Mono";
import Fireworks from "@lobehub/icons/es/Fireworks/components/Mono";
import Gemini from "@lobehub/icons/es/Gemini/components/Mono";
import Github from "@lobehub/icons/es/Github/components/Mono";
import Groq from "@lobehub/icons/es/Groq/components/Mono";
import Mistral from "@lobehub/icons/es/Mistral/components/Mono";
import Moonshot from "@lobehub/icons/es/Moonshot/components/Mono";
import Nebius from "@lobehub/icons/es/Nebius/components/Mono";
import Ollama from "@lobehub/icons/es/Ollama/components/Mono";
import OpenAI from "@lobehub/icons/es/OpenAI/components/Mono";
import OpenRouter from "@lobehub/icons/es/OpenRouter/components/Mono";
import SambaNova from "@lobehub/icons/es/SambaNova/components/Mono";
import Together from "@lobehub/icons/es/Together/components/Mono";
import Vercel from "@lobehub/icons/es/Vercel/components/Mono";
import VertexAI from "@lobehub/icons/es/VertexAI/components/Mono";
import ZAI from "@lobehub/icons/es/ZAI/components/Mono";

import { CustomMark, useCustomIcons } from "@/components/icons/custom-icons";
import { Monogram } from "@/components/icons/monogram";
import { cn } from "@/lib/utils";

/**
 * The brand mark for a provider id from `GET /providers/catalog`.
 *
 * Two decisions worth knowing about.
 *
 * **Why the deep import.** `@lobehub/icons/es/OpenAI` is the package's per-icon
 * entry, but it pulls in that icon's `Avatar`, which pulls in `@lobehub/ui` and
 * `antd-style` - an Ant Design runtime this app does not have and will not
 * take on for a 24×24 logo. The leaf component is the whole icon and imports
 * nothing but React, so that is what is imported. Never
 * `from "@lobehub/icons"`: the barrel is 332 brands and the same Ant runtime.
 *
 * **Why `Mono` for every brand, including the ones that ship `Color`.** The
 * console's brand marks are monochrome `currentColor` - the MCP catalog, the
 * connectors and the sign-in buttons all draw from Simple Icons that way - and
 * a column where Gemini is four colours while OpenAI is ink reads as two
 * different UIs. `Mono` also follows the theme for free; `Color` marks have to
 * hope their palette survives a dark surface. `provider-icon.test.tsx` pins
 * every mark to this.
 */
const MARKS: Readonly<Record<string, IconType>> = {
  alibaba: AlibabaCloud,
  anthropic: Anthropic,
  azure: Azure,
  bedrock: Bedrock,
  cerebras: Cerebras,
  deepseek: DeepSeek,
  fireworks: Fireworks,
  github: Github,
  google: Gemini,
  google_cloud: VertexAI,
  groq: Groq,
  mistral: Mistral,
  moonshotai: Moonshot,
  nebius: Nebius,
  ollama: Ollama,
  openai: OpenAI,
  openrouter: OpenRouter,
  sambanova: SambaNova,
  together: Together,
  vercel: Vercel,
  zai: ZAI,
};

/** Every id with a mark - what the monochrome pin in the test iterates. */
export const MARKED_PROVIDERS: readonly string[] = Object.keys(MARKS);

interface ProviderIconProps {
  /** The catalog id, e.g. `openai` or `google_cloud`. */
  provider: string;
  className?: string;
}

/**
 * A provider's logo: the compiled-in mark, a custom mark the deployment ships
 * under this id, or a monogram.
 *
 * Three of the platform's providers have no brand mark anywhere (Heroku AI,
 * OVHcloud, a LiteLLM proxy), and a deployment gains a provider whenever
 * Pydantic AI does - so the missing case is the normal case, not the error
 * case. The middle step is a deployment's answer to it: drop `heroku.svg`
 * into the backend's catalog icons and this draws it, as a `currentColor`
 * silhouette that keeps the monochrome register. The monogram remains the
 * floor - a bordered initial reads as deliberate; a blank gap does not.
 *
 * Always decorative. Every place this is used prints the provider beside it,
 * and an icon that repeated the name would make a screen reader say it twice.
 */
export function ProviderIcon({ provider, className }: ProviderIconProps) {
  const custom = useCustomIcons();
  const Mark = MARKS[provider];
  const size = cn("h-5 w-5 shrink-0", className);

  if (Mark) return <Mark aria-hidden className={size} />;
  if (custom.has(provider)) return <CustomMark name={provider} className={size} />;

  return <Monogram label={provider} className={size} />;
}
