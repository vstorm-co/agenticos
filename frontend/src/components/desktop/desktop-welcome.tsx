"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Bell, Keyboard, Sparkles } from "lucide-react";

import { CastPicker, Face } from "@/components/desktop/blobby-pickers";
import { DesktopSetting } from "@/components/desktop/desktop-only";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/hooks/use-auth";
import { useDesktopState, useSetBlobby, useSetWindowPreferences } from "@/hooks/use-desktop";
import { useShell } from "@/hooks/use-shell";
import { describeAccelerator } from "@/lib/desktop/accelerator";
import { faceOf } from "@/lib/desktop/blobby-cast";
import { finishOnboarding, notify, type DesktopState } from "@/lib/desktop/commands";
import { reportShellFailure } from "@/lib/desktop/shell";
import { useRouter } from "@/lib/locale-navigation";
import { cn } from "@/lib/utils";

const STEPS = ["blobby", "shortcuts", "loop", "done"] as const;
type Step = (typeof STEPS)[number];
const NEXT: Record<Step, Step> = {
  blobby: "shortcuts",
  shortcuts: "loop",
  loop: "done",
  done: "done",
};
const WELCOME = "/desktop/welcome";

/** One step of the welcome: an icon, a heading, what it is for, and its controls. */
function StepFrame({
  icon,
  title,
  body,
  children,
}: {
  icon: ReactNode;
  title: string;
  body: string;
  children?: ReactNode;
}) {
  return (
    <div className="animate-in fade-in slide-in-from-bottom-2 flex flex-col items-center gap-2 text-center duration-300">
      <div className="bg-accent text-foreground mb-2 flex size-11 items-center justify-center rounded-full">
        {icon}
      </div>
      <h1 className="font-display text-2xl font-bold">{title}</h1>
      <p className="text-muted-foreground max-w-md text-sm">{body}</p>
      {children ? <div className="mt-5 w-full">{children}</div> : null}
    </div>
  );
}

function Keycap({ children }: { children: string }) {
  return (
    <kbd className="border-border bg-card text-foreground rounded-lg border px-3 py-1.5 font-mono text-lg shadow-sm">
      {children}
    </kbd>
  );
}

function Steps({ state, step }: { state: DesktopState; step: Step }) {
  const t = useTranslations("desktop.welcome");
  const mac = useShell()?.platform === "macos";
  const setBlobby = useSetBlobby();
  const setWindow = useSetWindowPreferences();
  const [tested, setTested] = useState(false);
  const { blobby, window } = state;

  switch (step) {
    case "blobby":
      return (
        <StepFrame
          icon={<Sparkles className="size-5" aria-hidden />}
          title={t("blobby.title")}
          body={t("blobby.body")}
        >
          <CastPicker
            value={blobby.character}
            onChange={(character) => setBlobby.mutate({ ...blobby, character, enabled: true })}
          />
        </StepFrame>
      );
    case "shortcuts":
      return (
        <StepFrame
          icon={<Keyboard className="size-5" aria-hidden />}
          title={t("shortcuts.title")}
          body={t("shortcuts.body")}
        >
          <div className="flex flex-col items-center gap-4">
            {state.shortcuts.map((binding) => (
              <div
                key={binding.action}
                className="flex w-full max-w-sm items-center justify-between gap-4"
              >
                <span className="text-sm font-medium">{t(`shortcuts.${binding.action}`)}</span>
                {binding.accelerator ? (
                  <Keycap>{describeAccelerator(binding.accelerator, mac)}</Keycap>
                ) : (
                  <span className="text-muted-foreground text-sm">{t("shortcuts.off")}</span>
                )}
              </div>
            ))}
            <p className="text-muted-foreground text-xs">{t("shortcuts.change")}</p>
          </div>
        </StepFrame>
      );
    case "loop":
      return (
        <StepFrame
          icon={<Bell className="size-5" aria-hidden />}
          title={t("loop.title")}
          body={t("loop.body")}
        >
          <div className="border-border bg-card mx-auto max-w-md space-y-4 rounded-xl border p-4 text-left">
            <DesktopSetting id="welcome-login" label={t("loop.login")}>
              <Switch
                aria-labelledby="welcome-login"
                checked={window.launch_at_login}
                onCheckedChange={(checked) =>
                  setWindow.mutate({ ...window, launch_at_login: checked })
                }
              />
            </DesktopSetting>
            <DesktopSetting id="welcome-running" label={t("loop.keepRunning")}>
              <Switch
                aria-labelledby="welcome-running"
                checked={window.keep_running}
                onCheckedChange={(checked) =>
                  setWindow.mutate({ ...window, keep_running: checked })
                }
              />
            </DesktopSetting>
            <DesktopSetting id="welcome-test" label={t("loop.test")} hint={t("loop.testHint")}>
              <Button
                size="sm"
                variant="outline"
                disabled={tested}
                onClick={() => {
                  setTested(true);
                  notify({
                    kind: "inbox",
                    title: t("loop.testTitle"),
                    body: t("loop.testBody"),
                    path: "/dashboard",
                  }).catch((error: unknown) =>
                    reportShellFailure("could not send a test notification", error),
                  );
                }}
              >
                {tested ? t("loop.sent") : t("loop.send")}
              </Button>
            </DesktopSetting>
          </div>
        </StepFrame>
      );
    case "done":
      return (
        <StepFrame
          icon={<Face face={faceOf(blobby.character)} size={44} />}
          title={t("done.title")}
          body={t("done.body")}
        />
      );
  }
}

