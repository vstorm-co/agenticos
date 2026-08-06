"use client";

import { ProviderIcon } from "@/components/vault/provider-icon";
import { cn } from "@/lib/utils";

interface ProviderRowProps {
  /**
   * The catalog id whose mark is drawn.
   *
   * A provider id where a provider is being chosen (`openrouter`), and a
   * secret's `purpose` where a key is - the two are the same namespace, which
   * is what makes a key's brand mark a lookup rather than a second table
   * somebody has to keep in step.
   */
  provider: string;
  /** What the thing is called, in the words its own catalog uses. */
  name: string;
  /**
   * The four characters that identify a stored key, drawn masked: `····3123`.
   *
   * The mask belongs here rather than at each caller, because it is the
   * convention that makes a hint read as a redacted credential everywhere the
   * vault shows one.
   */
  hint?: string;
  className?: string;
}

/**
 * One row of a provider or key picker: the brand mark, the name, and the masked
 * tail of a key where there is one.
 *
 * Choosing a provider and choosing a key for a provider are the same act, and
 * they were drawn six different ways - a marked row in the Builder, bare strings
 * in Create knowledge base, name-plus-hint in the sandbox connection dialog.
 * Three clicks apart in one product, and not recognisably the same product.
 *
 * **A tick does not belong in here.** Radix mirrors a `SelectItem`'s
 * `ItemText` children into `SelectValue`, so anything in this row is also drawn
 * in the closed trigger - which is right for the mark and wrong for a tick
 * meaning "this provider already has a key": in a trigger, next to nothing to
 * compare it with, it reads as "selected". `SelectItem` takes it as `trailing`
 * instead, where it stays in the list.
 */
export function ProviderRow({ provider, name, hint, className }: ProviderRowProps) {
  return (
    <span className={cn("flex min-w-0 items-center gap-2", className)}>
      <ProviderIcon provider={provider} />
      <span className="truncate">{name}</span>
      {hint !== undefined && (
        <span className="text-muted-foreground shrink-0 font-mono">····{hint}</span>
      )}
    </span>
  );
}
