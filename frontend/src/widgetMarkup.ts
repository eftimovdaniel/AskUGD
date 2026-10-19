import { assetUrl } from "./config";
import { escapeHtmlAttr } from "./security";

type SuggestionLang = "mk" | "en";
type Suggestion = { lang: SuggestionLang; question: string };

const SUGGESTED_QUESTIONS: Record<SuggestionLang, string[]> = {
  mk: [
    "Кога е рокот за пријава на испити?",
    "Колку изнесува школарината за прв циклус?",
    "Како се заверува семестар?",
    "Колку кредити носи еден предмет?",
  ],
  en: [
    "When is the deadline to register for exams?",
    "How much is the tuition for first cycle studies?",
    "How do I certify a semester?",
    "How many credits does one course carry?",
  ],
};

/** Ги преплетува двата јазика: мк, анг, мк, анг... */
function interleaveSuggestions(): Suggestion[] {
  const { mk, en } = SUGGESTED_QUESTIONS;
  const out: Suggestion[] = [];
  for (let i = 0; i < Math.max(mk.length, en.length); i += 1) {
    if (mk[i]) out.push({ lang: "mk", question: mk[i] });
    if (en[i]) out.push({ lang: "en", question: en[i] });
  }
  return out;
}

/**
 * Лентата се врти бесконечно и може рачно да се врати наназад, па содржината се
 * исцртува трипати: една група за анимацијата, една за враќањето и една резерва
 * што ја покрива празнината кога двете поместувања се совпаднат. Копиите се
 * скриени од читачите на екран и извадени од tab-редоследот, за да не се
 * прочита/фокусира истото прашање повеќе пати.
 */
function renderSuggestionGroup(duplicate: boolean): string {
  const chips = interleaveSuggestions()
    .map(({ lang, question }) => {
      const safe = escapeHtmlAttr(question);
      const tabindex = duplicate ? ' tabindex="-1"' : "";
      return `<button type="button" class="ugd-ai-chip" lang="${lang}" data-question="${safe}"${tabindex}>${safe}</button>`;
    })
    .join("");
  const hidden = duplicate ? ' aria-hidden="true"' : "";
  return `<div class="ugd-ai-suggestions-group"${hidden}>${chips}</div>`;
}

export function getWidgetMarkup(apiUrl: string): string {
  const logo = assetUrl("assets/udg_symbol.png");
  const launcherIcon = assetUrl("assets/ai-agent-icon.png");
  const safeApi = escapeHtmlAttr(apiUrl);
  const chips = `${renderSuggestionGroup(false)}${renderSuggestionGroup(true)}${renderSuggestionGroup(true)}`;
  return `
  
<div class="ugd-ai-widget" id="ugd-ai-widget" data-open="false" data-api-url="${safeApi}">
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
          <p class="ugd-ai-desc">Прашај ме за упис, рокови, цени, кредити или административни постапки на УГД.</p>
        </div>
        <div class="ugd-ai-thread" id="ugd-ai-messages"></div>
      </div>
      <div class="ugd-ai-suggestions" id="ugd-ai-suggestions">
        <button type="button" class="ugd-ai-chip-nav" id="ugd-ai-suggestions-prev" aria-label="Претходни прашања" title="Претходни прашања">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" aria-hidden="true"><path d="M15 5 8 12l7 7" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
        <div class="ugd-ai-suggestions-window">
          <div class="ugd-ai-suggestions-shift" id="ugd-ai-suggestions-shift">
            <div class="ugd-ai-suggestions-track">${chips}</div>
          </div>
        </div>
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
