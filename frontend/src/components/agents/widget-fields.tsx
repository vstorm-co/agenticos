"use client";

import { useTranslations } from "next-intl";

import {
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import type { WidgetConfig } from "@/types/embeds";

const MAX_TITLE = 80;
const MAX_SUBTITLE = 120;
const MAX_GREETING = 400;
const MAX_PLACEHOLDER = 80;
const MAX_LAUNCHER = 24;

/**
 * What the bubble in the corner of somebody else's page says.
 *
 * All seven fields, which is the whole point of the component existing: the
 * config has had them since the widget did - they are stored, validated and
 * published to `widget.js` - and the Builder edited exactly one of them, the
 * accent. So the title said *Ask us anything* on every site this platform is
 * pasted into, the launcher said *Chat*, and the only way to change either was
 * an API call.
 *
 * A fixed set rather than a stylesheet, for the reason `WidgetConfig` gives: this
 * markup runs on a third party's page, and free-form CSS in a JSONB column is a
 * stylesheet nobody reviews shipped to somebody else's browser.
 *
 * The counterpart to `PageFields`, and deliberately not shared with it: a
 * launcher label and a corner to sit in mean nothing on a full page, and a page
 * needs a browser-tab title a bubble has no use for.
 */
export function WidgetFields({
  config,
  disabled,
  onChange,
}: {
  config: WidgetConfig;
  disabled: boolean;
  onChange: (config: WidgetConfig) => void;
}) {
  const t = useTranslations("agents");

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="widget-title">{t("widgetTitle")}</Label>
          <Input
            id="widget-title"
            value={config.title}
            maxLength={MAX_TITLE}
            disabled={disabled}
            onChange={(event) => onChange({ ...config, title: event.target.value })}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="widget-subtitle">{t("widgetSubtitle")}</Label>
          <Input
            id="widget-subtitle"
            value={config.subtitle}
            maxLength={MAX_SUBTITLE}
            disabled={disabled}
            onChange={(event) => onChange({ ...config, subtitle: event.target.value })}
          />
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="widget-greeting">{t("widgetGreeting")}</Label>
        <Textarea
          id="widget-greeting"
          value={config.greeting}
          rows={2}
          maxLength={MAX_GREETING}
          disabled={disabled}
          onChange={(event) => onChange({ ...config, greeting: event.target.value })}
        />
        <p className="text-muted-foreground text-xs">{t("widgetGreetingHint")}</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="widget-placeholder">{t("widgetPlaceholder")}</Label>
          <Input
            id="widget-placeholder"
            value={config.placeholder}
            maxLength={MAX_PLACEHOLDER}
            disabled={disabled}
            onChange={(event) => onChange({ ...config, placeholder: event.target.value })}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="widget-launcher">{t("widgetLauncherLabel")}</Label>
          <Input
            id="widget-launcher"
            value={config.launcher_label}
            maxLength={MAX_LAUNCHER}
            disabled={disabled}
            onChange={(event) => onChange({ ...config, launcher_label: event.target.value })}
          />
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="widget-accent">{t("accentColour")}</Label>
          <div className="flex items-center gap-2">
            <input
              id="widget-accent"
              type="color"
              value={config.accent}
              disabled={disabled}
              onChange={(event) => onChange({ ...config, accent: event.target.value })}
              className="border-input h-9 w-12 cursor-pointer rounded-md border bg-transparent"
            />
            <Input
              value={config.accent}
              disabled={disabled}
              onChange={(event) => onChange({ ...config, accent: event.target.value })}
              className="font-mono"
              aria-label={t("accentColour")}
            />
          </div>
        </div>
        <div className="space-y-2">
          <Label htmlFor="widget-position">{t("widgetPosition")}</Label>
          <Select
            value={config.position}
            onValueChange={(value) =>
              onChange({ ...config, position: value as WidgetConfig["position"] })
            }
          >
            <SelectTrigger id="widget-position">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="right">{t("widgetPositionRight")}</SelectItem>
              <SelectItem value="left">{t("widgetPositionLeft")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
    </div>
  );
}
