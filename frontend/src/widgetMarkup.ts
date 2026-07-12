import { assetUrl } from "./config";

export function getWidgetMarkup(apiUrl: string): string {
  const logo = assetUrl("assets/udg_symbol.png");
  const launcherIcon = assetUrl("assets/ai-agent-icon.png");

  return `
<div class="ugd-ai-widget" id="ugd-ai-widget" data-open="false" data-api-url="${apiUrl}">
  <div class="ugd-ai-stack">
    <section class="ugd-ai-panel" id="ugd-ai-panel" aria-hidden="true">
      <header class="ugd-ai-panel-header">
        <div class="ugd-ai-panel-header-brand" aria-hidden="true">
          <img class="ugd-ai-header-logo" src="${logo}" alt="" aria-hidden="true"/>
        </div>
        <div class="ugd-ai-panel-header-text">
          <div class="ugd-ai-panel-title">AskUGD</div>
          <div class="ugd-ai-panel-status">
            <span class="ugd-ai-status-dot" aria-hidden="true"></span>
            <span class="ugd-ai-panel-status-label">Интелигентен асистент на УГД – Штип</span>
          </div>
        </div>
        <div class="ugd-ai-panel-header-actions">
          <button type="button" class="ugd-ai-header-icon-btn ugd-ai-header-plus" id="ugd-ai-new-chat" aria-label="Нов разговор" title="Нов разговор">+</button>
        </div>
      </header>
      <div class="ugd-ai-panel-body">
        <div class="ugd-ai-intro" id="ugd-ai-intro">
          <p class="ugd-ai-greeting">Здраво 👋</p>
          <p class="ugd-ai-desc">Прашајте ме било што за Универзитетот „Гоце Делчев" – Штип.</p>
        </div>
        <div class="ugd-ai-thread" id="ugd-ai-messages"></div>
      </div>
      <form class="ugd-ai-footer-form" id="ugd-ai-form">
        <div class="ugd-ai-input-wrap">
          <input id="ugd-ai-input" type="text" autocomplete="off" maxlength="2000" placeholder="Напишете прашање..."/>
          <button type="submit" class="ugd-ai-send" aria-label="Испрати">
            <svg class="ugd-ai-send-svg" viewBox="0 0 24 24" width="18" height="18" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" fill="none"><path d="M22 2 11 13" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M22 2 15 22 11 13 2 9 22 2Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
        </div>
      </form>
    </section>
    <div class="ugd-ai-fabs">
      <button type="button" class="ugd-ai-launcher" id="ugd-ai-launcher" aria-expanded="false" aria-controls="ugd-ai-panel" aria-label="Отвори УГД асистент">
        <span class="ugd-ai-launcher-open" aria-hidden="true">
          <img class="ugd-ai-launcher-icon" src="${launcherIcon}" alt="" aria-hidden="true"/>
        </span>
        <span class="ugd-ai-launcher-close" aria-hidden="true">✕</span>
      </button>
    </div>
  </div>
</div>`.trim();
}
