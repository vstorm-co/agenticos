"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { BrandIcon, isBrandName } from "@/components/icons/brand-icon";
import { Monogram } from "@/components/icons/monogram";
import { serviceAction, spokenArgs } from "@/lib/approval-view";
import { MCP_LOGOS } from "@/lib/mcp-logos.generated";
import { STEP_ICONS } from "@/lib/step-icons";
import { toolEntry, toolLabel } from "@/lib/tool-catalog";
import { titleWords } from "@/lib/tool-steps";
import { cn } from "@/lib/utils";

/** A service's own logo, in colour, by any MCP host that carries its name. */
function serviceLogo(service: string): string | null {
  const key = service.toLowerCase();
  const host = Object.keys(MCP_LOGOS).find((name) => name.split(".").includes(key));
  return host === undefined ? null : MCP_LOGOS[host]!;
}

/**
 * The mark of what is asking: the service's logo for a tool from an MCP server,
 * the kind of thing a built-in tool does for one of ours.
 */
export function ToolMark({ toolName, className }: { toolName: string; className?: string }) {
  const entry = toolEntry(toolName);
  const { service } = serviceAction(toolName, entry !== null);
  const tile = cn(
    "bg-background ring-foreground/10 flex size-9 shrink-0 items-center justify-center rounded-xl ring-1",
    className,
  );
  if (service !== null) {
    const logo = serviceLogo(service);
    return (
      <span className={tile} aria-hidden>
        {logo !== null ? (
          // eslint-disable-next-line @next/next/no-img-element -- a baked data URI
          <img src={logo} alt="" className="size-5 rounded-[22%] object-contain" />
        ) : isBrandName(service) ? (
          <BrandIcon name={service} className="size-5" />
        ) : (
          <Monogram label={service} className="size-5" />
        )}
      </span>
    );
  }
  const Icon = STEP_ICONS[entry?.kind ?? "tool"];
  return (
    <span className={tile} aria-hidden>
      <Icon className="text-foreground/70 size-4" />
    </span>
  );
}

/**
 * What a call does, as words a person reads: "Search in Notion", "Run Python".
 *
 * Capitalised as a label; a sentence that puts it after "wants to" lowers the
 * first letter itself.
 */
export function useActionPhrase(): (toolName: string) => string {
  const t = useTranslations("pages.runs");
  const tTools = useTranslations("chat.tools");
  return (toolName: string) => {
    const known = toolEntry(toolName) !== null;
    const { service, action } = serviceAction(toolName, known);
    return service === null
      ? toolLabel(toolName, tTools)
      : t("actionInService", { action, service: titleWords(service) });
  };
}

/** A value as text a person reads, nested values as lines of their own. */
function Value({ value }: { value: unknown }) {
  if (typeof value === "string") {
    return <span className="line-clamp-6 break-words whitespace-pre-wrap">{value}</span>;
  }
  if (Array.isArray(value) && value.every((item) => typeof item !== "object" || item === null)) {
    return <span className="break-words">{value.map(String).join(", ")}</span>;
  }
  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    return <Fields args={value as Record<string, unknown>} nested />;
  }
  if (Array.isArray(value)) {
    return <pre className="overflow-x-auto text-xs">{JSON.stringify(value, null, 2)}</pre>;
  }
  return <span className="font-mono text-xs">{String(value)}</span>;
}

/** Each argument as its name in words and its value as text. */
function Fields({ args, nested = false }: { args: Record<string, unknown>; nested?: boolean }) {
  return (
    <dl
      className={cn(
        "text-sm",
        nested ? "space-y-1" : "bg-muted/40 divide-foreground/[0.06] divide-y rounded-lg",
      )}
    >
      {Object.entries(args).map(([name, value]) => (
        <div
          key={name}
          className={cn(
            "grid gap-1",
            nested
              ? "grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-2"
              : "px-3 py-2 sm:grid-cols-[9rem_minmax(0,1fr)] sm:gap-3",
          )}
        >
          <dt className="text-muted-foreground text-xs sm:pt-0.5">{titleWords(name)}</dt>
          <dd className="min-w-0">
            <Value value={value} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * Everything the call will be given, folded until somebody asks.
 *
 * The sentence and the one telling argument above it are what a decision is
 * made on; this is the evidence for the person who wants it. The empty fields
 * an MCP schema always sends are left out, and the tool's own id closes it for
 * whoever needs to look it up.
 */
export function ApprovalDetails({
  toolName,
  args,
}: {
  toolName: string;
  args: Record<string, unknown>;
}) {
  const t = useTranslations("pages.runs");
  const [open, setOpen] = useState(false);
  const fields = spokenArgs(args);
  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => setOpen((shown) => !shown)}
        aria-expanded={open}
        className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs font-medium"
      >
        <ChevronRight
          className={cn("size-3.5 transition-transform", open && "rotate-90")}
          aria-hidden
        />
        {t("approvalDetails")}
      </button>
      {open && (
        <div className="space-y-2">
          {Object.keys(fields).length > 0 ? (
            <Fields args={fields} />
          ) : (
            <p className="text-muted-foreground text-xs">{t("approvalNoArguments")}</p>
          )}
          <p className="text-muted-foreground font-mono text-xs">{toolName}</p>
        </div>
      )}
    </div>
  );
}
