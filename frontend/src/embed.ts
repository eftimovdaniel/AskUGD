/**
 * Vmetnuvanje na vidzetot vo stranicata: CSS, Font Awesome, HTML, „nagore“.
 * WIDGET_STYLE_VERSION — cache-busting koga se menuva styles.css.
 */
import { assetUrl, configureEmbed, resolveEmbedConfig } from "./config";
import { getWidgetMarkup } from "./widgetMarkup";

const STYLESHEET_ID = "ugd-ai-agent-styles";
const WIDGET_STYLE_VERSION = "13";

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

function ensureFontAwesome(): void {
  if (!document.getElementById("ugd-fa-base")) {
    const base = document.createElement("link");
    base.id = "ugd-fa-base";
    base.rel = "stylesheet";
    base.href = assetUrl("Styles/fontawesome.min.css");
    document.head.appendChild(base);
  }
  if (!document.getElementById("ugd-fa-solid")) {
    const solid = document.createElement("link");
    solid.id = "ugd-fa-solid";
    solid.rel = "stylesheet";
    solid.href = assetUrl("Styles/solid.min.css");
    document.head.appendChild(solid);
  }
}

/** Kopce „nagore“ kako na ugd.edu.mk — ne e del od chatot. */
function ensureBackToTop(): void {
  if (document.getElementById("ugd-back-to-top")) return;

  const link = document.createElement("a");
  link.id = "ugd-back-to-top";
  link.className = "a-top ugd-back-to-top";
  link.href = "#top";
  link.title = "Нагоре";
  link.setAttribute("aria-label", "Нагоре");
  link.innerHTML = '<i aria-hidden="true" class="fas fa-chevron-circle-up"></i>';

  document.body.appendChild(link);
}

export function bootstrapEmbed(): void {
  const config = resolveEmbedConfig();
  configureEmbed(config);
  ensureStylesheet();
  ensureFontAwesome();
  ensureWidget(config.apiUrl);
  ensureBackToTop();
}
