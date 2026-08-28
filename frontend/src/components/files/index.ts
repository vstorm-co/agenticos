/**
 * One file viewer, and the pieces it is made of.
 *
 * There were four - a dialog for workspace files, a 545-line one for knowledge base
 * documents, a reading pane in a skill's file tree, and a resizable panel for chat
 * attachments - over three notions of "what kind of file is this" and two icon sets.
 * `FileViewer` is the dialog every surface opens; `FileContent` is it without the
 * dialog, for a surface that has its own chrome; `FileTextView` is it without the
 * fetching, for content already in hand.
 *
 * `FileEditor` is the write side of the same idea - a named draft, rendered by
 * default and editable behind a toggle. A skill's body, a skill's reference and a
 * context file are one object to a reader, so they get one pane.
 */

export { FileCard, PendingFileCard } from "./file-card";
export { FileContent } from "./file-content";
export { FileDropOverlay } from "./file-drop-overlay";
export { FileEditor } from "./file-editor";
export { FileIcon } from "./file-icon";
export { FileBytesView, FileTextView, FileUnavailable } from "./file-render";
export { FileViewer, type ViewerFile, type ViewerTab } from "./file-viewer";
export { PathTree, type PathTreeNode } from "./path-tree";
