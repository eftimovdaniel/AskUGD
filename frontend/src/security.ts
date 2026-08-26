/** Frontend безбедносни hardening мерки за статичниот UGD клон. */

export function escapeHtmlAttr(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export function sanitizeHttpUrl(raw: string, fallback: string): string {
  const trimmed = (raw || "").trim();
  if (!trimmed) return fallback;
  try {
    const base = typeof window !== "undefined" ? window.location.href : "http://127.0.0.1";
    const parsed = new URL(trimmed, base);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return fallback;
    const path = parsed.pathname.replace(/\/$/, "");
    return `${parsed.origin}${path}`;
  } catch {
    return fallback;
  }
}

export function initFrontendSecurity(): void {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => hardenPage(), { once: true });
  } else {
    hardenPage();
  }
}

function hardenPage(): void {
  hardenBlankLinks();
}

function hardenBlankLinks(): void {
  document.querySelectorAll<HTMLAnchorElement>('a[target="_blank"]').forEach((link) => {
    const rel = link.getAttribute("rel") ?? "";
    const parts = new Set(rel.split(/\s+/).filter(Boolean));
    parts.add("noopener");
    parts.add("noreferrer");
    link.setAttribute("rel", [...parts].join(" "));
  });
}
