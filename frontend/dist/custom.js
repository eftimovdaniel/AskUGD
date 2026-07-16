"use strict";
(() => {
  // src/security.ts
  function initFrontendSecurity() {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", () => hardenPage(), { once: true });
    } else {
      hardenPage();
    }
  }
  function hardenPage() {
    hardenBlankLinks();
  }
  function hardenBlankLinks() {
    document.querySelectorAll('a[target="_blank"]').forEach((link) => {
      const rel = link.getAttribute("rel") ?? "";
      const parts = new Set(rel.split(/\s+/).filter(Boolean));
      parts.add("noopener");
      parts.add("noreferrer");
      link.setAttribute("rel", [...parts].join(" "));
    });
  }

  // src/config.ts
  var assetsBase = "";
  var apiUrl = "http://127.0.0.1:8000";
  function normalizeBase(base) {
    if (!base) return "/";
    return base.endsWith("/") ? base : `${base}/`;
  }
  function findEmbedScript() {
    if (document.currentScript instanceof HTMLScriptElement) {
      return document.currentScript;
    }
    const byId = document.getElementById("ugd-ai-agent-script");
    if (byId instanceof HTMLScriptElement) return byId;
    const scripts = document.querySelectorAll('script[src*="custom.js"]');
    return scripts.length ? scripts[scripts.length - 1] : null;
  }
  function resolveFromScript() {
    const script = findEmbedScript();
    if (!script?.src) return null;
    const scriptUrl = new URL(script.src, window.location.href);
    const derivedBase = scriptUrl.href.replace(/dist\/[^/]+$/, "");
    return {
      assetsBase: normalizeBase(script.dataset.assetsBase || derivedBase),
      apiUrl: script.dataset.apiUrl?.trim() || apiUrl
    };
  }
  function configureEmbed(config) {
    assetsBase = normalizeBase(config.assetsBase);
    apiUrl = config.apiUrl.replace(/\/$/, "");
  }
  function resolveEmbedConfig() {
    const fromScript = resolveFromScript();
    if (fromScript) return fromScript;
    return {
      assetsBase: normalizeBase(""),
      apiUrl
    };
  }
  function assetUrl(path) {
    const clean = path.replace(/^\//, "");
    if (!assetsBase || assetsBase === "/") return clean;
    return `${assetsBase}${clean}`;
  }
  function getApiUrl() {
    return apiUrl;
  }

  // src/widgetMarkup.ts
  function getWidgetMarkup(apiUrl2) {
    const logo = assetUrl("assets/udg_symbol.png");
    const launcherIcon = assetUrl("assets/ai-agent-icon.png");
    return `
<div class="ugd-ai-widget" id="ugd-ai-widget" data-open="false" data-api-url="${apiUrl2}">
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
            <span class="ugd-ai-panel-status-label">\u0418\u043D\u0442\u0435\u043B\u0438\u0433\u0435\u043D\u0442\u0435\u043D \u0430\u0441\u0438\u0441\u0442\u0435\u043D\u0442 \u043D\u0430 \u0423\u0413\u0414 \u2013 \u0428\u0442\u0438\u043F</span>
          </div>
        </div>
        <div class="ugd-ai-panel-header-actions">
          <button type="button" class="ugd-ai-header-icon-btn ugd-ai-header-plus" id="ugd-ai-new-chat" aria-label="\u041D\u043E\u0432 \u0440\u0430\u0437\u0433\u043E\u0432\u043E\u0440" title="\u041D\u043E\u0432 \u0440\u0430\u0437\u0433\u043E\u0432\u043E\u0440">+</button>
        </div>
      </header>
      <div class="ugd-ai-panel-body">
        <div class="ugd-ai-intro" id="ugd-ai-intro">
          <p class="ugd-ai-greeting">\u0417\u0434\u0440\u0430\u0432\u043E \u{1F44B}</p>
          <p class="ugd-ai-desc">\u041F\u0440\u0430\u0448\u0430\u0458\u0442\u0435 \u043C\u0435 \u0431\u0438\u043B\u043E \u0448\u0442\u043E \u0437\u0430 \u0423\u043D\u0438\u0432\u0435\u0440\u0437\u0438\u0442\u0435\u0442\u043E\u0442 \u201E\u0413\u043E\u0446\u0435 \u0414\u0435\u043B\u0447\u0435\u0432" \u2013 \u0428\u0442\u0438\u043F.</p>
        </div>
        <div class="ugd-ai-thread" id="ugd-ai-messages"></div>
      </div>
      <form class="ugd-ai-footer-form" id="ugd-ai-form">
        <div class="ugd-ai-input-wrap">
          <input id="ugd-ai-input" type="text" autocomplete="off" maxlength="2000" placeholder="\u041D\u0430\u043F\u0438\u0448\u0435\u0442\u0435 \u043F\u0440\u0430\u0448\u0430\u045A\u0435..."/>
          <button type="submit" class="ugd-ai-send" aria-label="\u0418\u0441\u043F\u0440\u0430\u0442\u0438">
            <svg class="ugd-ai-send-svg" viewBox="0 0 24 24" width="18" height="18" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" fill="none"><path d="M22 2 11 13" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M22 2 15 22 11 13 2 9 22 2Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
        </div>
      </form>
    </section>
    <div class="ugd-ai-fabs">
      <button type="button" class="ugd-ai-launcher" id="ugd-ai-launcher" aria-expanded="false" aria-controls="ugd-ai-panel" aria-label="\u041E\u0442\u0432\u043E\u0440\u0438 \u0423\u0413\u0414 \u0430\u0441\u0438\u0441\u0442\u0435\u043D\u0442">
        <span class="ugd-ai-launcher-open" aria-hidden="true">
          <img class="ugd-ai-launcher-icon" src="${launcherIcon}" alt="" aria-hidden="true"/>
        </span>
        <span class="ugd-ai-launcher-close" aria-hidden="true">\u2715</span>
      </button>
    </div>
  </div>
</div>`.trim();
  }

  // src/embed.ts
  var STYLESHEET_ID = "ugd-ai-agent-styles";
  var WIDGET_STYLE_VERSION = "11";
  function ensureStylesheet() {
    if (document.getElementById(STYLESHEET_ID)) return;
    const link = document.createElement("link");
    link.id = STYLESHEET_ID;
    link.rel = "stylesheet";
    link.href = `${assetUrl("styles.css")}?v=${WIDGET_STYLE_VERSION}`;
    document.head.appendChild(link);
  }
  function ensureWidget(apiUrl2) {
    if (document.getElementById("ugd-ai-widget")) return;
    const mount = document.createElement("div");
    mount.innerHTML = getWidgetMarkup(apiUrl2);
    const widget = mount.firstElementChild;
    if (!widget) return;
    document.body.appendChild(widget);
  }
  function ensureFontAwesome() {
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
  function ensureBackToTop() {
    if (document.getElementById("ugd-back-to-top")) return;
    const link = document.createElement("a");
    link.id = "ugd-back-to-top";
    link.className = "a-top ugd-back-to-top";
    link.href = "#top";
    link.title = "\u041D\u0430\u0433\u043E\u0440\u0435";
    link.setAttribute("aria-label", "\u041D\u0430\u0433\u043E\u0440\u0435");
    link.innerHTML = '<i aria-hidden="true" class="fas fa-chevron-circle-up"></i>';
    document.body.appendChild(link);
  }
  function bootstrapEmbed() {
    const config = resolveEmbedConfig();
    configureEmbed(config);
    ensureStylesheet();
    ensureFontAwesome();
    ensureWidget(config.apiUrl);
    ensureBackToTop();
  }

  // src/localNav.ts
  var UGD_HOSTS = /* @__PURE__ */ new Set(["www.ugd.edu.mk", "ugd.edu.mk"]);
  function rewriteUgdLinksToLocal() {
    if (location.protocol === "file:") return;
    document.querySelectorAll("a[href]").forEach((link) => {
      try {
        const url = new URL(link.href, location.href);
        if (!UGD_HOSTS.has(url.hostname)) return;
        link.href = url.pathname + url.search + url.hash;
      } catch {
      }
    });
  }
  function initLocalNav() {
    const run = () => rewriteUgdLinksToLocal();
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", run, { once: true });
    } else {
      run();
    }
    const observer = new MutationObserver(() => rewriteUgdLinksToLocal());
    observer.observe(document.body, { childList: true, subtree: true });
  }

  // src/ugdAgent.ts
  var MAX_MESSAGE_LENGTH = 2e3;
  var COPY = {
    open: "\u041E\u0442\u0432\u043E\u0440\u0438 \u0423\u0413\u0414 \u0430\u0441\u0438\u0441\u0442\u0435\u043D\u0442",
    close: "\u0417\u0430\u0442\u0432\u043E\u0440\u0438 \u0423\u0413\u0414 \u0430\u0441\u0438\u0441\u0442\u0435\u043D\u0442",
    newChat: "\u041D\u043E\u0432 \u0440\u0430\u0437\u0433\u043E\u0432\u043E\u0440",
    greeting: "\u0417\u0434\u0440\u0430\u0432\u043E \u{1F44B}",
    desc: '\u041F\u0440\u0430\u0448\u0430\u0458\u0442\u0435 \u043C\u0435 \u0431\u0438\u043B\u043E \u0448\u0442\u043E \u0437\u0430 \u0423\u043D\u0438\u0432\u0435\u0440\u0437\u0438\u0442\u0435\u0442\u043E\u0442 \u201E\u0413\u043E\u0446\u0435 \u0414\u0435\u043B\u0447\u0435\u0432" \u2013 \u0428\u0442\u0438\u043F.',
    placeholder: "\u041D\u0430\u043F\u0438\u0448\u0435\u0442\u0435 \u043F\u0440\u0430\u0448\u0430\u045A\u0435...",
    send: "\u0418\u0441\u043F\u0440\u0430\u0442\u0438",
    typing: "\u0410\u0441\u0438\u0441\u0442\u0435\u043D\u0442\u043E\u0442 \u043F\u0438\u0448\u0443\u0432\u0430",
    error: "\u0421\u0435 \u043F\u043E\u0458\u0430\u0432\u0438 \u0433\u0440\u0435\u0448\u043A\u0430. \u041F\u0440\u043E\u0432\u0435\u0440\u0435\u0442\u0435 \u0434\u0430\u043B\u0438 backend-\u043E\u0442 \u0440\u0430\u0431\u043E\u0442\u0438 \u0438 \u043E\u0431\u0438\u0434\u0435\u0442\u0435 \u0441\u0435 \u043F\u043E\u0432\u0442\u043E\u0440\u043D\u043E.",
    rateLimit: "\u041F\u0440\u0435\u043C\u043D\u043E\u0433\u0443 \u0431\u0430\u0440\u0430\u045A\u0430. \u041F\u043E\u0447\u0435\u043A\u0430\u0458\u0442\u0435 \u043C\u0430\u043B\u043A\u0443 \u0438 \u043E\u0431\u0438\u0434\u0435\u0442\u0435 \u0441\u0435 \u043F\u043E\u0432\u0442\u043E\u0440\u043D\u043E."
  };
  function qs(sel, root = document) {
    return root.querySelector(sel);
  }
  function sanitizeMessageText(text) {
    return text.trim().slice(0, MAX_MESSAGE_LENGTH);
  }
  function clearMessages(messagesEl) {
    messagesEl.replaceChildren();
  }
  function getApiBase(root) {
    const fromData = root.dataset.apiUrl?.trim();
    if (fromData) return fromData.replace(/\/$/, "");
    return getApiUrl();
  }
  function createAgentAvatar() {
    const img = document.createElement("img");
    img.className = "ugd-ai-avatar";
    img.src = assetUrl("assets/udg_symbol.png");
    img.alt = "";
    img.setAttribute("aria-hidden", "true");
    return img;
  }
  function wrapAgentBubble(content) {
    const row = document.createElement("div");
    row.className = "ugd-ai-msg-row ugd-ai-msg-row-agent";
    row.appendChild(createAgentAvatar());
    row.appendChild(content);
    return row;
  }
  function createTextMessage(className, text) {
    const el = document.createElement("p");
    el.className = className;
    el.textContent = text;
    return el;
  }
  function createTypingIndicator() {
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
  async function askBackend(apiBase, question) {
    let response;
    try {
      response = await fetch(`${apiBase}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question })
      });
    } catch {
      throw new Error(
        "\u041D\u0435 \u043C\u043E\u0436\u0430\u043C \u0434\u0430 \u0441\u0435 \u043F\u043E\u0432\u0440\u0437\u0430\u043C \u0441\u043E backend-\u043E\u0442. \u0421\u0442\u0430\u0440\u0442\u0443\u0432\u0430\u0458 \u0433\u043E API-\u0442\u043E \u043D\u0430 http://127.0.0.1:8000 \u0438 \u043E\u0442\u0432\u043E\u0440\u0438 \u0458\u0430 \u0441\u0442\u0440\u0430\u043D\u0438\u0446\u0430\u0442\u0430 \u043F\u0440\u0435\u043A\u0443 http (\u043D\u0435 file://)."
      );
    }
    if (response.status === 429) {
      throw new Error(COPY.rateLimit);
    }
    if (!response.ok) {
      let detail = COPY.error;
      try {
        const payload = await response.json();
        if (typeof payload.detail === "string" && payload.detail) {
          detail = payload.detail;
        } else if (Array.isArray(payload.detail) && payload.detail[0]?.msg) {
          detail = String(payload.detail[0].msg);
        }
      } catch {
      }
      throw new Error(detail);
    }
    const data = await response.json();
    return (data.answer || "").trim() || COPY.error;
  }
  function initUgdAgent() {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", () => setupAgent(), { once: true });
    } else {
      setupAgent();
    }
  }
  function setupAgent() {
    const root = qs("#ugd-ai-widget");
    if (!root) return;
    const launcher = qs("#ugd-ai-launcher", root);
    const panel = qs("#ugd-ai-panel", root);
    const form = qs("#ugd-ai-form", root);
    const input = qs("#ugd-ai-input", root);
    const messagesEl = qs("#ugd-ai-messages", root);
    const introEl = qs("#ugd-ai-intro", root);
    const newChatBtn = qs("#ugd-ai-new-chat", root);
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
    const setOpen = (open) => {
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

  // src/main.ts
  bootstrapEmbed();
  initLocalNav();
  initFrontendSecurity();
  initUgdAgent();
})();