/**
 * The desktop app's welcome, once, after it first reaches a console: pick
 * blobby, learn the two shortcuts, and decide how the app keeps you in the loop.
 * Each step can be skipped; all of it is in Settings afterwards.
 *
 * Signed out, it goes through sign-in and comes back here.
 */
export function DesktopWelcome() {
  const t = useTranslations("desktop.welcome");
  const router = useRouter();
  const shell = useShell();
  const { isAuthenticated, isLoading } = useAuth();
  const { data } = useDesktopState();
  const [step, setStep] = useState<Step>("blobby");
  const last = step === "done";

  useEffect(() => {
    if (!isLoading && !isAuthenticated)
      router.replace(`/login?returnTo=${encodeURIComponent(WELCOME)}`);
  }, [isAuthenticated, isLoading, router]);

  const finish = () => {
    finishOnboarding()
      .catch((error: unknown) => reportShellFailure("could not finish onboarding", error))
      .finally(() => router.replace("/dashboard"));
  };

  if (!shell) {
    return (
      <main className="flex min-h-dvh items-center justify-center p-6">
        <p className="text-muted-foreground text-sm">{t("onlyInApp")}</p>
      </main>
    );
  }
  if (!data || !isAuthenticated) return null;

  return (
    <main className="relative flex min-h-dvh flex-col items-center justify-center px-6 py-12">
      <div aria-hidden className="absolute inset-x-0 top-0 h-10" data-tauri-drag-region />
      <div className="w-full max-w-xl">
        <Steps key={step} state={data} step={step} />
        <div className="mt-10 flex items-center justify-between">
          <div className="flex gap-1.5" aria-hidden>
            {STEPS.map((name) => (
              <span
                key={name}
                className={cn(
                  "h-1.5 rounded-full transition-all",
                  name === step ? "bg-foreground w-5" : "bg-border w-1.5",
                )}
              />
            ))}
          </div>
          <div className="flex items-center gap-2">
            {last ? null : (
              <Button variant="ghost" size="sm" onClick={finish}>
                {t("skip")}
              </Button>
            )}
            <Button onClick={last ? finish : () => setStep(NEXT[step])}>
              {last ? t("open") : t("next")}
            </Button>
          </div>
        </div>
      </div>
    </main>
  );
}
