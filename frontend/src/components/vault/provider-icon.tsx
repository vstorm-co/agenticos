"use client";

import type { IconType } from "@lobehub/icons/es/types";

import AlibabaCloud from "@lobehub/icons/es/AlibabaCloud/components/Color";
import Anthropic from "@lobehub/icons/es/Anthropic/components/Mono";
import Azure from "@lobehub/icons/es/Azure/components/Color";
import Bedrock from "@lobehub/icons/es/Bedrock/components/Color";
import Cerebras from "@lobehub/icons/es/Cerebras/components/Color";
import DeepSeek from "@lobehub/icons/es/DeepSeek/components/Color";
import Fireworks from "@lobehub/icons/es/Fireworks/components/Color";
import Gemini from "@lobehub/icons/es/Gemini/components/Color";
import Github from "@lobehub/icons/es/Github/components/Mono";
import Groq from "@lobehub/icons/es/Groq/components/Mono";
import Mistral from "@lobehub/icons/es/Mistral/components/Color";
import Moonshot from "@lobehub/icons/es/Moonshot/components/Mono";
import Nebius from "@lobehub/icons/es/Nebius/components/Mono";
import Ollama from "@lobehub/icons/es/Ollama/components/Mono";
import OpenAI from "@lobehub/icons/es/OpenAI/components/Mono";
import OpenRouter from "@lobehub/icons/es/OpenRouter/components/Color";
import SambaNova from "@lobehub/icons/es/SambaNova/components/Color";
import Together from "@lobehub/icons/es/Together/components/Color";
import Vercel from "@lobehub/icons/es/Vercel/components/Mono";
import VertexAI from "@lobehub/icons/es/VertexAI/components/Color";
import ZAI from "@lobehub/icons/es/ZAI/components/Mono";

import { Monogram } from "@/components/icons/monogram";
import { cn } from "@/lib/utils";

/**
 * The brand mark for a provider id from `GET /providers/catalog`.
 *
 * Two decisions worth knowing about.
 *
 * **Why the deep import.** `@lobehub/icons/es/OpenAI` is the package's per-icon
 * entry, but it pulls in that icon's `Avatar`, which pulls in `@lobehub/ui` and
 * `antd-style` — an Ant Design runtime this app does not have and will not
 * take on for a 24×24 logo. The leaf component is the whole icon and imports
 * nothing but React, so that is what is imported. Never
 * `from "@lobehub/icons"`: the barrel is 332 brands and the same Ant runtime.
 *
 * **Why some are coloured and some are not.** Each brand ships `Color` only
 * when its logo has colour; OpenAI, Anthropic, GitHub, Vercel and Ollama are
 * monochrome marks and ship `Mono`, which inherits `currentColor`. Taking each
 * brand as it comes is the reason this reads as a set rather than as a page
 * where half the logos failed to load.
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

interface ProviderIconProps {
  /** The catalog id, e.g. `openai` or `google_cloud`. */
  provider: string;
  className?: string;
}

/**
 * A provider's logo, or a monogram for one the icon set does not carry.
 *
 * Three of the platform's providers have no brand mark anywhere (Heroku AI,
 * OVHcloud, a LiteLLM proxy), and a deployment gains a provider whenever
 * Pydantic AI does — so the missing case is the normal case, not the error
 * case. It renders as a bordered initial in the same square the logos occupy,
 * which reads as deliberate; a broken image or a blank gap does not.
 *
 * Always decorative. Every place this is used prints the provider beside it,
 * and an icon that repeated the name would make a screen reader say it twice.
 */
export function ProviderIcon({ provider, className }: ProviderIconProps) {
  const Mark = MARKS[provider];
  const size = cn("h-5 w-5 shrink-0", className);

  if (Mark) return <Mark aria-hidden className={size} />;

  return <Monogram label={provider} className={size} />;
}
