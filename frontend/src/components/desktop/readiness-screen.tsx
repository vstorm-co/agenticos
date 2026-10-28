"use client";
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

/** The connection wizard's destination, also available later from the native menu. */
export function ReadinessScreen({
  repair,
  connection,
}: {
  repair: string | null;
  connection: boolean;
}) {
  const shell = useShell();
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
  const finish = useMutation({
    mutationFn: finishOnboarding,
    onSuccess: () => {
      if (setup.scope && setup.revision !== undefined) mark(setup.scope, setup.revision);
      router.replace("/dashboard");
    },
    onError: (error) => reportShellFailure("finishing desktop connection", error),
  });
  return (
    <main className="mx-auto max-w-2xl space-y-6 p-6">
      {connection && (
        <div>
          <h1 className="text-xl font-semibold">{t("welcome")}</h1>
          <p className="text-muted-foreground mt-1 text-sm">{t("welcomeHint")}</p>
        </div>
      )}
      <ReadinessPanel repair={repair} />
      {finish.isError && (
        <p role="alert" className="text-destructive text-sm">
          {t("finishFailed")}
        </p>
      )}
      <div className="flex justify-end">
        <Button disabled={finish.isPending} onClick={() => finish.mutate()}>
          {t("done")}
        </Button>
      </div>
    </main>
  );
}
