import {
  Building2,
  Code2,
  Factory,
  HeartPulse,
  Landmark,
  Library,
  Scale,
  ShoppingBag,
} from "lucide-react";
import type { LucideIcon, LucideProps } from "lucide-react";

/**
 * Icon per skill gallery industry, keyed on the directory the backend ships.
 *
 * A table rather than a field on the response: the backend has no business
 * naming a component from an icon package, and an id it does not recognise
 * falls back rather than rendering nothing.
 */
const INDUSTRY_ICONS: Record<string, LucideIcon> = {
  healthcare: HeartPulse,
  finance: Landmark,
  ecommerce: ShoppingBag,
  software: Code2,
  "public-sector": Building2,
  legal: Scale,
  manufacturing: Factory,
};

export function industryIcon(id: string): LucideIcon {
  return INDUSTRY_ICONS[id] ?? Library;
}

/** One industry's icon, drawn. */
export function IndustryIcon({ id, ...props }: { id: string } & LucideProps) {
  const Icon = INDUSTRY_ICONS[id] ?? Library;
  return <Icon {...props} />;
}
