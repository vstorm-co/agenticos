import type { ReactNode } from "react";

/** One quiet heading across sign-in and account recovery. */
export function AuthHeading({ children }: { children: ReactNode }) {
  return (
    <h1 className="text-foreground text-2xl leading-tight font-medium tracking-tight text-balance">
      {children}
    </h1>
  );
}
