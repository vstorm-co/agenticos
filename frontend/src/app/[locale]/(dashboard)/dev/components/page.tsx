"use client";

import { useState } from "react";
import { notFound } from "next/navigation";
import { Sparkles, Trash2 } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { StatCard } from "@/components/dashboard/stat-card";
import { EmptyState } from "@/components/states";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  ConfirmDialog,
  FormField,
  IconButton,
  Input,
  SectionHeading,
} from "@/components/ui";

/**
 * Dev-only component gallery - a lightweight stand-in for Storybook that keeps
 * the design system honest. Renders the core primitives in one place so visual
 * regressions are easy to spot. Hidden in production builds.
 */
export default function ComponentGalleryPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <Gallery />;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-border bg-card rounded-xl border p-5">
      <SectionHeading title={title} className="mb-4" />
      <div className="flex flex-wrap items-start gap-3">{children}</div>
    </section>
  );
}

/** The accent ramp from globals.css. Only this page names palette steps. */
const BRAND_RAMP = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950] as const;

/** Accent roles, and what each is allowed to mean. Mirrors globals.css. */
const BRAND_ROLES: readonly { token: string; means: string }[] = [
  { token: "--color-brand", means: "primary action · checked control · accent text" },
  { token: "--color-brand-hover", means: "its hover" },
  { token: "--color-brand-active", means: "its press" },
  { token: "--color-brand-subtle", means: "selected row · tinted panel" },
  { token: "--color-brand-subtle-hover", means: "that surface, hovered" },
  { token: "--color-brand-line", means: "edge of a tinted panel" },
  { token: "--color-chart", means: "data strokes and fills" },
];

function AccentPalette() {
  return (
    <div className="w-full space-y-4">
      <div className="flex w-full gap-1">
        {BRAND_RAMP.map((step) => (
          <div key={step} className="flex-1 space-y-1">
            <div
              className="border-border h-10 rounded-md border"
              style={{ background: `var(--brand-${step})` }}
            />
            <p className="text-muted-foreground text-center font-mono text-[10px]">{step}</p>
          </div>
        ))}
      </div>
      <ul className="space-y-1.5">
        {BRAND_ROLES.map(({ token, means }) => (
          <li key={token} className="flex items-center gap-3 text-xs">
            <span
              className="border-border h-4 w-4 shrink-0 rounded border"
              style={{ background: `var(${token})` }}
            />
            <code className="font-mono">{token}</code>
            <span className="text-muted-foreground">{means}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Gallery() {
  const [confirmOpen, setConfirmOpen] = useState(false);

  return (
    <div className="space-y-6 pb-8">
      <PageHeader
        title="Component gallery"
        description="Core design-system primitives, in one place."
      />

      <Section title="Accent palette - change --brand-h in globals.css to retheme">
        <AccentPalette />
      </Section>

      <Section title="Button variants">
        {(["default", "secondary", "outline", "ghost", "destructive", "link"] as const).map((v) => (
          <Button key={v} variant={v}>
            {v}
          </Button>
        ))}
      </Section>

      <Section title="Button sizes">
        <Button size="sm">sm</Button>
        <Button size="default">default</Button>
        <Button size="lg">lg</Button>
        <IconButton aria-label="Sparkles" size="icon-sm">
          <Sparkles />
        </IconButton>
        <IconButton aria-label="Delete" size="icon">
          <Trash2 />
        </IconButton>
      </Section>

      <Section title="Badges">
        {(["default", "secondary", "outline", "destructive"] as const).map((v) => (
          <Badge key={v} variant={v}>
            {v}
          </Badge>
        ))}
      </Section>

      <Section title="Alerts">
        <div className="w-full space-y-2">
          {(["default", "info", "warning", "destructive"] as const).map((v) => (
            <Alert key={v} variant={v}>
              <AlertTitle>{v} alert</AlertTitle>
              <AlertDescription>Something worth the user&apos;s attention.</AlertDescription>
            </Alert>
          ))}
        </div>
      </Section>

      <Section title="FormField">
        <div className="w-full max-w-sm space-y-4">
          <FormField label="Display name" htmlFor="g-name" description="Visible to teammates.">
            <Input id="g-name" placeholder="Ada Lovelace" />
          </FormField>
          <FormField label="Email" htmlFor="g-email" error="That email is already taken." required>
            <Input id="g-email" type="email" defaultValue="taken@example.com" />
          </FormField>
        </div>
      </Section>

      <Section title="StatCard">
        <div className="grid w-full gap-3 sm:grid-cols-3">
          <StatCard label="Credits" value="1,240" delta={12.5} deltaLabel="vs prior 7d" />
          <StatCard label="Conversations" value="38" footer="across all chats" />
          <StatCard label="Knowledge base" value="0" unit="vectors" />
        </div>
      </Section>

      <Section title="EmptyState">
        <div className="w-full">
          <EmptyState
            icon={Sparkles}
            title="Nothing here yet"
            description="Create your first item to get started."
            cta={{ label: "Create", onClick: () => {} }}
          />
        </div>
      </Section>

      <Section title="ConfirmDialog">
        <Button variant="destructive" onClick={() => setConfirmOpen(true)}>
          Delete something…
        </Button>
        <ConfirmDialog
          open={confirmOpen}
          onOpenChange={setConfirmOpen}
          title="Delete this resource?"
          description="This action cannot be undone."
          destructive
          confirmText="DELETE"
          confirmLabel="Delete"
          onConfirm={() => setConfirmOpen(false)}
        />
      </Section>
    </div>
  );
}
