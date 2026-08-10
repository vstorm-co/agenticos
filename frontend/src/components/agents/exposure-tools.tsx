"use client";

import { Checkbox, Label } from "@/components/ui";
import type { ExposureTool } from "@/types/exposures";
import { useTranslations } from "next-intl";

/**
 * What the agent may look up on one bound bot.
 *
 * Here rather than in the Toolbox, and once per binding rather than once per
 * agent. An organization can bind one agent to two Mattermost servers and three
 * Slack workspaces, and "may it read what was said in this channel" has a
 * different answer on the internal one and the customer one - a switch on the
 * agent has one answer for all five.
 *
 * Only what the platform can answer is offered. Telegram gives a bot no channel
 * search and no way to read history, so those two boxes are simply absent
 * there: a control whose only effect is a tool that says "Telegram cannot do
 * that" is a worse answer than no control.
 *
 * Saved on the box rather than on a button, unlike the prompt beside it. This
 * is four switches, not prose - there is no half-typed state to protect, and a
 * Save nobody pressed is a grant nobody made.
 */
export function ExposureTools({
  exposureId,
  platform,
  available,
  granted,
  disabled,
  onChange,
}: {
  /** Scopes the checkbox ids, so two bindings on one page do not share labels. */
  exposureId: string;
  /** How the platform is written for a person - "Mattermost", not "mattermost". */
  platform: string;
  available: ExposureTool[];
  granted: string[];
  disabled: boolean;
  onChange: (tools: string[]) => void;
}) {
  const t = useTranslations("agents");
  if (available.length === 0) return null;

  return (
    <fieldset className="space-y-2">
      <legend className="text-xs font-medium">{t("channelLookupsOn", { platform })}</legend>
      <p className="text-muted-foreground text-xs">{t("channelLookupsHint")}</p>
      {available.map((tool) => (
        <div key={tool.id} className="flex items-start gap-2">
          <Checkbox
            id={`lookup-${exposureId}-${tool.id}`}
            className="mt-0.5"
            checked={granted.includes(tool.id)}
            disabled={disabled}
            // The whole list, not the box that moved: what a binding grants is
            // what it is, and a patch describing one checkbox could not say
            // "and nothing else".
            onCheckedChange={(checked) =>
              onChange(
                checked === true ? [...granted, tool.id] : granted.filter((id) => id !== tool.id),
              )
            }
          />
          <Label htmlFor={`lookup-${exposureId}-${tool.id}`} className="text-xs font-normal">
            {/* The registry's own sentence - the one the model reads before
                deciding to call the tool. A second paraphrase written here is
                the shape of #144. */}
            {tool.description}
          </Label>
        </div>
      ))}
    </fieldset>
  );
}
