"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import {
  Brain,
  Building2,
  ChevronRight,
  Lock,
  MessageSquare,
  Mic,
  Settings2,
  Sparkles,
  UserRound,
} from "lucide-react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { AgentStatusBadge } from "@/components/agents/status-badge";
import { ModelSettingsForm } from "@/components/agents/model-settings-form";
import { AnswerFormatForm } from "@/components/agents/answer-format-form";
import { StartersPanel } from "@/components/agents/starters-panel";
import { Badge, Button, Input, Label, NativeSelect, Switch } from "@/components/ui";
import { MoreOptions } from "@/components/ui/more-options";
import { cn } from "@/lib/utils";
import type { AgentStatus, ModelSettingsSpec } from "@/types/agents";

type Variant = "profile" | "directory" | "compact";
type Section = "model" | "thinking" | "answer" | "voice" | "starters" | "identity";
const SECTIONS = [
  {
    id: "model",
    title: "Model & access",
    icon: Settings2,
    hint: "Model, credentials and generation settings",
  },
  { id: "thinking", title: "Thinking", icon: Brain, hint: "Reasoning effort and response depth" },
  {
    id: "answer",
    title: "Answer format",
    icon: MessageSquare,
    hint: "Prose or a structured answer",
  },
  { id: "voice", title: "Voice", icon: Mic, hint: "Dictation, spoken replies and calls" },
  {
    id: "starters",
    title: "Suggested prompts",
    icon: Sparkles,
    hint: "Help people start a useful conversation",
  },
  {
    id: "identity",
    title: "Identity & discovery",
    icon: UserRound,
    hint: "Name, description and visibility",
  },
] as const;
const SAMPLES: {
  name: string;
  description: string;
  status: AgentStatus;
  shared: boolean;
  attention?: boolean;
}[] = [
  {
    name: "AgenticOS",
    description:
      "Research, write and get work done with your connected apps, files and personal context.",
    status: "published",
    shared: true,
  },
  {
    name: "Sales assistant",
    description: "Prepare account briefs, draft follow-ups and keep customer conversations moving.",
    status: "published",
    shared: false,
    attention: true,
  },
  {
    name: "Knowledge guide",
    description: "Find answers in company knowledge and explain the sources behind each answer.",
    status: "draft",
    shared: true,
  },
];

