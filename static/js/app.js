/* TOMONI Beauty — 共通スクリプト（コピー→LINEを開く、録音、ポーリング、PWA） */
(function () {
  "use strict";

  const csrf = () => {
    const m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : (document.querySelector("[name=csrfmiddlewaretoken]") || {}).value || "";
  };
  window.TOMONI = window.TOMONI || {};
  window.TOMONI.csrf = csrf;

  // ---- toast ----
  function toast(text, kind) {
    const wrap = document.querySelector(".messages") || (() => {
      const d = document.createElement("div");
      d.className = "messages";
      document.body.appendChild(d);
      return d;
    })();
    const el = document.createElement("div");
    el.className = "toast " + (kind || "");
    el.textContent = text;
    wrap.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  }
  window.TOMONI.toast = toast;

  // ---- クリップボード ----
  async function copyText(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (e) { /* fallthrough */ }
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-1000px";
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    ta.remove();
    return ok;
  }
  window.TOMONI.copyText = copyText;

  // data-copy-source="#id" を持つ要素: クリックでコピー。data-open-url があれば続けてそのURLを開く（LINEチャット）
  document.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-copy-source]");
    if (!btn) return;
    const src = document.querySelector(btn.getAttribute("data-copy-source"));
    if (!src) return;
    const text = "value" in src ? src.value : src.textContent;
    const openUrl = btn.getAttribute("data-open-url");
    // 画面遷移前にコピー（ユーザー操作のコンテキスト内で実行する必要がある）
    const ok = await copyText(text);
    if (ok) {
      toast(openUrl ? "コピーしました。LINEを開きます…" : "コピーしました", "success");
    } else {
      toast("コピーできませんでした。長押しでコピーしてください", "error");
    }
    const after = btn.getAttribute("data-after-copy");
    if (after) {
      const target = document.querySelector(after);
      if (target) target.classList.remove("hidden"), (target.style.display = "");
    }
    if (openUrl && ok) {
      // 新しいタブで開くと戻ってきたときに「送った」を押せる
      window.open(openUrl, "_blank", "noopener");
    }
  });

  // data-share-source: Web Share API（共有先から LINE を選ぶ補助ルート）
  document.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-share-source]");
    if (!btn) return;
    const src = document.querySelector(btn.getAttribute("data-share-source"));
    if (!src) return;
    const text = "value" in src ? src.value : src.textContent;
    if (navigator.share) {
      try { await navigator.share({ text }); } catch (e) { /* cancelled */ }
    } else {
      await copyText(text);
      toast("この端末は共有に対応していないためコピーしました");
    }
  });

  // ---- 自動保存 textarea (data-autosave-url) ----
  document.querySelectorAll("textarea[data-autosave-url]").forEach((ta) => {
    let timer = null;
    const status = document.querySelector(ta.getAttribute("data-autosave-status") || "#autosave-status");
    ta.addEventListener("input", () => {
      if (status) status.textContent = "編集中…";
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const fd = new FormData();
        fd.append("body", ta.value);
        try {
          const r = await fetch(ta.getAttribute("data-autosave-url"), {
            method: "POST",
            headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" },
            body: fd,
          });
          if (status) status.textContent = r.ok ? "保存しました" : "保存できませんでした";
        } catch (e) {
          if (status) status.textContent = "保存できませんでした（オフライン？）";
        }
      }, 800);
    });
  });

  // ---- ポーリング (data-poll-url, data-poll-redirect-key) ----
  document.querySelectorAll("[data-poll-url]").forEach((el) => {
    const url = el.getAttribute("data-poll-url");
    const bar = el.querySelector("[data-poll-bar]");
    const label = el.querySelector("[data-poll-label]");
    const errBox = el.querySelector("[data-poll-error]");
    let tries = 0;
    async function tick() {
      tries += 1;
      try {
        const r = await fetch(url, { headers: { "X-Requested-With": "fetch" }, cache: "no-store" });
        const data = await r.json();
        if (bar && data.percent != null) bar.style.width = data.percent + "%";
        if (label && data.label) label.textContent = data.label;
        if (data.redirect) { window.location.href = data.redirect; return; }
        if (data.done === true) { window.location.reload(); return; }
        if (data.status === "failed") {
          if (errBox) { errBox.textContent = data.error || "失敗しました"; errBox.style.display = ""; }
          window.location.reload();
          return;
        }
      } catch (e) { /* retry */ }
      setTimeout(tick, tries < 10 ? 2000 : 4000);
    }
    setTimeout(tick, 1500);
  });

  // ---- Reply トークンのカウントダウン ----
  document.querySelectorAll("[data-countdown]").forEach((el) => {
    let left = parseInt(el.getAttribute("data-countdown"), 10);
    const target = document.querySelector(el.getAttribute("data-countdown-disable") || "");
    function step() {
      if (left <= 0) {
        el.textContent = "期限切れ";
        if (target) { target.classList.add("disabled"); target.setAttribute("disabled", "disabled"); }
        const alt = document.querySelector(el.getAttribute("data-countdown-show") || "");
        if (alt) alt.style.display = "";
        return;
      }
      el.textContent = left + "秒";
      left -= 1;
      setTimeout(step, 1000);
    }
    step();
  });

  // ---- 同意トグル (data-consent-url) ----
  document.querySelectorAll("[data-consent-url] input[type=checkbox]").forEach((cb) => {
    cb.addEventListener("change", async () => {
      const wrap = cb.closest("[data-consent-url]");
      const fd = new FormData();
      fd.append(cb.name, cb.checked ? "1" : "0");
      try {
        const r = await fetch(wrap.getAttribute("data-consent-url"), { method: "POST", headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" }, body: fd });
        if (!r.ok) throw new Error();
        toast("保存しました", "success");
      } catch (e) {
        cb.checked = !cb.checked;
        toast("保存できませんでした", "error");
      }
    });
  });

  // ---- PWA ----
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    });
  }
  let deferredPrompt = null;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredPrompt = e;
    const bar = document.querySelector(".installbar");
    if (bar) {
      bar.classList.add("show");
      bar.querySelector("button")?.addEventListener("click", async () => {
        bar.classList.remove("show");
        deferredPrompt.prompt();
        deferredPrompt = null;
      });
    }
  });

  // ---- confirm ----
  document.addEventListener("submit", (ev) => {
    const f = ev.target;
    if (f.matches("form[data-confirm]") && !window.confirm(f.getAttribute("data-confirm"))) ev.preventDefault();
  });
})();
