"use client";

import { useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useStart } from "@/hooks/use-start";
import { useRouter } from "@/lib/locale-navigation";

/** Completing the walkthrough never requires optional fields or an AI run. */
export function StartFinish() {
  const t = useTranslations("start");
  const state = useStart();
  const router = useRouter();
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  return (
    <div className="flex flex-wrap items-center gap-3 border-t pt-5">
      <Button
        variant="outline"
        disabled={state.save.isPending}
        onClick={() =>
          state.save.mutate(
            { completed: true },
            {
              onSuccess: () => {
                if (active.current) router.push("/chat");
              },
            },
          )
        }
      >
        {t("administration.finishSetup")}
      </Button>
      {state.save.error && <p role="alert">{t("loadFailed")}</p>}
    </div>
  );
}
