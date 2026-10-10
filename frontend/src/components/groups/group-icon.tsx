import {
  Banknote,
  Briefcase,
  Building,
  Code,
  FlaskConical,
  GraduationCap,
  Headphones,
  HeartHandshake,
  Megaphone,
  Scale,
  Truck,
  Users,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { GroupIcon as GroupIconName } from "@/types/groups";

/** Each mark a group may carry, by the name the API stores (#2072). */
export const GROUP_ICON_COMPONENTS: Record<GroupIconName, LucideIcon> = {
  users: Users,
  briefcase: Briefcase,
  banknote: Banknote,
  megaphone: Megaphone,
  headphones: Headphones,
  code: Code,
  scale: Scale,
  "heart-handshake": HeartHandshake,
  truck: Truck,
  "flask-conical": FlaskConical,
  "graduation-cap": GraduationCap,
  building: Building,
};

/** A group's mark in a soft tile; the generic group mark when it has none. */
export function GroupIcon({ icon, className }: { icon: GroupIconName | null; className?: string }) {
  const Mark = GROUP_ICON_COMPONENTS[icon ?? "users"];
  return (
    <span
      className={cn(
        "bg-muted text-foreground inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
        className,
      )}
    >
      <Mark className="h-4 w-4" aria-hidden />
    </span>
  );
}
