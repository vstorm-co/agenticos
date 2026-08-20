import { Mail, Webhook } from "lucide-react";

import { BrandIcon, type BrandName } from "@/components/icons/brand-icon";
import type { EventSource } from "@/types/triggers";

/**
 * The one mark per event source, drawn wherever a source is shown - the "Fires
 * on" picker and every trigger row read this so a GitHub trigger never wears two
 * faces across the surfaces.
 *
 * GitHub gets its brand mark (bundled Simple Icons, monochrome `currentColor`,
 * no external fetch); an inbound email and the API source have no brand and
 * take a plain lucide glyph. The mark is decorative - a label always sits
 * beside it - so it is `aria-hidden` and adds no second announcement.
 */
const BRAND_SOURCES: Partial<Record<EventSource, BrandName>> = {
  github: "github",
};

export function EventSourceMark({
  source,
  className,
}: {
  source: EventSource;
  className?: string;
}) {
  const brand = BRAND_SOURCES[source];
  if (brand) {
    return <BrandIcon name={brand} aria-hidden className={className} />;
  }
  const Glyph = source === "email" ? Mail : Webhook;
  return <Glyph aria-hidden className={className} />;
}
