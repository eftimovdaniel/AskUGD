/**
 * УГД AI асистент — frontend логика + backend API.
 */

import { assetUrl, getApiUrl } from "./config";
import { isLeakQuestion, LEAK_REFUSAL, scrubLeakedAnswer, stripControls } from "./promptGuard";
import { sanitizeHttpUrl } from "./security";

const MAX_MESSAGE_LENGTH = 2000;
const MAX_SOURCES = 3;
const SESSION_KEY = "askugd.session_id";
const SESSION_ID_RE = /^[A-Za-z0-9_-]{8,64}$/;
const UGD_HOST_RE = /(^|\.)ugd\.edu\.mk$/i;

const COPY = {
  open: "Отвори УГД асистент",
  close: "Затвори УГД асистент",
  newChat: "Нов разговор",
  greeting: "Здраво 👋",
  desc: "Прашај ме за упис, рокови, цени, кредити или административни постапки на УГД.",
  placeholder: "Напишете прашање...",
  send: "Испрати",
  typing: "Асистентот пишува",
  error: "Се појави грешка. Проверете дали backend-от работи и обидете се повторно.",
  rateLimit: "Премногу барања. Почекајте малку и обидете се повторно.",
  forbidden: "Асистентот работи само на страницата на УГД.",
  busy: "Сервисот е привремено преоптоварен. Обидете се подоцна.",
  source: "Извор",
  sources: "Извори",
} as const;

type ChatSource = {
  title: string;
  url: string | null;
  article_no: string | null;
};

type StreamEvent = {
  type?: string;
  token?: string;
  message?: string;
  session_id?: string;
  sources?: unknown;
};

type StreamResult = {
  sessionId: string | null;
  sources: ChatSource[];
};

function isSessionId(value: unknown): value is string {
  return typeof value === "string" && SESSION_ID_RE.test(value);
}

function readSessionId(): string | null {
  try {
    const saved = sessionStorage.getItem(SESSION_KEY);
    return isSessionId(saved) ? saved : null;
  } catch {
    return null;
  }
}

function writeSessionId(id: string): void {
  try {
    sessionStorage.setItem(SESSION_KEY, id);
  } catch {
    // private mode / blocked storage — сесијата останува само во меморија
  }
}

function clearSessionId(): void {
  try {
    sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // ignore
  }
}

function qs<T extends HTMLElement>(sel: string, root: ParentNode = document): T | null {
  return root.querySelector(sel) as T | null;
}

function sanitizeMessageText(text: string): string {
  return stripControls(text).trim().slice(0, MAX_MESSAGE_LENGTH);
}

function clearMessages(messagesEl: HTMLElement): void {
  messagesEl.replaceChildren();
}

function getApiBase(root: HTMLElement): string {
  const fromData = root.dataset.apiUrl?.trim();
  if (fromData) return sanitizeHttpUrl(fromData, getApiUrl());
  return getApiUrl();
}

function createAgentAvatar(): HTMLImageElement {
  const img = document.createElement("img");
  img.className = "ugd-ai-avatar";
  img.src = assetUrl("assets/udg_symbol.png");
  img.alt = "";
  img.setAttribute("aria-hidden", "true");
  return img;
}

function wrapAgentBubble(content: HTMLElement): HTMLDivElement {
  const row = document.createElement("div");
  row.className = "ugd-ai-msg-row ugd-ai-msg-row-agent";
  row.appendChild(createAgentAvatar());
  row.appendChild(content);
  return row;
}

function safeSourceUrl(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim();
  if (!trimmed) return null;
  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return null;
    if (!UGD_HOST_RE.test(parsed.hostname)) return null;
    return parsed.href;
  } catch {
    return null;
  }
}

function normalizeSources(raw: unknown): ChatSource[] {
  if (!Array.isArray(raw)) return [];
  const out: ChatSource[] = [];
  const seen = new Set<string>();
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const rec = item as Record<string, unknown>;
    const title = String(rec.title || rec.source || "").trim();
    if (!title || title === "?") continue;
    const url = safeSourceUrl(rec.url);
    const article = typeof rec.article_no === "string" ? rec.article_no.trim() : "";
    const key = (url || title).toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ title, url, article_no: article || null });
    if (out.length >= MAX_SOURCES) break;
  }
  return out;
}

