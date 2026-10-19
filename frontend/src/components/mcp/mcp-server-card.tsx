"use client";

import type { ReactNode } from "react";

import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
import { Card, CardContent } from "@/components/ui";
import { cn } from "@/lib/utils";

interface McpServerCardProps {
  name: string;
  icon: string | null;
  /** Drawn in place of the catalog icon - the deployment's own mark, which no catalog holds. */
  mark?: ReactNode;
  url: string | null;
  description: string;
  /** Beside the name, for the one thing worth saying there - a registry server. */
  badge?: ReactNode;
  /** Top right: the Builder's switch. */
  headerAction?: ReactNode;
  /** Where the server stands, as one line at the foot. */
  status: ReactNode;
  /** The foot's right end: the page's verbs, where it has any. */
  actions?: ReactNode;
  /** The Builder's card for a server this agent uses. */
  selected?: boolean;
  /** Clicking the card's body, where the card is more than its controls. */
  onOpen?: () => void;
  dataTour?: string;
}

/**
 * One MCP server, drawn the same on the servers page and in the Builder, and
 * the same whatever state it is in.
 *
 * Every card is a logo, a name, two lines of what it does, and one foot: where
 * it stands on the left, the verbs on the right. The address, the category,
 * the documentation link and the date of the last catalog check used to sit
 * in between, and whether a card had a Connect, a settings button or nothing
 * at all depended on its state, so no two cards in a row looked alike. The
 * address and the documentation are one click away, in the server's own
 * dialog.
 */
export function McpServerCard({
  name,
  icon,
  mark,
  url,
  description,
  badge,
  headerAction,
  status,
  actions,
  selected = false,
  onOpen,
  dataTour,
}: McpServerCardProps) {
  return (
    <Card
      role="group"
      aria-label={name}
      className={cn(
        "h-full transition-colors",
        selected && "border-foreground/40",
        onOpen && "hover:border-foreground/25 cursor-pointer",
      )}
      data-tour={dataTour}
      onClick={
        onOpen &&
        ((event) => {
          // The card's own controls act for themselves; only the rest of it opens.
          if (!(event.target as HTMLElement).closest("button, a, [role=switch]")) onOpen();
        })
      }
    >
      <CardContent className="flex h-full flex-col gap-3 p-4">
        <div className="flex items-start gap-3">
          {/* A white tile in both themes: the logos are drawn for a light ground. */}
          <span className="border-foreground/10 grid size-10 shrink-0 place-items-center rounded-xl border bg-white">
            {mark ?? (
              <McpServerIcon
                icon={icon}
                name={name}
                url={url}
                className="size-6 text-neutral-900"
              />
            )}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="truncate text-sm font-medium">{name}</span>
              {badge}
            </div>
            <p className="text-muted-foreground mt-0.5 line-clamp-2 text-[13px] leading-snug">
              {description}
            </p>
          </div>
          {headerAction && <span className="shrink-0">{headerAction}</span>}
        </div>
        <div className="mt-auto flex min-h-8 min-w-0 items-center gap-2">
          <span className="text-muted-foreground flex min-w-0 flex-1 items-center gap-1.5 text-xs">
            {status}
          </span>
          {actions && <span className="flex shrink-0 items-center gap-1">{actions}</span>}
        </div>
      </CardContent>
    </Card>
  );
}

/** The foot's left end: a dot for whether anything answers, and what that is. */
export function CardStatus({
  tone,
  children,
  onClick,
  label,
}: {
  tone: "live" | "off" | "error";
  children: ReactNode;
  /** Where the line opens the server's accounts or settings - the keyboard's way in. */
  onClick?: () => void;
  label?: string;
}) {
  const body = (
    <>
      <span
        aria-hidden
        className={cn(
          "size-1.5 shrink-0 rounded-full",
          tone === "live"
            ? "bg-success"
            : tone === "error"
              ? "bg-destructive"
              : "bg-muted-foreground/35",
        )}
      />
      <span className="truncate">{children}</span>
    </>
  );
  if (onClick === undefined) return body;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="hover:text-foreground flex min-w-0 items-center gap-1.5 rounded-sm underline-offset-2 hover:underline"
    >
      {body}
    </button>
  );
}
