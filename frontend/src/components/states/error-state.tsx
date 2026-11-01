import { AlertCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { useTranslations } from "next-intl";
interface ErrorStateProps {
  title?: string;
  description?: string;
  cta?: { label: string; onClick: () => void };
  className?: string;
}

export function ErrorState({ title, description, cta, className }: ErrorStateProps) {
  const t = useTranslations("ui");
  return (
    <div
      role="alert"
      className={cn(
        "border-border bg-card flex flex-col items-center justify-center rounded-xl border px-5 py-10 text-center sm:px-6 sm:py-14",
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
      {cta && (
        <Button variant="outline" type="button" onClick={cta.onClick} className="mt-5">
          {cta.label}
        </Button>
      )}
    </div>
  );
}