function createSourcesEl(sources: ChatSource[]): HTMLDivElement {
  const wrap = document.createElement("div");
  wrap.className = "ugd-ai-sources";
  const label = document.createElement("span");
  label.className = "ugd-ai-sources-label";
  label.textContent = sources.length === 1 ? COPY.source : COPY.sources;
  const list = document.createElement("ul");
  for (const src of sources) {
    const li = document.createElement("li");
    const caption = src.article_no ? `${src.title} (${src.article_no})` : src.title;
    if (src.url) {
      const link = document.createElement("a");
      link.href = src.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = caption;
      li.appendChild(link);
    } else {
      li.textContent = caption;
    }
    list.appendChild(li);
  }
  wrap.appendChild(label);
  wrap.appendChild(list);
  return wrap;
}

function renderMarkdown(text: string): string {
  // 1) escape na HTML (XSS bezbednost), 2) minimalen Markdown -> HTML
  const escaped = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  return escaped
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/^#{1,4}\s+(.*)$/gm, "<strong>$1</strong>")
    .replace(/^\s*[-•]\s+(.*)$/gm, "&nbsp;&nbsp;• $1")
    .replace(/^\s*(\d+)\.\s+(.*)$/gm, "&nbsp;&nbsp;$1. $2")
    .replace(/\n/g, "<br>");
}

function createTextMessage(className: string, text: string): HTMLParagraphElement {
  const el = document.createElement("p");
  el.className = className;
  if (className.includes("ugd-ai-msg-agent")) {
    el.innerHTML = renderMarkdown(text);   // odgovorite od agentot se Markdown
  } else {
    el.textContent = text;                 // korisnichkiot vlez SEKOGASH kako tekst
  }
  return el;
}

function scrollToBottom(el: HTMLElement): void {
  // Skrolame SAMO vo telото na chat-panelot (.ugd-ai-panel-body so overflow-y:auto),
  // NIKOGAS celiot sajt. Porano se kacuvavme nagore po roditelite dodeka ne najdeme
  // "skrolabilen" element, no toa ponekogas go fakase celata stranica i ja vlecese
  // nadolu. Sega targetirame tocno panel-body preku closest(); ako go nema, skrolame
  // go samiot thread. requestAnimationFrame ceka DOM-ot da ja dodade novata poraka.
  requestAnimationFrame(() => {
    const cel = (el.closest(".ugd-ai-panel-body") as HTMLElement | null) ?? el;
    cel.scrollTo({ top: cel.scrollHeight, behavior: "smooth" });
  });
}

function createTypingIndicator(): HTMLDivElement {
  const typingEl = document.createElement("div");
  typingEl.className = "ugd-ai-typing";
  typingEl.setAttribute("role", "status");
  typingEl.setAttribute("aria-live", "polite");
  typingEl.setAttribute("aria-label", COPY.typing);
  for (let i = 0; i < 3; i += 1) {
    typingEl.appendChild(document.createElement("span"));
  }
  return typingEl;
}

