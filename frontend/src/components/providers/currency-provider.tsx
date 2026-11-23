"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import { useCurrencies } from "@/hooks/use-currencies";
import type { CurrencyContext } from "@/lib/currency-api";
import { moneyFor } from "@/lib/money";

// Shared/public components without a workspace retain the USD API convention.
const Context = createContext<CurrencyContext | null>({
  currency: "USD",
  default_currency: "USD",
  inherited: true,
  rates: { USD: "1" },
});

export function CurrencyProvider({ children }: { children: ReactNode }) {
  const { data } = useCurrencies();
  return <Context value={data ?? null}>{children}</Context>;
}

/** Read the active tenant's money context without issuing per-cell requests. */
export function useMoney() {
  const context = useContext(Context);
  return useMemo(() => moneyFor(context), [context]);
}
