"use client";

import { useLayoutEffect, useRef, useState, type ComponentProps } from "react";
import {
  ListTodo,
  Heading2,
  List,
  ListOrdered,
  Quote,
  Code2,
  Minus,
  Table2,
  ImagePlus,
  Video,
  Link2,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { Textarea } from "@/components/ui";
import { discardTableImage } from "@/lib/tables-api";
import { markdownCaret } from "./markdown-caret";
import { useTableImageUpload } from "@/hooks/use-table-image-upload";

const BLOCKS = [
  { key: "todo", icon: ListTodo, body: "- [ ] " },
  { key: "heading", icon: Heading2, body: "## " },
  { key: "bullet", icon: List, body: "- " },
  { key: "numbered", icon: ListOrdered, body: "1. " },
  { key: "quote", icon: Quote, body: "> " },
  { key: "code", icon: Code2, body: "```\n\n```" },
  { key: "divider", icon: Minus, body: "\n---\n" },
  { key: "table", icon: Table2, body: "| Column | Column |\n| --- | --- |\n|  |  |\n" },
  { key: "image", icon: ImagePlus, body: "![](https://)" },
  { key: "video", icon: Video, body: "[Video](https://example.com/video.mp4)" },
  { key: "link", icon: Link2, body: "[](https://)" },
] as const;

type Slash = { start: number; end: number; query: string };

/** Only a slash at the start of a line is a command, never one inside a URL. */
function slashAt(value: string, caret: number): Slash | null {
  const start = value.lastIndexOf("\n", caret - 1) + 1;
  const match = /^\s*\/([^/\n]*)$/.exec(value.slice(start, caret));
  return match ? { start, end: caret, query: match[1] ?? "" } : null;
}

export function MarkdownInput({
  value,
  onValueChange,
  onImageInserted,
  tableId,
  ...props
}: Omit<ComponentProps<typeof Textarea>, "value" | "onChange"> & {
  value: string;
  onValueChange: (value: string) => void;
  onImageInserted: (value: string) => void;
  tableId?: string;
}) {
  const t = useTranslations("tables.markdown");
  const [slash, setSlash] = useState<Slash | null>(null);
  const [active, setActive] = useState(0);
  const [position, setPosition] = useState({ top: 56, left: 16 });
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const upload = useTableImageUpload(tableId);
  const current = useRef({ value, onValueChange, onImageInserted });
  useLayoutEffect(() => {
    current.current = { value, onValueChange, onImageInserted };
  }, [value, onValueChange, onImageInserted]);
  const matches = BLOCKS.filter((block) =>
    `${block.key} ${t(`blocks.${block.key}`)}`
      .toLowerCase()
      .includes(slash?.query.toLowerCase() ?? ""),
  );
  useLayoutEffect(() => {
    if (!slash) return;
    document.getElementById(`${props.id}-block-${active}`)?.scrollIntoView?.({ block: "nearest" });
  }, [active, slash, props.id]);
  const updateSlash = (text: string, caret: number) => {
    const next = slashAt(text, caret);
    setSlash(next);
    if (next && input.current) {
      const point = markdownCaret(input.current);
      setPosition({
        left: Math.max(8, Math.min(point.left, input.current.clientWidth - 272)),
        top: Math.max(8, Math.min(point.top, input.current.clientHeight - 120)),
      });
    }
    setActive(0);
  };
  const insertBlock = (body: string) => {
    if (!slash) return;
    onValueChange(value.slice(0, slash.start) + body + value.slice(slash.end));
    const caret = slash.start + body.length;
    setSlash(null);
    requestAnimationFrame(() => {
      input.current?.focus();
      input.current?.setSelectionRange(caret, caret);
    });
  };
  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <Textarea
        {...props}
        ref={input}
        value={value}
        readOnly={props.readOnly || uploading}
        aria-controls={slash ? `${props.id}-blocks` : undefined}
        aria-autocomplete="list"
        aria-activedescendant={slash && matches.length ? `${props.id}-block-${active}` : undefined}
        onChange={(event) => {
          onValueChange(event.target.value);
          updateSlash(event.target.value, event.target.selectionStart);
        }}
        onScroll={() => setSlash(null)}
        onBlur={() => setSlash(null)}
        onClick={(event) => updateSlash(value, event.currentTarget.selectionStart)}
        onKeyDown={(event) => {
          if (!slash) return;
          if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            setSlash(null);
          } else if (matches.length && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
            event.preventDefault();
            setActive(
              (index) =>
                (index + (event.key === "ArrowDown" ? 1 : -1) + matches.length) % matches.length,
            );
          } else if (event.key === "Enter" && !event.nativeEvent.isComposing && matches[active]) {
            event.preventDefault();
            insertBlock(matches[active].body);
          }
        }}
        onPaste={async (event) => {
          const images = Array.from(event.clipboardData.files).filter((file) =>
            file.type.startsWith("image/"),
          );
          if (!images.length || props.disabled || props.readOnly || uploading) return;
          event.preventDefault();
          setSlash(null);
          setError(false);
          if (!tableId || images.some((file) => file.size > 5 * 1024 * 1024)) {
            setError(true);
            return;
          }
          const element = event.currentTarget;
          const start = element.selectionStart,
            end = element.selectionEnd;
          setUploading(true);
          const completed: { id: string; url: string }[] = [];
          let committed = false;
          try {
            for (const image of images) completed.push(await upload(image));
            const inserted = completed.map((image) => `![](${image.url})`);
            // A navigation/unmount while uploading must not edit a different record.
            if (!element.isConnected || current.current.value !== value) return;
            const text = inserted.join("\n\n");
            const next = value.slice(0, start) + text + value.slice(end);
            current.current.onValueChange(next);
            current.current.onImageInserted(next);
            committed = true;
            requestAnimationFrame(() => {
              if (document.activeElement === element)
                element.setSelectionRange(start + text.length, start + text.length);
            });
          } catch {
            setError(true);
          } finally {
            if (!committed) {
              const cleanup = await Promise.allSettled(
                completed.map((image) => discardTableImage(tableId, image.id)),
              );
              if (cleanup.some((result) => result.status === "rejected")) setError(true);
            }
            setUploading(false);
          }
        }}
      />
      {uploading && (
        <p role="status" className="text-muted-foreground px-6 py-2 text-xs">
          {t("uploadingImage")}
        </p>
      )}
      {error && (
        <p role="alert" className="text-destructive px-6 py-2 text-xs">
          {t("imageUploadError")}
        </p>
      )}
      {slash && (
        <div
          id={`${props.id}-blocks`}
          role="listbox"
          aria-label={t("insertBlock")}
          style={position}
          className="bg-popover absolute z-20 max-h-72 w-64 overflow-y-auto rounded-xl border p-1.5 shadow-lg"
        >
          <p className="text-muted-foreground px-2 py-1.5 text-xs">{t("insertBlock")}</p>
          {matches.map(({ key, body, icon: Icon }, index) => (
            <div
              key={key}
              id={`${props.id}-block-${index}`}
              role="option"
              aria-selected={active === index}
            >
              <button
                type="button"
                tabIndex={-1}
                className={`flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-left text-sm ${active === index ? "bg-accent" : "hover:bg-accent"}`}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => insertBlock(body)}
              >
                <Icon className="text-muted-foreground size-4 shrink-0" aria-hidden />
                {t(`blocks.${key}`)}
              </button>
            </div>
          ))}
          {!matches.length && (
            <p className="text-muted-foreground px-3 py-2 text-sm">{t("noBlocks")}</p>
          )}
        </div>
      )}
    </div>
  );
}
