"use client";

import Link from "next/link";
import { ArrowUpRight, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { KIND_LABEL, MODE_LABEL, type MapDelegate, type MapNode } from "./agent-map-nodes";
import { Button } from "@/components/ui";
import { useTranslations } from "next-intl";

interface MapDetailProps {
  title: string;
  icon: LucideIcon;
  /** Exactly one of these is set - whichever kind of node has focus. */
  node?: MapNode;
  delegate?: MapDelegate;
  onClose: () => void;
}

/**
 * What the focused node holds, spelled out beside the map rather than on it.
 *
 * The boxes are terse on purpose - a title and a count read across the whole
 * diagram at a glance. This is where the rest goes: the full list, the reason an
 * empty box is empty, and for a delegate the one thing the map is now for - the
 * link that walks to its own page, one hop of the delegation tree at a time.
 */
export function MapDetail({ title, icon: Icon, node, delegate, onClose }: MapDetailProps) {
  const t = useTranslations("agents");

  return (
    <div
      role="region"
      aria-label={t("mapDetailRegion", { name: title })}
      className="bg-card absolute bottom-2 left-2 z-10 w-64 rounded-lg border p-3 shadow-lg"
    >
      <div className="flex items-start gap-2">
        <Icon className="text-muted-foreground mt-0.5 h-4 w-4 shrink-0" />
        <p className="min-w-0 flex-1 truncate text-sm font-semibold">{title}</p>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="-mt-1.5 -mr-1.5 h-7 w-7"
          aria-label={t("mapCloseDetail")}
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      {node &&
        (node.items.length === 0 ? (
          <p className="text-muted-foreground mt-2 text-sm">{node.empty}</p>
        ) : (
          <ul className="mt-2 space-y-1">
            {node.items.map((item) => (
              <li key={item} className="text-sm break-words">
                {item}
              </li>
            ))}
          </ul>
        ))}

      {delegate && (
        <div className="mt-2 space-y-2 text-sm">
          <p className="text-muted-foreground text-xs tracking-wide uppercase">
            {t(KIND_LABEL[delegate.kind])}
          </p>
          {delegate.mode && (
            <p className="text-muted-foreground text-xs">
              {t("mapHandsBack", { mode: t(MODE_LABEL[delegate.mode]) })}
            </p>
          )}
          {delegate.href ? (
            <Button asChild variant="outline" size="sm" className="w-full">
              <Link href={delegate.href}>
                <ArrowUpRight className="h-3.5 w-3.5" />
                {t("openAgentPage", { name: delegate.name })}
              </Link>
            </Button>
          ) : delegate.kind === "specialist" ? (
            <p className="text-muted-foreground text-xs">{t("mapSpecialistDetail")}</p>
          ) : (
            <p className="text-muted-foreground text-xs">{t("delegateUnreachableDetail")}</p>
          )}
        </div>
      )}
    </div>
  );
}
