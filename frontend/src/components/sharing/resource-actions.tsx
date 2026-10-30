"use client";

import { MoreHorizontal, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui";

export function ResourceActions({
  name,
  onDelete,
  disabled,
}: {
  name: string;
  onDelete: () => void;
  disabled?: boolean;
}) {
  const t = useTranslations("common");
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="icon"
          aria-label={t("resourceActions", { name })}
          disabled={disabled}
        >
          <MoreHorizontal className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuItem onSelect={onDelete} className="text-destructive focus:text-destructive">
          <Trash2 className="size-4" />
          {t("deleteNamed", { name })}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
