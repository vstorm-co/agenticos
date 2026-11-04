import { Webhook } from "lucide-react";

import { BrandIcon, type BrandName } from "@/components/icons/brand-icon";
import type { EventSource } from "@/types/triggers";

/**
 * The one mark per event source, drawn wherever a source is shown - the "Fires
 * on" picker and every trigger row read this so a GitHub trigger never wears two
 * faces across the surfaces.
 *
 * GitHub, Gmail and Outlook get their brand marks (bundled Simple Icons, monochrome
 * `currentColor`, no external fetch); the API source stands for nobody's brand -
 * it is your own code posting signed JSON - and takes a plain lucide glyph. The mark is decorative - a label always sits
 * beside it - so it is `aria-hidden` and adds no second announcement.
 */
const BRAND_SOURCES: Partial<Record<EventSource, BrandName>> = {
  github: "github",
  gmail: "gmail",
  // The bundled sets carry no Outlook mark; Microsoft's is the one the portal
  // card draws too.
  outlook: "microsoft",
  hubspot: "hubspot",
  zendesk: "zendesk",
  google_drive: "gdrive",
  google_calendar: "googlecalendar",
  microsoft_files: "sharepoint",
  outlook_calendar: "microsoft",
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
  const Glyph = Webhook;
  return <Glyph aria-hidden className={className} />;
}
