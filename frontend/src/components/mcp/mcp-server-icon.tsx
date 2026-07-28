import { BrandIcon, isBrandName } from "@/components/icons/brand-icon";
import { Monogram } from "@/components/icons/monogram";
import { cn } from "@/lib/utils";

/**
 * The brand mark for a server, from the name the catalog gives it.
 *
 * **The catalog carries the icon; this component only draws it.** It used to
 * hold its own map from catalog key to brand, six entries long, which had to be
 * edited every time somebody added a server to the backend — and silently drew
 * a monogram when they did not. The entry now says what its mark is, so there
 * is one list and it lives beside the thing it describes.
 *
 * **Simple Icons, via the `BrandIcon` this app already uses** for connectors and
 * the sign-in buttons. Three properties matter here and only that source has all
 * of them: the glyphs are compiled in, so nothing is fetched while a page
 * renders and a self-hosted deployment stays air-gappable; they are monochrome
 * `currentColor`, so one mark is legible in both themes; and they come from a
 * maintained set rather than from hand-authored path data, so GitHub's logo is
 * GitHub's logo.
 *
 * An icon set is finite and this catalog is not, so a name it does not draw —
 * and a server nobody curated — falls through to a monogram. That is the
 * deliberate case, not the failure one: one generic plug repeated down a column
 * removes the only reason to have icons in a list.
 */
interface McpServerIconProps {
  /** The mark the catalog names, or null for a server nobody curated. */
  icon: string | null | undefined;
  /**
   * What the row is called. The monogram is taken from this rather than from the
   * icon name, because an uncurated row has none.
   */
  name: string;
  className?: string;
}

/** A catalog server's logo, or a monogram for one no icon set carries. */
export function McpServerIcon({ icon, name, className }: McpServerIconProps) {
  const size = cn("h-5 w-5 shrink-0", className);

  if (icon && isBrandName(icon)) {
    return <BrandIcon name={icon} aria-hidden className={size} />;
  }
  return <Monogram label={name} className={size} />;
}
