import { assetUrl, configureEmbed, resolveEmbedConfig } from "./config";
import { getWidgetMarkup } from "./widgetMarkup";

const STYLESHEET_ID = "ugd-ai-agent-styles";
const WIDGET_STYLE_VERSION = "1";

function ensureStylesheet(): void {
  if (document.getElementById(STYLESHEET_ID)) return;

  const link = document.createElement("link");
  link.id = STYLESHEET_ID;
  link.rel = "stylesheet";
  link.href = `${assetUrl("styles.css")}?v=${WIDGET_STYLE_VERSION}`;
  document.head.appendChild(link);
}

function ensureWidget(apiUrl: string): void {
  if (document.getElementById("ugd-ai-widget")) return;

  const mount = document.createElement("div");
  mount.innerHTML = getWidgetMarkup(apiUrl);
  const widget = mount.firstElementChild;
  if (!widget) return;

  document.body.appendChild(widget);
}

export function bootstrapEmbed(): void {
  const config = resolveEmbedConfig();
  configureEmbed(config);
  ensureStylesheet();
  ensureWidget(config.apiUrl);
}
