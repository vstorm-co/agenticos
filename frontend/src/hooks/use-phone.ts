"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import {
  phoneApi,
  endedPhoneStatuses,
  type PhoneCallCreate,
  type PhoneContactConfig,
  type PhoneEndpointConfig,
} from "@/lib/phone-api";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";

export function usePhoneSettings() {
  const org = useOrgStore((state) => state.activeOrgId) ?? "current";
  const client = useQueryClient();
  const errors = useTranslations("errors");
  const query = useQuery({ queryKey: qk.phone.settings(org), queryFn: phoneApi.settings });
  const refresh = () => client.invalidateQueries({ queryKey: qk.phone.all(org) });
  const onError = (cause: unknown) => toast.error(getErrorMessage(cause, errors));
  const saveContact = useMutation({
    mutationFn: (data: PhoneContactConfig) => phoneApi.saveContact(data),
    onSuccess: refresh,
    onError,
  });
  const configure = useMutation({
    mutationFn: ({ botId, data }: { botId: string; data: PhoneEndpointConfig }) =>
      phoneApi.configure(botId, data),
    onSuccess: refresh,
    onError,
  });
  const call = useMutation({
    mutationFn: (data: PhoneCallCreate) => phoneApi.call(data),
    onSuccess: refresh,
    onError,
  });
  return { ...query, saveContact, configure, call };
}
export function usePhoneCalls() {
  const org = useOrgStore((state) => state.activeOrgId) ?? "current";
  return useQuery({
    queryKey: qk.phone.calls(org),
    queryFn: phoneApi.calls,
    refetchInterval: (query) =>
      query.state.data?.some((call) => !endedPhoneStatuses.has(call.status)) ? 4000 : false,
  });
}
export function usePhoneCall(id: string) {
  const org = useOrgStore((state) => state.activeOrgId) ?? "current";
  return useQuery({
    queryKey: qk.phone.call(org, id),
    queryFn: () => phoneApi.receipt(id),
    retry: false,
    refetchInterval: (query) =>
      query.state.data && !endedPhoneStatuses.has(query.state.data.status) ? 4000 : false,
  });
}
