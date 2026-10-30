"use client";
import { useEffect, useSyncExternalStore, useTransition } from "react";
import { ArrowRight, LoaderCircle } from "lucide-react";
import { BrandMark } from "@/components/branding/brand-mark";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useDesktopSetup } from "@/hooks/use-desktop-setup";
import { useDesktopPreferencesStore } from "@/stores/desktop-preferences-store";
import { finishOnboarding } from "@/lib/desktop/commands";
import { reportShellFailure } from "@/lib/desktop/shell";
import { useRouter } from "@/lib/locale-navigation";
import { useShell } from "@/hooks/use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";
import { ReadinessPanel } from "./readiness-panel";

const subscribeHydration = () => () => {};
const clientReady = () => true;
const serverReady = () => false;

/** The connection wizard's destination, also available later from the native menu. */
export function ReadinessScreen({
  repair,
  connection,
}: {
  repair: string | null;
  connection: boolean;
}) {
  const shell = useShell();
  const hydrated = useSyncExternalStore(subscribeHydration, clientReady, serverReady);
  if (!hydrated)
    return (
      <main className="desktop-setup-screen">
        <LoaderCircle
          aria-hidden
          className="my-auto size-6 animate-spin motion-reduce:animate-none"
        />
      </main>
    );
  return isDesktopShell(shell) ? (
    <NativeReadinessScreen repair={repair} connection={connection} />
  ) : (
    <ReadinessPanel repair={repair} />
  );
}
function NativeReadinessScreen({
  repair,
  connection,
}: {
  repair: string | null;
  connection: boolean;
}) {
  const t = useTranslations("desktop.readiness");
  const setup = useDesktopSetup();
  const mark = useDesktopPreferencesStore((s) => s.review);
  const router = useRouter();
  const [navigating, startNavigation] = useTransition();
  useEffect(() => {
    router.prefetch("/dashboard");
  }, [router]);
  const finish = useMutation({
    mutationFn: finishOnboarding,
    onSuccess: () => {
      if (setup.scope && setup.revision !== undefined) mark(setup.scope, setup.revision);
      startNavigation(() => router.replace("/dashboard"));
    },
    onError: (error) => reportShellFailure("finishing desktop connection", error),
  });
  const busy = finish.isPending || navigating;
  return (
    <main className="desktop-setup-screen" aria-busy={busy}>
      <div className="desktop-setup-card" data-busy={busy || undefined}>
        {connection && (
          <header className="mb-7 flex flex-col items-center text-center">
            <BrandMark size={56} className="mb-5 drop-shadow-md" />
            <h1 className="text-2xl font-semibold tracking-tight">{t("welcome")}</h1>
            <p className="text-muted-foreground mt-2 max-w-md text-sm leading-relaxed">
              {t("welcomeHint")}
            </p>
          </header>
        )}
        <ReadinessPanel repair={repair} />
        {finish.isError && (
          <p role="alert" className="text-destructive mt-4 text-sm">
            {t("finishFailed")}
          </p>
        )}
        <footer className="border-border mt-6 flex items-center justify-end gap-3 border-t pt-5">
          <Button className="min-w-36 rounded-full" disabled={busy} onClick={() => finish.mutate()}>
            {busy ? (
              <LoaderCircle
                aria-hidden
                className="size-4 animate-spin motion-reduce:animate-none"
              />
            ) : null}
            {busy ? t("opening") : t("done")}
            {!busy && <ArrowRight aria-hidden className="size-4" />}
          </Button>
        </footer>
      </div>
    </main>
  );
}
