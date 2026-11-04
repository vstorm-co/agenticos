"use client";

import { useTranslations } from "next-intl";

import { ChannelPlatformIcon } from "@/components/channels/channel-platform-icon";
import {
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useTeamsConversations } from "@/hooks/use-channel-bots";

/** Sentinel for "post nowhere" - a Select item may not be empty. */
export const NO_TEAMS_POST = "__none__";

/**
 * Where a fire's answer is also posted: a Teams channel or group chat the
 * organization's bot is in (#1985).
 *
 * Drawn only where there is somewhere to post - an organization with no Teams
 * bot, or a bot nobody has talked to yet, has nothing to offer, and an empty
 * picker is a question nobody can answer. A personal chat is never offered: it
 * is somebody's own.
 */
export function TeamsPostField({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const t = useTranslations("triggers");
  const { data: conversations = [] } = useTeamsConversations();
  if (conversations.length === 0) return null;
  return (
    <FormField label={t("teamsPost")} htmlFor="trigger-teams-post" description={t("teamsPostHint")}>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id="trigger-teams-post">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NO_TEAMS_POST}>{t("teamsPostNowhere")}</SelectItem>
          {conversations.map((conversation) => (
            <SelectItem key={conversation.id} value={conversation.id}>
              <span className="flex items-center gap-2">
                <ChannelPlatformIcon platform="teams" className="h-5 w-5 rounded-md" />
                <span>
                  {conversation.name ??
                    t(
                      conversation.conversation_type === "channel"
                        ? "teamsPostUnnamedChannel"
                        : "teamsPostUnnamedGroup",
                    )}
                </span>
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FormField>
  );
}
