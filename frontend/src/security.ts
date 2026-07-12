/** Frontend безбедносни мерки за AskUGD виџетот. */

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
