// Helpers shared by the views: formatting, error text, keyboard focus and downloads.

export const pad2 = (n: number) => String(n).padStart(2, "0");

/** Seconds as mm:ss. */
export const clock = (t: number) => `${pad2(Math.floor(t / 60))}:${pad2(Math.floor(t % 60))}`;

/** A 0-1 ratio as a whole percentage; missing counts as 0. */
export const pct = (v: number | null | undefined) => `${Math.round((v ?? 0) * 100)}%`;

/** Operator id of the i-th detection (0-based): TRGT-01, TRGT-02, ... */
export const targetId = (i: number) => `TRGT-${pad2(i + 1)}`;

/** Source time of a frame, or STILL when it comes from a still image. */
export const frameTime = (kind: string | null, t: number) => (kind === "image" ? "STILL" : clock(t));

/** Readable text of anything thrown: its message when it has one, else its string form. */
export function errorText(e: unknown): string {
  const message = (e as { message?: unknown } | null | undefined)?.message;
  return message ? String(message) : String(e);
}

/** True when a key event comes from a text field, where global shortcuts must not fire. */
export function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA");
}

/** Save a URL (an object URL or an API download) under a file name. */
export function download(href: string, filename: string): void {
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/** Save text as a file of the given MIME type. */
export function saveText(text: string, type: string, filename: string): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  download(url, filename);
  URL.revokeObjectURL(url);
}
