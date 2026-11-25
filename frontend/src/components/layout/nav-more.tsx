"use client";

import { useState, type KeyboardEvent } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { Ellipsis, Pin, PinOff } from "lucide-react";

import { ConnectionHealthCount } from "@/components/layout/connection-health-count";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { stripLocale } from "@/lib/active-route";
import { navItemId, type MoreSection } from "@/lib/nav-pins";
import { isActive, type NavItem } from "@/lib/nav-sections";
import { cn } from "@/lib/utils";

const LINK = "[data-more-link]";

/** Move focus between rows with the arrow keys; Home and End jump to the ends. */
function moveFocus(event: KeyboardEvent<HTMLElement>) {
  const keys = ["ArrowDown", "ArrowUp", "Home", "End"];
  if (!keys.includes(event.key)) return;
  const links = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(LINK));
  const row = document.activeElement?.closest("[data-more-row]")?.querySelector(LINK);
  const at = links.findIndex((link) => link === row);
  const last = links.length - 1;
  const next =
    event.key === "Home"
      ? 0
      : event.key === "End"
        ? last
        : event.key === "ArrowDown"
          ? Math.min(at + 1, last)
          : Math.max(at - 1, 0);
  event.preventDefault();
  links[next]?.focus();
}

function MoreRow({
  item,
  pinned,
  pinsReady,
  onToggle,
  onNavigate,
}: {
  item: NavItem;
  pinned: boolean;
  pinsReady: boolean;
  onToggle: (id: string) => void;
  onNavigate: () => void;
}) {
  const t = useTranslations("nav");
  const pathname = usePathname();
  const active = item.exact ? stripLocale(pathname) === item.href : isActive(pathname, item.href);
  const label = t(item.labelKey);
  const PinIcon = pinned ? PinOff : Pin;
  return (
    <div data-more-row className="flex items-center gap-1">
      <Link
        href={item.href}
        data-more-link
        onClick={onNavigate}
        aria-current={active ? "page" : undefined}
        className={cn(
          "touch:min-h-11 focus-visible:ring-ring flex h-9 min-w-0 flex-1 items-center gap-2.5 rounded-lg px-2.5 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-inset",
          active
            ? "bg-accent text-foreground"
            : "text-foreground/80 hover:bg-foreground/5 hover:text-foreground",
        )}
      >
        <item.icon className="h-[18px] w-[18px] shrink-0" strokeWidth={1.75} aria-hidden />
        <span className="truncate">{label}</span>
        {item.count === "connectionHealth" && <ConnectionHealthCount collapsed={false} />}
      </Link>
      <button
        type="button"
        aria-pressed={pinned}
        disabled={!pinsReady}
        aria-label={t(pinned ? "unpinItem" : "pinItem", { item: label })}
        title={t(pinned ? "unpinItem" : "pinItem", { item: label })}
        onClick={() => onToggle(navItemId(item))}
        className="text-muted-foreground hover:bg-foreground/5 hover:text-foreground focus-visible:ring-ring touch:min-h-11 touch:min-w-11 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg outline-none focus-visible:ring-2"
      >
        <PinIcon className="size-4" aria-hidden />
      </button>
    </div>
  );
}

/**
 * Every entry the caller may see, grouped as the navigation table groups them,
 * each with a pin toggle. The popover is modal: focus is trapped inside, Esc
 * closes it and returns focus to the trigger. Following a link closes it;
 * toggling a pin does neither navigate nor close.
 */
export function NavMore({
  sections,
  pinnedIds,
  currentId,
  pinsReady,
  onToggle,
  onNavigate,
  collapsed,
}: {
  sections: MoreSection[];
  pinnedIds: readonly string[];
  /** The page on screen when it is not fixed or pinned; it already shows its own badge. */
  currentId: string | null;
  /** False until the saved pins have loaded: the pin buttons stay disabled. */
  pinsReady: boolean;
  onToggle: (id: string) => void;
  onNavigate?: () => void;
  collapsed: boolean;
}) {
  const t = useTranslations("nav");
  const [open, setOpen] = useState(false);
  const label = t("more");
  // A broken connection must stay visible when its row is not in the column:
  // neither pinned nor the page on screen, the More trigger carries the badge.
  const holdsHiddenHealth = sections.some((section) =>
    section.items.some(
      (item) =>
        item.count === "connectionHealth" &&
        !pinnedIds.includes(navItemId(item)) &&
        currentId !== navItemId(item),
    ),
  );

  return (
    <Popover open={open} onOpenChange={setOpen} modal>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-tour="nav-more"
          // On the rail the word is gone, so it moves to the tooltip and the name.
          title={collapsed ? label : undefined}
          aria-label={collapsed ? label : undefined}
          className={cn(
            "sidebar-nav-link touch:min-h-11 focus-visible:ring-ring text-foreground/80 hover:bg-foreground/5 hover:text-foreground relative flex shrink-0 items-center rounded-lg text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-inset",
            collapsed ? "touch:min-w-11 h-9 w-9 justify-center" : "h-9 gap-2.5 px-2.5",
          )}
        >
          <Ellipsis className="h-[18px] w-[18px] shrink-0" strokeWidth={1.75} aria-hidden />
          {collapsed ? null : <span className="truncate">{label}</span>}
          {holdsHiddenHealth && <ConnectionHealthCount collapsed={collapsed} />}
        </button>
      </PopoverTrigger>
      <PopoverContent
        side="right"
        align="start"
        collisionPadding={12}
        aria-label={label}
        onKeyDown={moveFocus}
        className="w-64 p-2"
      >
        {sections.map((section) => (
          <div
            key={section.labelKey ?? "admin"}
            className={cn(
              "flex flex-col gap-0.5",
              section.labelKey === null && "mt-1 border-t pt-1",
            )}
          >
            {section.labelKey ? (
              <div className="text-muted-foreground flex h-7 items-center px-2.5 text-xs font-medium">
                {t(section.labelKey)}
              </div>
            ) : null}
            {section.items.map((item) => (
              <MoreRow
                key={item.href}
                item={item}
                pinned={pinnedIds.includes(navItemId(item))}
                pinsReady={pinsReady}
                onToggle={onToggle}
                onNavigate={() => {
                  setOpen(false);
                  onNavigate?.();
                }}
              />
            ))}
          </div>
        ))}
      </PopoverContent>
    </Popover>
  );
}
