/* 音声録音（MediaRecorder）→ multipart アップロード
   iOS Safari: audio/mp4 (AAC)、Chrome/Android: audio/webm;codecs=opus。
   使い方: TOMONI.initRecorder({ button, timer, status, onBlob }) */
(function () {
  "use strict";
  window.TOMONI = window.TOMONI || {};

  function pickMime() {
    const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus", "audio/mpeg"];
    if (typeof MediaRecorder === "undefined") return null;
    if (!MediaRecorder.isTypeSupported) return "";
    for (const c of candidates) {
      try { if (MediaRecorder.isTypeSupported(c)) return c; } catch (e) { /* ignore */ }
    }
    return "";
  }

  function extFor(mime) {
    if (!mime) return "webm";
    if (mime.includes("mp4")) return "m4a";
    if (mime.includes("ogg")) return "ogg";
    if (mime.includes("mpeg")) return "mp3";
    if (mime.includes("wav")) return "wav";
    return "webm";
  }

  window.TOMONI.initRecorder = function (opts) {
    const btn = opts.button;
    const timerEl = opts.timer;
    const statusEl = opts.status;
    let recorder = null, chunks = [], stream = null, startedAt = 0, tick = null, mime = "";

    function setStatus(t) { if (statusEl) statusEl.textContent = t; }
    function fmt(sec) { const m = Math.floor(sec / 60), s = sec % 60; return m + ":" + (s < 10 ? "0" : "") + s; }

    if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices) {
      btn.disabled = true;
      setStatus("このブラウザは録音に対応していません。下のテキスト入力をご利用ください。");
      if (opts.onUnsupported) opts.onUnsupported();
      return;
    }

    async function start() {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (e) {
        setStatus("マイクを使えませんでした。ブラウザの設定でマイクを許可してください。");
        return;
      }
      mime = pickMime() || "";
      chunks = [];
      try {
        recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      } catch (e) {
        recorder = new MediaRecorder(stream);
      }
      mime = recorder.mimeType || mime;
      recorder.ondataavailable = (ev) => { if (ev.data && ev.data.size > 0) chunks.push(ev.data); };
      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunks, { type: mime || "audio/webm" });
        const duration = Math.round((Date.now() - startedAt) / 1000);
        clearInterval(tick);
        btn.classList.remove("recording");
        btn.querySelector(".label").textContent = "録音する";
        if (blob.size < 1000) { setStatus("録音が短すぎます。もう一度お試しください。"); return; }
        setStatus("録音完了（" + fmt(duration) + "）");
        opts.onBlob(blob, "memo." + extFor(mime), duration);
      };
      recorder.start(1000);
      startedAt = Date.now();
      btn.classList.add("recording");
      btn.querySelector(".label").textContent = "停止";
      setStatus("録音中… 施術内容・悩み・次回の目安・掲載OK/NGを話してください");
      tick = setInterval(() => { if (timerEl) timerEl.textContent = fmt(Math.round((Date.now() - startedAt) / 1000)); }, 500);
      // 最長 5 分
      setTimeout(() => { if (recorder && recorder.state === "recording") recorder.stop(); }, 5 * 60 * 1000);
    }

    btn.addEventListener("click", () => {
      if (recorder && recorder.state === "recording") recorder.stop();
      else start();
    });
  };

  window.TOMONI.uploadForm = async function (url, formData, onProgress) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "X-CSRFToken": window.TOMONI.csrf(), "X-Requested-With": "fetch" },
      body: formData,
    });
    let data = {};
    try { data = await r.json(); } catch (e) { /* ignore */ }
    if (!r.ok) throw new Error(data.error || "アップロードに失敗しました");
    return data;
  };
})();
