"use client";

import { create } from "zustand";
import type { ChatMessageFile } from "@/types";

interface FilePreviewState {
  /**
   * Every file this conversation carries, in the order it arrived.
   *
   * Held here rather than passed by whoever opened one, and that is the fix for a
   * dialog that paged when it was opened from the Files panel and did not when the
   * same file was clicked in the transcript: the panel had the conversation's list
   * and a message had only its own attachments, so clicking a message that carried
   * one file opened a set of one. Where a file was clicked is not a fact about
   * which other files exist.
   *
   * Set by the chat container, which derives it from the messages.
   */
  available: ChatMessageFile[];
  /** The file being read, or `null` when the dialog is closed. */
  openId: string | null;
  setAvailable: (files: ChatMessageFile[]) => void;
  /**
   * Open one file.
   *
   * Nothing but the file, because the set is already here. One that is not in
   * `available` still opens - a surface can hold a file the transcript does not,
   * and refusing to show it would be worse than showing it alone.
   */
  open: (file: ChatMessageFile) => void;
  select: (index: number) => void;
  close: () => void;
}

export const useFilePreviewStore = create<FilePreviewState>((set) => ({
  available: [],
  openId: null,
  setAvailable: (files) => set({ available: files }),
  open: (file) =>
    set((state) =>
      state.available.some((one) => one.id === file.id)
        ? { openId: file.id }
        : { available: [file], openId: file.id },
    ),
  select: (index) =>
    set((state) => {
      const file = state.available[index];
      return file === undefined ? {} : { openId: file.id };
    }),
  close: () => set({ openId: null }),
}));
