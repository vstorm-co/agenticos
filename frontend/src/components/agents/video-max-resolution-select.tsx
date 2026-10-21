"use client";

import { useTranslations } from "next-intl";

import {
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { resolutionsAbove } from "@/lib/video-resolutions";

/** The select's value for "no other resolution", which is stored as no value. */
const ONLY_USUAL = "only-usual";

interface VideoMaxResolutionSelectProps {
  /** The chosen model's resolutions, in the catalog's order. */
  resolutions: string[];
  /** The resolution every clip is made at unless the agent asks for another. */
  usual: string;
  /** The stored ceiling, if any. */
  value: unknown;
  disabled?: boolean;
  /** The new ceiling, or `null` for none. */
  onChange: (ceiling: string | null) => void;
}

/**
 * The highest resolution the agent may ask for per clip.
 *
 * Only resolutions above the usual one are offered, as the server requires: a
 * ceiling at the usual one would allow every lower resolution while saying
 * nothing here. With nothing above the usual one there is nothing to choose,
 * and the control is not drawn.
 */
export function VideoMaxResolutionSelect({
  resolutions,
  usual,
  value,
  disabled,
  onChange,
}: VideoMaxResolutionSelectProps) {
  const t = useTranslations("agents");
  const ceilings = resolutionsAbove(resolutions, usual);
  if (ceilings.length === 0) return null;
  const shown = typeof value === "string" && ceilings.includes(value) ? value : ONLY_USUAL;

  return (
    <div className="space-y-1.5">
      <Label htmlFor="video-max-resolution">{t("videoMaxResolution")}</Label>
      <Select
        value={shown}
        disabled={disabled}
        onValueChange={(next) => onChange(next === ONLY_USUAL ? null : next)}
      >
        <SelectTrigger id="video-max-resolution">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ONLY_USUAL}>{t("videoMaxResolutionNone")}</SelectItem>
          {ceilings.map((entry) => (
            <SelectItem key={entry} value={entry}>
              {entry}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p className="text-muted-foreground text-xs">{t("videoMaxResolutionDetail")}</p>
    </div>
  );
}