/** Development-only comparison. Every editable value lives in this component, never an agent spec. */
export function AgentDesignPreview({ variant, build }: { variant: Variant; build: boolean }) {
  const [selected, setSelected] = useState<Section>("model");
  const [model, setModel] = useState("claude-sonnet-5");
  const [access, setAccess] = useState("organization");
  const [settings, setSettings] = useState<ModelSettingsSpec>({});
  const [thinking, setThinking] = useState(true);
  const [effort, setEffort] = useState("medium");
  const [schema, setSchema] = useState<Record<string, unknown> | null>(null);
  const [voice, setVoice] = useState(false);
  const [starters, setStarters] = useState(["Help me plan my day", "Summarize my latest messages"]);
  const [name, setName] = useState("AgenticOS");
  const [description, setDescription] = useState(SAMPLES[0]?.description ?? "");
  const [visibility, setVisibility] = useState("organization");
  const content: Record<Section, ReactNode> = {
    model: (
      <div className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="preview-model">Model</Label>
            <NativeSelect
              id="preview-model"
              value={model}
              onChange={(event) => setModel(event.target.value)}
            >
              <option value="claude-sonnet-5">Anthropic · Claude Sonnet 5</option>
              <option value="gpt-5.5">OpenAI · GPT-5.5</option>
            </NativeSelect>
          </div>
          <div className="space-y-2">
            <Label htmlFor="preview-access">Model access</Label>
            <NativeSelect
              id="preview-access"
              value={access}
              onChange={(event) => setAccess(event.target.value)}
            >
              <option value="organization">Organization key</option>
              <option value="personal">Each person’s key</option>
            </NativeSelect>
          </div>
        </div>
        <MoreOptions label="Generation settings">
          <ModelSettingsForm value={settings} onChange={setSettings} />
        </MoreOptions>
      </div>
    ),
    thinking: (
      <div className="space-y-5">
        <label className="flex items-center justify-between gap-4 text-sm">
          Allow reasoning
          <Switch checked={thinking} onCheckedChange={setThinking} />
        </label>
        {thinking && (
          <div className="space-y-2">
            <Label htmlFor="preview-effort">Effort</Label>
            <NativeSelect
              id="preview-effort"
              value={effort}
              onChange={(event) => setEffort(event.target.value)}
            >
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </NativeSelect>
          </div>
        )}
      </div>
    ),
    answer: <AnswerFormatForm value={schema} onChange={setSchema} />,
    voice: (
      <div className="space-y-4">
        <label className="flex items-center justify-between gap-4 text-sm">
          Use organization voice defaults
          <Switch checked={voice} onCheckedChange={setVoice} />
        </label>
        <p className="text-muted-foreground text-sm">
          {voice
            ? "Dictation and spoken replies inherit the organization settings."
            : "Voice is off for this preview."}
        </p>
      </div>
    ),
    starters: <StartersPanel starters={starters} disabled={false} onChange={setStarters} />,
    identity: (
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="preview-name">Name</Label>
          <Input id="preview-name" value={name} onChange={(event) => setName(event.target.value)} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="preview-description">Description</Label>
          <Input
            id="preview-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="preview-visibility">Visibility</Label>
          <NativeSelect
            id="preview-visibility"
            value={visibility}
            onChange={(event) => setVisibility(event.target.value)}
          >
            <option value="organization">Organization</option>
            <option value="private">Private</option>
          </NativeSelect>
        </div>
      </div>
    ),
  };
  return (
    <main
      className="mx-auto w-full max-w-6xl space-y-8 p-5 sm:p-8"
      data-agent-design-preview={variant}
    >
      <header className="space-y-3">
        <p className="text-muted-foreground text-xs">
          Design preview · local state only · no agent changes are saved
        </p>
        <h1 className="text-2xl font-semibold">{build ? "Agent builder" : "Agent directory"}</h1>
        <div className="flex flex-wrap gap-2">
          {(["profile", "directory", "compact"] as const).map((value) => (
            <Button
              key={value}
              asChild
              variant={variant === value ? "default" : "outline"}
              size="sm"
            >
              <Link href={`/dev/agent-designs?variant=${value}${build ? "&section=build" : ""}`}>
                {value === "profile"
                  ? "A · Cards"
                  : value === "directory"
                    ? "B · Outline"
                    : "C · Workspace"}
              </Link>
            </Button>
          ))}
          <Button asChild size="sm" variant="ghost">
            <Link href={`/dev/agent-designs?variant=${variant}${build ? "" : "&section=build"}`}>
              {build ? "Compare agent cards" : "Compare builder layouts"}
            </Link>
          </Button>
        </div>
      </header>
      {!build ? (
        <div
          className={cn("grid gap-4", variant !== "directory" && "md:grid-cols-2 xl:grid-cols-3")}
        >
          {SAMPLES.map((agent, index) => (
            <article
              key={agent.name}
              className={cn(
                "bg-card rounded-2xl border",
                variant === "profile"
                  ? "flex min-h-64 flex-col p-5"
                  : variant === "directory"
                    ? "grid items-center gap-4 p-4 sm:grid-cols-[minmax(180px,1fr)_2fr_auto]"
                    : "space-y-4 p-4",
              )}
            >
              <div className="flex items-start gap-3">
                <AgentAvatar
                  agentId={`preview-${index}`}
                  slug={agent.name.toLowerCase()}
                  colorSlot={index}
                  size={variant === "profile" ? "lg" : "sm"}
                />
                <div className="min-w-0">
                  <h2 className="truncate font-semibold">{agent.name}</h2>
                  <p className="text-muted-foreground mt-1 flex items-center gap-1.5 text-xs">
                    {agent.shared ? <Building2 className="size-3" /> : <Lock className="size-3" />}
                    {agent.shared ? "Organization" : "Private"}
                  </p>
                </div>
                {variant === "compact" && (
                  <div className="ml-auto">
                    <AgentStatusBadge status={agent.status} />
                  </div>
                )}
              </div>
              <p
                className={cn(
                  "text-muted-foreground text-sm leading-relaxed",
                  variant === "profile" && "mt-5 mb-6 flex-1",
                  variant === "compact" && "line-clamp-2",
                )}
              >
                {agent.description}
              </p>
              <div
                className={cn(
                  "flex flex-wrap items-center gap-2",
                  variant === "profile" && "border-t pt-4",
                )}
              >
                {variant !== "compact" && <AgentStatusBadge status={agent.status} />}
                {agent.attention && <Badge variant="warning">Needs attention</Badge>}
                <span className="text-muted-foreground ml-auto text-[11px]">Edited today</span>
              </div>
            </article>
          ))}
        </div>
      ) : variant === "compact" ? (
        <div className="grid items-start gap-6 md:grid-cols-[220px_minmax(0,1fr)]">
          <nav className="bg-card space-y-1 rounded-2xl border p-2" aria-label="Builder sections">
            {SECTIONS.map((section) => (
              <button
                key={section.id}
                type="button"
                aria-current={selected === section.id ? "page" : undefined}
                onClick={() => setSelected(section.id)}
                className={cn(
                  "flex min-h-11 w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm",
                  selected === section.id
                    ? "bg-foreground/8 font-medium"
                    : "text-muted-foreground hover:bg-muted",
                )}
              >
                <section.icon className="size-4" />
                {section.title}
              </button>
            ))}
          </nav>
          <PreviewSection
            title={SECTIONS.find((section) => section.id === selected)?.title ?? "Model"}
          >
            {content[selected]}
          </PreviewSection>
        </div>
      ) : variant === "directory" ? (
        <div className="bg-card divide-y overflow-hidden rounded-2xl border">
          {SECTIONS.map((section) => (
            <div key={section.id} className="p-5">
              <MoreOptions
                label={`${section.title} · ${section.hint}`}
                defaultOpen={section.id === "model"}
              >
                {content[section.id]}
              </MoreOptions>
            </div>
          ))}
        </div>
      ) : (
        <div className="grid items-start gap-5 lg:grid-cols-2">
          {SECTIONS.map((section) => (
            <div key={section.id} className={section.id === "model" ? "lg:col-span-2" : ""}>
              <PreviewSection title={section.title} hint={section.hint}>
                {content[section.id]}
              </PreviewSection>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}

function PreviewSection({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <section className="bg-card space-y-5 rounded-2xl border p-5 sm:p-6">
      <header>
        <h2 className="flex items-center gap-2 text-base font-semibold">
          <ChevronRight className="text-muted-foreground size-4" />
          {title}
        </h2>
        {hint && <p className="text-muted-foreground mt-1 text-sm">{hint}</p>}
      </header>
      {children}
    </section>
  );
}
