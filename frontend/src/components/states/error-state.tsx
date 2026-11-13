import { AlertCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { useTranslations } from "next-intl";
interface ErrorStateProps {
  title?: string;
  description?: string;
  cta?: { label: string; onClick: () => void };
  secondaryCta?: { label: string; onClick: () => void };
  className?: string;
}

export function ErrorState({ title, description, cta, secondaryCta, className }: ErrorStateProps) {
  const t = useTranslations("ui");
  return (
    <div
      role="alert"
      className={cn(
        "border-border bg-card flex flex-col items-center justify-center rounded-xl border px-5 py-6 text-center sm:px-6 sm:py-8",
        className,
      )}
    >
      <div className="bg-destructive/10 text-destructive mb-4 flex h-11 w-11 items-center justify-center rounded-full">
        <AlertCircle className="h-5 w-5" aria-hidden />
      </div>
      <h3 className="text-foreground text-base font-semibold">
        {title ?? t("somethingWentWrong")}
      </h3>
      <p className="text-muted-foreground mt-1.5 max-w-sm text-sm">
        {description ?? t("checkConnection")}
      </p>
      {(cta || secondaryCta) && (
        <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
          {cta && (
            <Button variant="outline" type="button" onClick={cta.onClick}>
              {cta.label}
            </Button>
          )}
          {secondaryCta && (
            <Button variant="default" type="button" onClick={secondaryCta.onClick}>
              {secondaryCta.label}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
