"use client";

import { createElement, useState } from "react";
import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { MarkdownContent } from "@/components/chat/markdown-content";
import { BrandIcon, isBrandName } from "@/components/icons/brand-icon";
import { Monogram } from "@/components/icons/monogram";
import { serviceAction, spokenArgs } from "@/lib/approval-view";
import { Badge } from "@/components/ui/badge";
import { MCP_LOGOS } from "@/lib/mcp-logos.generated";
import { toolIcon } from "@/lib/step-icons";
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
    "bg-muted/35 border-border/70 flex size-8 shrink-0 items-center justify-center rounded-lg border",
    className,
  );
  if (service !== null && service !== "AgenticOS") {
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
  return (
    <span className={tile} aria-hidden>
      {createElement(toolIcon(toolName, entry?.kind), { className: "text-foreground/70 size-4" })}
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

/**
 * Which account the call acts as, where its binding names one: with two mailboxes
 * on one service, "Send in Gmail" is a question until it says from which.
 */
export function AccountBadge({ account }: { account: string | null | undefined }) {
  const t = useTranslations("pages.runs");
  if (!account) return null;
  return (
    <Badge variant="outline" className="max-w-full">
      <span className="truncate">{t("account", { account })}</span>
    </Badge>
  );
}

/** A value as text a person reads, nested values as lines of their own. */
function Value({ value, field }: { value: unknown; field: string }) {
  if (typeof value === "string") {
    if (field === "description" || field === "notes") {
      return (
        <div className="text-sm leading-relaxed [&_p]:my-1 [&_ul]:my-1">
          <MarkdownContent content={value} inertImages />
        </div>
      );
    }
    return <span className="break-words whitespace-pre-wrap">{value}</span>;
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

/** Put the content being approved before routing metadata and opaque IDs. */
function argumentOrder(name: string): number {
  if (name === "title" || name === "name") return 0;
  if (name === "description" || name === "notes") return 1;
  if (name === "id" || name.endsWith("_id")) return 3;
  return 2;
}

/** Each argument as its name in words and its value as text. */
function Fields({ args, nested = false }: { args: Record<string, unknown>; nested?: boolean }) {
  return (
    <dl className={cn("divide-border/60 divide-y text-sm", !nested && "rounded-lg border px-3")}>
      {Object.entries(args)
        .sort(([left], [right]) => argumentOrder(left) - argumentOrder(right))
        .map(([name, value]) => {
          const object = value !== null && typeof value === "object" && !Array.isArray(value);
          const prose = name === "description" || name === "notes";
          return (
            <div
              key={name}
              className={cn(
                "gap-x-4 gap-y-1.5 py-2.5",
                object || prose ? "space-y-2" : "grid @sm:grid-cols-[7rem_minmax(0,1fr)]",
              )}
            >
              <dt className="text-muted-foreground text-xs leading-5 font-medium">
                {titleWords(name)}
              </dt>
              <dd
                className={cn(
                  "min-w-0",
                  !prose && !object && /(^id$|_id$)/.test(name) && "font-mono text-xs break-all",
                )}
              >
                <Value value={value} field={name} />
              </dd>
            </div>
          );
        })}
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
        className="text-muted-foreground hover:text-foreground focus-visible:ring-ring inline-flex min-h-8 items-center gap-1 rounded-md text-xs font-medium focus-visible:ring-2 focus-visible:outline-none"
      >
        <ChevronRight
          className={cn("size-3.5 transition-transform", open && "rotate-90")}
          aria-hidden
        />
        {t("approvalDetails")}
      </button>
      {open && (
        <div className="max-h-[min(28dvh,18rem)] scrollbar-thin space-y-2 overflow-y-auto overscroll-contain pr-1">
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
