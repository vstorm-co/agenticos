"use client";

import { Database, Globe } from "lucide-react";

import { BrandIcon, connectorBrand } from "@/components/icons/brand-icon";
import { CONNECTOR_LOGOS } from "@/lib/connector-logos.generated";
import { cn } from "@/lib/utils";

/** The spellings a stored source may carry for a connector the logos are keyed by. */
const ALIASES: Readonly<Record<string, string>> = {
  google_drive: "gdrive",
  drive: "gdrive",
  aws: "s3",
};

const SIZES = {
  sm: { tile: "size-8 rounded-lg", mark: "size-[18px]" },
  md: { tile: "size-9 rounded-xl", mark: "size-5" },
} as const;

/**
 * A connector's mark, as the MCP cards draw a server's: the brand's own logo in
 * its colours on a white tile, the same in both themes because the logos are
 * drawn for a light ground. A grey glyph in a grey circle read as one icon
 * repeated down the list. A connector with no baked logo takes its brand glyph,
 * the website connector a globe, anything else a database.
 */
export function ConnectorIcon({
  type,
  size = "md",
  className,
}: {
  type: string;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  const logo = CONNECTOR_LOGOS[ALIASES[type] ?? type];
  const brand = connectorBrand(type);
  const Glyph = type === "web" ? Globe : Database;
  return (
    <span
      aria-hidden
      className={cn(
        "border-foreground/10 grid shrink-0 place-items-center border bg-white text-neutral-800",
        SIZES[size].tile,
        className,
      )}
    >
      {logo ? (
        // A baked data URI: there is nothing for `next/image` to optimise or fetch.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={logo} alt="" className={cn(SIZES[size].mark, "object-contain")} />
      ) : brand ? (
        <BrandIcon name={brand} className="size-4" />
      ) : (
        <Glyph className="size-4" />
      )}
    </span>
  );
}
