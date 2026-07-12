export type EmbedConfig = {
  assetsBase: string;
  apiUrl: string;
};

let assetsBase = "";
let apiUrl = "http://127.0.0.1:8000";

function normalizeBase(base: string): string {
  if (!base) return "/";
  return base.endsWith("/") ? base : `${base}/`;
}

function findEmbedScript(): HTMLScriptElement | null {
  if (document.currentScript instanceof HTMLScriptElement) {
    return document.currentScript;
  }

  const byId = document.getElementById("ugd-ai-agent-script");
  if (byId instanceof HTMLScriptElement) return byId;

  const scripts = document.querySelectorAll<HTMLScriptElement>('script[src*="custom.js"]');
  return scripts.length ? scripts[scripts.length - 1] : null;
}

function resolveFromScript(): EmbedConfig | null {
  const script = findEmbedScript();
  if (!script?.src) return null;

  const scriptUrl = new URL(script.src, window.location.href);
  const derivedBase = scriptUrl.href.replace(/dist\/[^/]+$/, "");

  return {
    assetsBase: normalizeBase(script.dataset.assetsBase || derivedBase),
    apiUrl: script.dataset.apiUrl?.trim() || apiUrl,
  };
}

export function configureEmbed(config: EmbedConfig): void {
  assetsBase = normalizeBase(config.assetsBase);
  apiUrl = config.apiUrl.replace(/\/$/, "");
}

export function resolveEmbedConfig(): EmbedConfig {
  const fromScript = resolveFromScript();
  if (fromScript) return fromScript;

  return {
    assetsBase: normalizeBase(""),
    apiUrl,
  };
}

export function getAssetsBase(): string {
  return assetsBase;
}

export function assetUrl(path: string): string {
  const clean = path.replace(/^\//, "");
  if (!assetsBase || assetsBase === "/") return clean;
  return `${assetsBase}${clean}`;
}

export function getApiUrl(): string {
  return apiUrl;
}