async function streamBackend(
  apiBase: string,
  question: string,
  sessionId: string | null,
  onUpdate: (fullText: string) => void,
  onSession?: (id: string) => void,
): Promise<StreamResult> {
  const body: { question: string; session_id?: string } = { question };
  if (sessionId) body.session_id = sessionId;

  let response: Response;
  try {
    response = await fetch(`${apiBase}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error(
      "Не можам да се поврзам со backend-от. Стартувај го API-то на http://127.0.0.1:8000 и отвори ја страницата преку http (не file://).",
    );
  }

  if (response.status === 429) {
    throw new Error(COPY.rateLimit);
  }
  if (response.status === 403) {
    throw new Error(COPY.forbidden);
  }

  if (!response.ok || !response.body) {
    let detail: string = response.status === 503 ? COPY.busy : COPY.error;
    try {
      const payload = (await response.json()) as { detail?: string | { msg?: string }[] };
      if (typeof payload.detail === "string" && payload.detail) {
        detail = payload.detail;
      } else if (Array.isArray(payload.detail) && payload.detail[0]?.msg) {
        detail = String(payload.detail[0].msg);
      }
    } catch {
      // ignore parse errors
    }
    throw new Error(detail);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let full = "";
  let streamError: string | null = null;
  let receivedSession: string | null = sessionId;
  let sources: ChatSource[] = [];

  const applyEvent = (raw: string): void => {
    const line = raw.trim();
    if (!line.startsWith("data:")) return;
    const payload = line.slice(5).trim();
    if (!payload) return;
    let evt: StreamEvent;
    try {
      evt = JSON.parse(payload) as StreamEvent;
    } catch {
      return;
    }
    if (isSessionId(evt.session_id)) {
      receivedSession = evt.session_id;
      onSession?.(evt.session_id);
    }
    if (evt.type === "sources") {
      sources = normalizeSources(evt.sources);
    } else if (evt.type === "redact" && evt.message) {
      // Odbivanje — izvorite prateni pred tokenite ne smeat da ostanat pod nego.
      full = evt.message;
      sources = [];
      onUpdate(full);
    } else if (evt.type === "token" && evt.token) {
      full += evt.token;
      onUpdate(scrubLeakedAnswer(full));
    } else if (evt.type === "error") {
      streamError = evt.message || COPY.error;
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) applyEvent(part);
  }
  if (buffer.trim()) applyEvent(buffer);

  if (!full) {
    throw new Error(streamError || COPY.error);
  }
  return { sessionId: receivedSession, sources };
}

/** Колку пиксели наназад враќа едно притискање на стрелката. */
const SUGGESTION_STEP = 260;

/**
 * Лентата има две независни поместувања: CSS анимацијата што ја влече налево и
 * `--ugd-chip-shift` што стрелката ја враќа надесно. Бидејќи содржината се повторува
 * на секој период, поместување за цел период е визуелно невидливо — затоа шифтот се
 * враќа во опсегот [-период, 0) штом ќе го помине, и лентата никогаш не остава празнина.
 */
function initSuggestionRewind(wrap: HTMLElement, prevBtn: HTMLButtonElement | null): void {
  const shiftEl = qs<HTMLElement>("#ugd-ai-suggestions-shift", wrap);
  const group = shiftEl?.querySelector<HTMLElement>(".ugd-ai-suggestions-group");
  const track = shiftEl?.querySelector<HTMLElement>(".ugd-ai-suggestions-track");
  if (!shiftEl || !group || !track || !prevBtn) return;

  let period = 0;
  let shift = 0;

  const applyShift = (animate: boolean): void => {
    shiftEl.classList.toggle("is-stepping", animate);
    wrap.style.setProperty("--ugd-chip-shift", `${shift}px`);
  };

  const measure = (): void => {
    // Затворен панел значи нулта ширина — тогаш мерењето нема смисла.
    const width = group.getBoundingClientRect().width;
    if (width <= 0) return;
    const gap = parseFloat(getComputedStyle(track).columnGap) || 0;
    const next = width + gap;
    if (next === period) return;
    period = next;
    shift = -period;
    applyShift(false);
  };

  // Ширината се знае дури откако фонтовите ќе се вчитаат, па мери и потоа.
  measure();
  document.fonts?.ready.then(measure).catch(() => undefined);
  new ResizeObserver(measure).observe(group);

  prevBtn.addEventListener("click", () => {
    if (period <= 0) return;
    shift += SUGGESTION_STEP;
    applyShift(true);
  });

  shiftEl.addEventListener("transitionend", (e) => {
    if (e.propertyName !== "transform" || shift < 0) return;
    shift -= period;
    applyShift(false);
  });
}

export function initUgdAgent(): void {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => setupAgent(), { once: true });
  } else {
    setupAgent();
  }
}

function setupAgent(): void {
  const root = qs<HTMLElement>("#ugd-ai-widget");
  if (!root) return;

  const launcher = qs<HTMLButtonElement>("#ugd-ai-launcher", root);
  const panel = qs<HTMLElement>("#ugd-ai-panel", root);
  const form = qs<HTMLFormElement>("#ugd-ai-form", root);
  const input = qs<HTMLInputElement>("#ugd-ai-input", root);
  const messagesEl = qs<HTMLElement>("#ugd-ai-messages", root);
  const introEl = qs<HTMLElement>("#ugd-ai-intro", root);
  const suggestionsEl = qs<HTMLElement>("#ugd-ai-suggestions", root);
  const suggestionsPrev = qs<HTMLButtonElement>("#ugd-ai-suggestions-prev", root);
  const newChatBtn = qs<HTMLButtonElement>("#ugd-ai-new-chat", root);
  const apiBase = getApiBase(root);

  if (!launcher || !panel || !form || !input || !messagesEl) return;

  input.maxLength = MAX_MESSAGE_LENGTH;
  input.placeholder = COPY.placeholder;
  input.setAttribute("aria-label", COPY.placeholder);
  form.querySelector(".ugd-ai-send")?.setAttribute("aria-label", COPY.send);
  newChatBtn?.setAttribute("aria-label", COPY.newChat);
  newChatBtn?.setAttribute("title", COPY.newChat);
  launcher.setAttribute("aria-label", COPY.open);

  const introDesc = introEl?.querySelector(".ugd-ai-desc");
  if (introDesc) introDesc.textContent = COPY.desc;
  const introGreeting = introEl?.querySelector(".ugd-ai-greeting");
  if (introGreeting) introGreeting.textContent = COPY.greeting;

  if (suggestionsEl) initSuggestionRewind(suggestionsEl, suggestionsPrev);

  let busy = false;
  let sessionId = readSessionId();

  const setOpen = (open: boolean): void => {
    root.dataset.open = open ? "true" : "false";
    panel.classList.toggle("is-open", open);
    panel.setAttribute("aria-hidden", open ? "false" : "true");
    launcher.setAttribute("aria-expanded", open ? "true" : "false");
    launcher.setAttribute("aria-label", open ? COPY.close : COPY.open);
    if (open) input.focus();
  };

  const isOpen = (): boolean => root.dataset.open === "true";

  launcher.addEventListener("click", () => {
    setOpen(!isOpen());
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || !isOpen()) return;
    e.preventDefault();
    setOpen(false);
    launcher.focus();
  });

  newChatBtn?.addEventListener("click", () => {
    clearMessages(messagesEl);
    if (introEl) introEl.hidden = false;
    if (suggestionsEl) suggestionsEl.hidden = false;
    sessionId = null;
    clearSessionId();
    input.focus();
  });

  suggestionsEl?.addEventListener("click", (e) => {
    const chip = (e.target as HTMLElement | null)?.closest<HTMLButtonElement>(".ugd-ai-chip");
    if (!chip || busy) return;
    input.value = chip.dataset.question ?? chip.textContent ?? "";
    if (typeof form.requestSubmit === "function") {
      form.requestSubmit();
    } else {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    }
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (busy) return;

    const text = sanitizeMessageText(input.value);
    if (!text) return;

    if (introEl) introEl.hidden = true;
    if (suggestionsEl) suggestionsEl.hidden = true;

    const userEl = createTextMessage("ugd-ai-msg ugd-ai-msg-user", text);
    const userRow = document.createElement("div");
    userRow.className = "ugd-ai-msg-row ugd-ai-msg-row-user";
    userRow.appendChild(userEl);
    messagesEl.appendChild(userRow);
    input.value = "";
    scrollToBottom(messagesEl);

    if (isLeakQuestion(text)) {
      const botEl = createTextMessage("ugd-ai-msg ugd-ai-msg-agent", LEAK_REFUSAL);
      messagesEl.appendChild(wrapAgentBubble(botEl));
      scrollToBottom(messagesEl);
      input.focus();
      return;
    }

    busy = true;
    input.disabled = true;

    const typingEl = createTypingIndicator();
    const typingRow = wrapAgentBubble(typingEl);
    messagesEl.appendChild(typingRow);
    scrollToBottom(messagesEl);

    const botEl = createTextMessage("ugd-ai-msg ugd-ai-msg-agent", "");
    const botCol = document.createElement("div");
    botCol.className = "ugd-ai-msg-col";
    botCol.appendChild(botEl);
    const botRow = wrapAgentBubble(botCol);
    let mounted = false;

    try {
      const result = await streamBackend(
        apiBase,
        text,
        sessionId,
        (fullText) => {
          if (!mounted) {
            typingRow.remove();
            messagesEl.appendChild(botRow);
            mounted = true;
          }
          botEl.innerHTML = renderMarkdown(fullText);
          scrollToBottom(messagesEl);
        },
        (id) => {
          sessionId = id;
          writeSessionId(id);
        },
      );
      if (result.sessionId) {
        sessionId = result.sessionId;
        writeSessionId(result.sessionId);
      }
      if (result.sources.length) {
        botCol.appendChild(createSourcesEl(result.sources));
        scrollToBottom(messagesEl);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : COPY.error;
      if (!mounted) {
        typingRow.remove();
        const errEl = createTextMessage("ugd-ai-msg ugd-ai-msg-agent", message);
        messagesEl.appendChild(wrapAgentBubble(errEl));
      }
    } finally {
      busy = false;
      input.disabled = false;
      input.focus();
      scrollToBottom(messagesEl);
    }
  });
}
