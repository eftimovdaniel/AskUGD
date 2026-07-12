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

function createTextMessage(className: string, text: string): HTMLParagraphElement {
  const el = document.createElement("p");
  el.className = className;
  el.textContent = text;
  return el;
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

async function askBackend(apiBase: string, question: string): Promise<string> {
  let response: Response;
  try {
    response = await fetch(`${apiBase}/api/chat`, {
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

  if (!response.ok) {
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

  const data = (await response.json()) as ChatApiResponse;
  return (data.answer || "").trim() || COPY.error;
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
    messagesEl.scrollTop = messagesEl.scrollHeight;

    const typingEl = createTypingIndicator();
    const typingRow = wrapAgentBubble(typingEl);
    messagesEl.appendChild(typingRow);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    try {
      const answer = await askBackend(apiBase, text);
      typingRow.remove();
      const botEl = createTextMessage("ugd-ai-msg ugd-ai-msg-agent", answer);
      messagesEl.appendChild(wrapAgentBubble(botEl));
    } catch (err) {
      typingRow.remove();
      const message = err instanceof Error ? err.message : COPY.error;
      const botEl = createTextMessage("ugd-ai-msg ugd-ai-msg-agent", message);
      messagesEl.appendChild(wrapAgentBubble(botEl));
    } finally {
      busy = false;
      input.disabled = false;
      input.focus();
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }
  });
}
