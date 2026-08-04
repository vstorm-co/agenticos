import { AlertCircle } from "lucide-react";

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
      className={cn(
        "border-destructive/30 bg-destructive/5 flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-14 text-center",
        className,
      )}
    >
      <div className="bg-destructive/10 text-destructive mb-4 flex h-11 w-11 items-center justify-center rounded-full">
        <AlertCircle className="h-5 w-5" />
      </div>
      <h3 className="text-foreground text-base font-semibold">
        {title ?? t("somethingWentWrong")}
      </h3>
      <p className="text-foreground/60 mt-1.5 max-w-sm text-sm">
        {description ?? t("checkConnection")}
      </p>
      {cta && (
        <button
          type="button"
          onClick={cta.onClick}
          className="border-foreground/20 hover:border-foreground/40 text-foreground mt-5 inline-flex items-center justify-center rounded-full border px-5 py-2 text-sm font-medium transition-colors"
        >
          {cta.label}
        </button>
      )}
    </div>
  );
}
