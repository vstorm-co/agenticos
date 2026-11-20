"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useAppConnections, isCurrentAppConnectionScope } from "@/hooks/use-app-connections";
import { getErrorMessage } from "@/lib/api-error";
import {
  appAuthorizationUrl,
  appConnectionGoalForToolkit,
  appConnectionUsable,
  clearAppConnectionCallback,
  readAppConnectionCallback,
  rememberedAppConnectionGoal,
  rememberAppConnectionGoal,
  type AppConnectionGoal,
} from "@/lib/app-connection-journey";
import type { AppConnection, AppConnectionScope } from "@/types/app-connections";
import type { ConnectionAuthorizationTarget } from "./connection-authorization-dialog";

export function useConnectionJourney(scope: AppConnectionScope) {
  const t = useTranslations("appConnections");
  const tErrors = useTranslations("errors");
  const [arrival] = useState(() => {
    const search = typeof window === "undefined" ? "" : window.location.search;
    return {
      callback: readAppConnectionCallback(search),
      toolkit: new URLSearchParams(search).get("app"),
    };
  });
  const [catalogSearch, setCatalogSearch] = useState(arrival.toolkit ?? "");
  const [debouncedSearch, setDebouncedSearch] = useState(catalogSearch);
  useEffect(() => {
    const timeout = setTimeout(() => setDebouncedSearch(catalogSearch.trim()), 300);
    return () => clearTimeout(timeout);
  }, [catalogSearch]);
  const api = useAppConnections(scope, debouncedSearch);
  const [goal, setGoal] = useState(() =>
    appConnectionGoalForToolkit(arrival.toolkit, rememberedAppConnectionGoal(scope)),
  );
  const [step, setStep] = useState<1 | 2 | 3>(arrival.callback || arrival.toolkit ? 2 : 1);
  const [authorization, setAuthorization] = useState<ConnectionAuthorizationTarget | null>(null);
  const [disconnecting, setDisconnecting] = useState<AppConnection | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [callbackPending, setCallbackPending] = useState(arrival.callback !== null);
  const callback = useRef(arrival.callback);
  const callbackStarted = useRef(false);
  const callbackComplete = api.complete.mutateAsync;
  const current = useCallback(() => isCurrentAppConnectionScope(scope), [scope]);

  const verifyCallback = useCallback(async () => {
    if (!callback.current || !current()) return;
    try {
      const account = await callbackComplete(callback.current);
      if (!current()) return;
      setError(null);
      setStep(2);
      setMessage(t(appConnectionUsable(account) ? "callbackVerified" : "callbackPending"));
      callback.current = null;
      setCallbackPending(false);
    } catch (caught) {
      if (current()) setError(getErrorMessage(caught, tErrors, t("callbackFailed")));
    } finally {
      if (current()) clearAppConnectionCallback();
    }
  }, [callbackComplete, current, t, tErrors]);

  useEffect(() => {
    if (callbackStarted.current) return;
    callbackStarted.current = true;
    if (callback.current) {
      void verifyCallback();
    } else if (arrival.toolkit) rememberAppConnectionGoal(scope, goal);
  }, [arrival.toolkit, goal, scope, verifyCallback]);

  function chooseGoal(value: AppConnectionGoal) {
    setGoal(value);
    rememberAppConnectionGoal(scope, value);
  }

  async function authorize(label: string) {
    if (!authorization || !current()) return;
    setError(null);
    try {
      const result = await api.begin.mutateAsync({
        toolkit: authorization.app.toolkit,
        ...(authorization.connection ? { connectionId: authorization.connection.id } : { label }),
      });
      if (!current()) return;
      const url = appAuthorizationUrl(result.redirect_url);
      if (!url) {
        setError(t("invalidAuthorizationUrl"));
        return;
      }
      rememberAppConnectionGoal(scope, goal);
      window.location.assign(url);
    } catch (caught) {
      if (current()) setError(getErrorMessage(caught, tErrors, t("connectFailed")));
    }
  }

  async function perform(operation: () => Promise<unknown>, success: string) {
    setError(null);
    try {
      await operation();
      if (!current()) return;
      setMessage(success);
      setDisconnecting(null);
    } catch (caught) {
      if (current()) setError(getErrorMessage(caught, tErrors));
    }
  }

  const busy =
    api.begin.isPending ||
    api.complete.isPending ||
    api.remove.isPending ||
    api.refreshConnection.isPending ||
    api.setDefault.isPending ||
    api.enable.isPending;
  return {
    ...api,
    catalogSearch,
    setCatalogSearch,
    goal,
    chooseGoal,
    step,
    setStep,
    authorization,
    setAuthorization,
    disconnecting,
    setDisconnecting,
    message,
    error,
    setError,
    busy,
    authorize,
    perform,
    verifyCallback,
    callbackPending,
  };
}
