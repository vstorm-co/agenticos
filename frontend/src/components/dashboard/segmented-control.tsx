"use client";

import { cn } from "@/lib/utils";

interface SegmentedControlProps {
  value: string;
  onChange: (value: string) => void;
  options: { label: string; value: string }[];
  className?: string;
}

export function SegmentedControl({ value, onChange, options, className }: SegmentedControlProps) {
  return (
    <div className={cn("bg-muted inline-flex rounded-full p-1", className)}>
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={cn(
            "rounded-full px-3.5 py-1 text-xs font-medium transition-colors",
            // The raised card pill is the selection signal, same grammar as
            // the tab strip - one control language across the product.
            value === opt.value
              ? "bg-card text-foreground shadow-card"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
