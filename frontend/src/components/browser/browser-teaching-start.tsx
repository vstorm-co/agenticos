"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  Button,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import { usePermissions } from "@/hooks/use-permissions";
import { useHydrated } from "@/hooks/use-hydrated";
import { useTeachingStart } from "@/hooks/use-browser-teaching";
import { useTeachingAudience, useTeachingSkills } from "@/hooks/use-browser-teaching-settings";
import { readBrowserTeaching, isTeachingAudienceCurrent } from "@/lib/browser-teaching-api";
import {
  clearTeachingAttempt,
  readTeachingAttempt,
  retainTeachingAttempt,
  teachingAttemptKey,
  type TeachingStartAttempt,
} from "@/lib/browser-teaching-attempts";
import { isTeachingId, teachingOrigin, teachingOrigins } from "@/lib/browser-teaching-review";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";
import { ApiError } from "@/lib/api-error";
import type { Browse } from "@/lib/browse";
import type { BrowserTeaching } from "@/types/browser-teaching";
import { TeachingError } from "./browser-teaching-status";

type StartProps = {
  browse: Browse;
  canStart: boolean;
  onStarted: (session: BrowserTeaching) => void;
};
export function BrowserTeachingStart(props: StartProps) {
  const audience = useTeachingAudience();
  const hydrated = useHydrated();
  return hydrated ? (
    <TeachingStartForm
      key={JSON.stringify([
        audience.actor,
        audience.organization,
        props.browse.runId,
        props.browse.callId,
        props.browse.tabId,
      ])}
      {...props}
    />
  ) : null;
}
function TeachingStartForm({ browse, canStart, onStarted }: StartProps) {
  const t = useTranslations("browserTeaching");
  const locale = useLocale();
  const audience = useTeachingAudience();
  const key = teachingAttemptKey(audience, "start", [browse.runId!, browse.callId, browse.tabId!]);
  const [initial] = useState(() => readTeachingAttempt<TeachingStartAttempt>(key, "start"));
  const { can } = usePermissions();
  const canCreate = can(Perm.skillsEdit);
  const choices = useTeachingSkills(true);
  const skills =
    choices.data?.pages.flatMap((page) => page.items).filter((skill) => skill.can_edit === true) ??
    [];
  const [title, setTitle] = useState("");
  const [origins, setOrigins] = useState(() => teachingOrigin(browse.url ?? "") ?? "");
  const [target, setTarget] = useState(canCreate ? "new" : "");
  const [saved, setSaved] = useState(initial.attempt);
  const [blocked, setBlocked] = useState(initial.blocked);
  const [error, setError] = useState<unknown>(null);
  const [reading, setReading] = useState(false);
  const busy = useRef(false);
  const start = useTeachingStart();
  const validOrigins = teachingOrigins(origins);
  const targetAllowed = target === "new" ? canCreate : skills.some((skill) => skill.id === target);
  const leaseLive = canStart && !!browse.takeoverId && isTeachingId(browse.takeoverId);
  const valid =
    !blocked &&
    leaseLive &&
    !!validOrigins &&
    !!title.trim() &&
    title.length <= 160 &&
    targetAllowed;
  async function settle(session: BrowserTeaching, attempt: TeachingStartAttempt) {
    if (!isTeachingAudienceCurrent(audience)) return;
    if (
      session.id !== attempt.body.request_id ||
      session.run_id !== attempt.body.run_id ||
      session.call_id !== attempt.body.call_id ||
      session.tab_id !== attempt.body.tab_id ||
      session.target_skill_id !== attempt.targetSkillId
    ) {
      // i18n-exempt: fixed internal identity refusal, not transport or page copy.
      throw new Error("Teaching recovery identity mismatch");
    }
    clearTeachingAttempt(key);
    setSaved(null);
    onStarted(session);
  }
  async function check() {
    if (!saved || busy.current) return;
    busy.current = true;
    setReading(true);
    setError(null);
    try {
      await settle(await readBrowserTeaching(audience, saved.body.request_id), saved);
    } catch (failure) {
      if (isTeachingAudienceCurrent(audience)) setError(failure);
    } finally {
      busy.current = false;
      setReading(false);
    }
  }
  async function submit() {
    if (busy.current || blocked || (!saved && !valid)) return;
    busy.current = true;
    setError(null);
    const attempt: TeachingStartAttempt = saved ?? {
      kind: "start",
      targetSkillId: target === "new" ? null : target,
      body: {
        request_id: crypto.randomUUID(),
        run_id: browse.runId!,
        call_id: browse.callId,
        tab_id: browse.tabId!,
        takeover_id: browse.takeoverId!,
        title: title.trim(),
        allowed_origins: validOrigins!,
      },
    };
    if (!saved && !retainTeachingAttempt(key, attempt)) {
      setBlocked(true);
      busy.current = false;
      return;
    }
    setSaved(attempt);
    try {
      await settle(await start.mutateAsync(attempt), attempt);
    } catch (failure) {
      if (isTeachingAudienceCurrent(audience)) {
        setError(failure);
        if (
          !saved &&
          failure instanceof ApiError &&
          [400, 401, 403, 404, 409, 422].includes(failure.status)
        ) {
          if (clearTeachingAttempt(key)) setSaved(null);
          else setBlocked(true);
        }
      }
    } finally {
      busy.current = false;
    }
  }
  return (
    <section data-tour="teaching-start" className="space-y-4" aria-label={t("startTitle")}>
      <p className="text-muted-foreground text-sm">{t("liveActionsWarning")}</p>
      {blocked ? (
        <p role="alert" className="text-sm">
          {t("storageUnavailable")}
        </p>
      ) : saved ? (
        <div className="space-y-3 rounded-lg border p-3">
          <p className="text-sm">{t("startUncertain")}</p>
          <p className="text-sm font-medium break-words">{saved.body.title}</p>
          <p className="text-muted-foreground text-xs break-words">
            {saved.body.allowed_origins.join(", ")}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={() => void check()}
              disabled={reading || start.isPending}
            >
              {t("checkAgain")}
            </Button>
            <Button
              variant="outline"
              onClick={() => void submit()}
              disabled={reading || start.isPending}
            >
              {t("retrySameStart")}
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="teaching-title">{t("captureTitle")}</Label>
            <Input
              id="teaching-title"
              value={title}
              maxLength={160}
              onChange={(event) => setTitle(event.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="teaching-origins">{t("allowedOrigins")}</Label>
            <Textarea
              id="teaching-origins"
              value={origins}
              onChange={(event) => setOrigins(event.target.value)}
              rows={3}
            />
            <p className="text-muted-foreground text-xs">{t("originsHelp")}</p>
            {origins && !validOrigins && (
              <p role="alert" className="text-destructive text-xs">
                {t("invalidOrigins")}
              </p>
            )}
          </div>
          <div className="space-y-1">
            <Label htmlFor="teaching-target">{t("targetSkill")}</Label>
            <Select value={target} onValueChange={setTarget}>
              <SelectTrigger id="teaching-target">
                <SelectValue placeholder={t("chooseSkill")} />
              </SelectTrigger>
              <SelectContent>
                {canCreate && <SelectItem value="new">{t("newSkill")}</SelectItem>}
                {skills.map((skill) => (
                  <SelectItem key={skill.id} value={skill.id}>
                    {skill.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {choices.hasNextPage && (
              <Button
                size="sm"
                variant="ghost"
                disabled={choices.isFetching}
                onClick={() => void choices.fetchNextPage()}
              >
                {t("loadMoreSkills")}
              </Button>
            )}
            {choices.error && <TeachingError error={choices.error} />}
          </div>
          {!leaseLive && <p className="text-muted-foreground text-sm">{t("takeOverRequired")}</p>}
          <Button disabled={!valid || start.isPending} onClick={() => void submit()}>
            {t("startRecording")}
          </Button>
        </div>
      )}
      {error != null && <TeachingError error={error} />}
      <Link
        className="text-muted-foreground text-sm underline"
        href={`/${locale}${ROUTES.SKILLS_TEACHING}`}
      >
        {t("allCaptures")}
      </Link>
    </section>
  );
}
