import { cn } from "@/lib/utils";

const SIZES = {
  xs: "size-[18px] rounded-[5px] text-[10px]",
  sm: "size-6 rounded-md text-[11px]",
  md: "size-8 rounded-lg text-sm",
  lg: "size-10 rounded-xl text-base",
};

/** The same project identity beside its name on every surface. */
export function ProjectAvatar({
  name,
  size = "xs",
  className,
}: {
  name: string;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  const initial = Array.from(name.trim())[0]?.toUpperCase() ?? "·";
  return (
    <span
      aria-hidden
      className={cn(
        "bg-foreground/[0.07] text-foreground inline-flex shrink-0 items-center justify-center leading-none font-semibold",
        SIZES[size],
        className,
      )}
    >
      {initial}
    </span>
  );
}
