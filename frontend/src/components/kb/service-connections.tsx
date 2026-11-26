"use client";

import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ServiceConnectionRecord } from "@/lib/service-connections-api";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
  Button,
} from "@/components/ui";

export function ServiceConnectionRemove({
  service,
  canRemove,
  onDelete,
}: {
  service: ServiceConnectionRecord;
  canRemove: boolean;
  onDelete: () => void;
}) {
  const t = useTranslations("kb");
  const tc = useTranslations("common");
  if (!canRemove) return null;
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="text-muted-foreground hover:text-destructive h-8 w-8 p-0"
          aria-label={tc("removeNamed", { name: service.name })}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("removeNamed", { name: service.name })}</AlertDialogTitle>
          <AlertDialogDescription>{t("collectionsPointingAtItStop")}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            onClick={onDelete}
          >
            {t("remove")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
