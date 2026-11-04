"use client";

import { createContext, useContext } from "react";
import { DEFAULT_TABLE_DISPLAY } from "@/lib/table-display";

export const TableDisplayContext = createContext(DEFAULT_TABLE_DISPLAY);
export function useTableDisplay() {
  return useContext(TableDisplayContext);
}
