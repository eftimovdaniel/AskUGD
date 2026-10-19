const UGD_HOSTS = new Set(["www.ugd.edu.mk", "ugd.edu.mk"]);

/** Локално: линковите кон ugd.edu.mk остануваат на истиот origin (proxy), не на вистинскиот сајт. */
export function rewriteUgdLinksToLocal(): void {
  if (location.protocol === "file:") return;

  document.querySelectorAll<HTMLAnchorElement>("a[href]").forEach((link) => {
    try {
      const url = new URL(link.href, location.href);
      if (!UGD_HOSTS.has(url.hostname)) return;

      link.href = url.pathname + url.search + url.hash;
    } catch {
      // ignore invalid URLs
    }
  });
}

export function initLocalNav(): void {
  const run = () => rewriteUgdLinksToLocal();

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run, { once: true });
  } else {
    run();
  }

  // Elementor / менија понекогаш додаваат линкови подоцна.
  const observer = new MutationObserver(() => rewriteUgdLinksToLocal());
  observer.observe(document.body, { childList: true, subtree: true });
}
