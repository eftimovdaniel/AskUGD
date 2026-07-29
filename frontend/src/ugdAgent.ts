/**
 * УГД AI асистент — frontend логика + backend API.
 */

import { assetUrl, getApiUrl } from "./config";

const MAX_MESSAGE_LENGTH = 2000;

const COPY = {
  open: "Отвори УГД асистент",
  close: "Затвори УГД асистент",
  newChat: "Нов разговор",
  greeting: "Здраво 👋",
  desc: 'Прашајте ме било што за Универзитетот „Гоце Делчев" – Штип.',
  placeholder: "Напишете прашање...",
  send: "Испрати",
  typing: "Асистентот пишува",
  error: "Се појави грешка. Проверете дали backend-от работи и обидете се повторно.",
  rateLimit: "Премногу барања. Почекајте малку и обидете се повторно.",
} as const;

type ChatApiResponse = {
  answer: string;
  sources?: string[];
};

function qs<T extends HTMLElement>(sel: string, root: ParentNode = document): T | null {
  return root.querySelector(sel) as T | null;
}

function sanitizeMessageText(text: string): string {
  return text.trim().slice(0, MAX_MESSAGE_LENGTH);
}

function clearMessages(messagesEl: HTMLElement): void {
  messagesEl.replaceChildren();
}

function getApiBase(root: HTMLElement): string {
  const fromData = root.dataset.apiUrl?.trim();
  if (fromData) return fromData.replace(/\/$/, "");
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
  // Skrolabilen e RODITELOT (.ugd-ai-panel-body so overflow-y:auto), ne samiot
  // thread — zatoa se kacuvame nagore dodeka ne najdeme element sto navistina
  // moze da skrola. requestAnimationFrame ceka DOM-ot da se prerascita, inaku
  // scrollHeight se cita PRED novata poraka da zafati prostor i ne stiga do dno.
  const najdiSkrolabilen = (nod: HTMLElement | null): HTMLElement | null => {
    while (nod) {
      if (nod.scrollHeight > nod.clientHeight + 4) return nod;
      nod = nod.parentElement;
    }
    return null;
  };
  requestAnimationFrame(() => {
    const cel = najdiSkrolabilen(el);
    if (cel) cel.scrollTo({ top: cel.scrollHeight, behavior: "smooth" });
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
  onUpdate: (fullText: string) => void,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${apiBase}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
  } catch {
    throw new Error(
      "Не можам да се поврзам со backend-от. Стартувај го API-то на http://127.0.0.1:8000 и отвори ја страницата преку http (не file://).",
    );
  }

  if (response.status === 429) {
    throw new Error(COPY.rateLimit);
  }

  if (!response.ok || !response.body) {
    let detail: string = COPY.error;
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

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data:")) continue;
      const payload = line.slice(5).trim();
      if (!payload) continue;
      let evt: { type?: string; token?: string; message?: string };
      try {
        evt = JSON.parse(payload);
      } catch {
        continue;
      }
      if (evt.type === "token" && evt.token) {
        full += evt.token;
        onUpdate(full);
      } else if (evt.type === "error") {
        streamError = evt.message || COPY.error;
      }
    }
  }

  if (!full) {
    throw new Error(streamError || COPY.error);
  }
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

  let busy = false;

  const setOpen = (open: boolean): void => {
    root.dataset.open = open ? "true" : "false";
    panel.classList.toggle("is-open", open);
    panel.setAttribute("aria-hidden", open ? "false" : "true");
    launcher.setAttribute("aria-expanded", open ? "true" : "false");
    launcher.setAttribute("aria-label", open ? COPY.close : COPY.open);
    if (open) input.focus();
  };

  launcher.addEventListener("click", () => {
    setOpen(root.dataset.open !== "true");
  });

  newChatBtn?.addEventListener("click", () => {
    clearMessages(messagesEl);
    if (introEl) introEl.hidden = false;
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (busy) return;

    const text = sanitizeMessageText(input.value);
    if (!text) return;

    if (introEl) introEl.hidden = true;

    const userEl = createTextMessage("ugd-ai-msg ugd-ai-msg-user", text);
    const userRow = document.createElement("div");
    userRow.className = "ugd-ai-msg-row ugd-ai-msg-row-user";
    userRow.appendChild(userEl);
    messagesEl.appendChild(userRow);

    input.value = "";
    busy = true;
    input.disabled = true;
    scrollToBottom(messagesEl);

    const typingEl = createTypingIndicator();
    const typingRow = wrapAgentBubble(typingEl);
    messagesEl.appendChild(typingRow);
    scrollToBottom(messagesEl);

    const botEl = createTextMessage("ugd-ai-msg ugd-ai-msg-agent", "");
    const botRow = wrapAgentBubble(botEl);
    let mounted = false;

    try {
      await streamBackend(apiBase, text, (fullText) => {
        if (!mounted) {
          typingRow.remove();
          messagesEl.appendChild(botRow);
          mounted = true;
        }
        botEl.innerHTML = renderMarkdown(fullText);
        scrollToBottom(messagesEl);
      });
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
