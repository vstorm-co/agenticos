"use client";

import { AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Alert,
  AlertDescription,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { resolutionsFrom } from "@/lib/video-resolutions";

/** The select's value for "any resolution", which is stored as no value. */
const ANY = "any";

interface VideoMaxResolutionSelectProps {
  /** The chosen model's resolutions, in the catalog's order. */
  resolutions: string[];
  /** The resolution a clip is made at unless the agent asks for another. */
  usual: string;
  /** The stored ceiling, if any. */
  value: unknown;
  disabled?: boolean;
  /** The new ceiling, or `null` for none. */
  onChange: (ceiling: string | null) => void;
}

/**
 * The highest resolution the agent may ask for per clip - the one limit on it.
 *
 * The usual resolution is only a default: with no ceiling the agent may ask for
 * any resolution the model renders, and since a second costs more the higher it
 * goes, that is said as a warning rather than left to the field's description.
 * A ceiling is the usual resolution or anything above it, as the server requires.
 */
export function VideoMaxResolutionSelect({
  resolutions,
  usual,
  value,
  disabled,
  onChange,
}: VideoMaxResolutionSelectProps) {
  const t = useTranslations("agents");
  const ceilings = resolutionsFrom(resolutions, usual);
  const shown = typeof value === "string" && ceilings.includes(value) ? value : ANY;

  return (
    <div className="space-y-1.5">
      <Label htmlFor="video-max-resolution">{t("videoMaxResolution")}</Label>
      <Select
        value={shown}
        disabled={disabled}
        onValueChange={(next) => onChange(next === ANY ? null : next)}
      >
        <SelectTrigger id="video-max-resolution">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ANY}>{t("videoMaxResolutionAny")}</SelectItem>
          {ceilings.map((entry) => (
            <SelectItem key={entry} value={entry}>
              {entry}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p className="text-muted-foreground text-xs">{t("videoMaxResolutionDetail")}</p>
      {shown === ANY && resolutions.length > 1 && (
        <Alert variant="warning">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>
            {t("videoMaxResolutionAnyWarning", { highest: String(ceilings.at(-1)) })}
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}
