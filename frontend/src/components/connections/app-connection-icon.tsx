import { Plug } from "lucide-react";
import { BrandIcon, isBrandName } from "@/components/icons/brand-icon";

const BRANDS: Record<string, string> = {
  googledrive: "gdrive",
  googlecalendar: "googlecalendar",
  gmail: "gmail",
  outlook: "outlook",
  slack: "slack",
  notion: "notion",
  github: "github",
};

export function AppConnectionIcon({ toolkit }: { toolkit: string }) {
  const brand = BRANDS[toolkit] ?? toolkit;
  return brand && isBrandName(brand) ? (
    <BrandIcon name={brand} className="size-6 shrink-0" />
  ) : (
    <Plug className="text-muted-foreground size-6 shrink-0" aria-hidden />
  );
}
