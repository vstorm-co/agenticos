"use client";

import { BrandIcon, isBrandName } from "@/components/icons/brand-icon";
import { CustomMark, useCustomIcons } from "@/components/icons/custom-icons";
import { Monogram } from "@/components/icons/monogram";
import { bakedLogo } from "@/lib/mcp-catalog";
import { cn } from "@/lib/utils";
import { MCP_SERVICE_GLYPHS, mcpServiceKind } from "./mcp-service-glyph";

/** Brand marks are supplied by the catalog. Registry listings without one use
 * a service pictogram; arbitrary private names retain their monogram. All marks
 * are local so browsing the catalog makes no third-party favicon requests. */
interface McpServerIconProps {
  /** The mark the catalog names, or null for a server nobody curated. */
  icon: string | null | undefined;
  /**
   * What the row is called. The monogram is taken from this rather than from the
   * icon name, because an uncurated row has none.
   */
  name: string;
  /**
   * The server's address. A server the catalog bakes a logo for is drawn in its
   * own colours from it - a column of grey glyphs reads as one icon repeated.
   */
  url?: string | null;
  category?: string;
  className?: string;
}

/** A catalog server's logo: compiled-in, deployment-supplied, or a monogram. */
export function McpServerIcon({ icon, name, url, category, className }: McpServerIconProps) {
  const custom = useCustomIcons();
  const size = cn("h-5 w-5 shrink-0", className);
  const logo = bakedLogo(url);

  if (logo !== null) {
    // A baked data URI: there is nothing for `next/image` to optimise or fetch.
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img src={logo} alt="" aria-hidden className={cn(size, "rounded-[22%] object-contain")} />
    );
  }
  if (icon && isBrandName(icon)) {
    return <BrandIcon name={icon} aria-hidden className={size} />;
  }
  if (icon && custom.has(icon)) {
    return <CustomMark name={icon} className={size} />;
  }
  const service = mcpServiceKind(name, category);
  const ServiceGlyph = service ? MCP_SERVICE_GLYPHS[service] : null;
  if (ServiceGlyph) return <ServiceGlyph aria-hidden className={size} strokeWidth={1.7} />;
  return <Monogram label={name} className={size} />;
}
