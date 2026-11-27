import { apiClient } from "@/lib/api-client";
import type { Organization } from "@/types";

export interface CurrencySettings {
  default_currency: string;
  rates: Record<string, string>;
}

export interface CurrencyContext {
  currency: string;
  default_currency: string;
  inherited: boolean;
  rates: Record<string, string>;
}

export const currencyApi = {
  current: (org: string) =>
    apiClient.get<CurrencyContext>("/providers/currencies", {
      headers: { "X-Organization-Id": org },
    }),
  organization: (id: string) => apiClient.get<CurrencyContext>(`/orgs/${id}/currency`),
  setOrganization: (id: string, currency: string | null) =>
    apiClient.patch<Organization>(`/orgs/${id}`, { currency }),
};

export function validCurrencySettings(value: CurrencySettings): boolean {
  return (
    Number(value.rates.USD) === 1 &&
    value.default_currency in value.rates &&
    Object.keys(value.rates).length <= 100 &&
    Object.entries(value.rates).every(
      ([code, rate]) =>
        /^[A-Z]{3}$/.test(code) &&
        rate.trim() !== "" &&
        Number.isFinite(Number(rate)) &&
        Number(rate) > 0,
    )
  );
}
