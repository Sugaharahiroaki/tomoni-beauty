/* SNS動画（リール）: アップロード、ガイド付きカメラ、台本の写真差し替え、自分の声の録音、声の試聴 */
(function () {
  "use strict";
  const csrf = () => window.TOMONI.csrf();
  const toast = (t, k) => window.TOMONI.toast(t, k);

  // ---- アップロード（選んだファイルを順番に送り、終わったら画面を更新） ----
  const modal = document.getElementById("camera-modal");
  const uploadUrl = modal ? modal.getAttribute("data-upload-url") : null;
  const statusBox = document.getElementById("upload-status");
  let pending = 0;

  async function uploadFile(file, slot, faceVisible) {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("slot", slot);
    if (faceVisible) fd.append("face_visible", "1");
    const r = await fetch(uploadUrl, { method: "POST", headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" }, body: fd });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || "送れませんでした");
    return data;
  }

  function showStatus(text) {
    if (!statusBox) return;
    statusBox.style.display = text ? "" : "none";
    statusBox.textContent = text || "";
  }

  async function sendFiles(files, slot) {
    if (!uploadUrl || !files.length) return;
    pending += files.length;
    for (const f of files) {
      showStatus(`送っています…（あと${pending}つ）`);
      try {
        await uploadFile(f, slot, false);
      } catch (e) {
        toast(`${f.name}: ${e.message}`, "error");
      }
      pending -= 1;
    }
    if (pending <= 0) {
      showStatus("送り終わりました。画面を更新します…");
      window.location.reload();
    }
  }

  document.querySelectorAll("input[data-upload-slot]").forEach((input) => {
    input.addEventListener("change", () => {
      sendFiles(Array.from(input.files || []), input.getAttribute("data-upload-slot"));
      input.value = "";
    });
  });

  // ---- ガイド付きカメラ ----
  if (modal) {
    const video = document.getElementById("camera-video");
    const guide = document.getElementById("camera-guide");
    const recBadge = document.getElementById("camera-rec");
    const errBox = document.getElementById("camera-error");
    const shutter = document.getElementById("camera-shutter");
    const countEl = document.getElementById("camera-count");
    let stream = null, recorder = null, mode = "photo", slot = "", taken = 0, recording = false, timer = null;

    function recorderType() {
      if (typeof MediaRecorder === "undefined") return "";
      return ["video/mp4;codecs=avc1", "video/mp4", "video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"].find((m) => MediaRecorder.isTypeSupported(m)) || "";
    }

    async function open(btn) {
      slot = btn.getAttribute("data-slot");
      mode = btn.getAttribute("data-mode") === "video" ? "video" : "photo";
      document.getElementById("camera-what").textContent = btn.getAttribute("data-what") || "";
      document.getElementById("camera-how").textContent = btn.getAttribute("data-how") || "";
      guide.className = "guide-overlay guide-" + (btn.getAttribute("data-frame") || "closeup");
      setMode(mode);
      taken = 0; countEl.textContent = "";
      errBox.style.display = "none";
      modal.style.display = "flex";
      document.body.style.overflow = "hidden";
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1920 } }, audio: false });
        video.srcObject = stream;
        await video.play().catch(() => {});
      } catch (e) {
        errBox.textContent = "カメラを使えませんでした。ブラウザの設定でカメラを許可するか、「アルバムから」でスマホのカメラアプリの写真を選んでください。";
        errBox.style.display = "";
      }
    }
    function close() {
      if (recorder && recorder.state === "recording") recorder.stop();
      if (stream) stream.getTracks().forEach((t) => t.stop());
      stream = null;
      modal.style.display = "none";
      document.body.style.overflow = "";
      if (taken > 0) window.location.reload();
    }
    function setMode(m) {
      mode = m;
      modal.querySelectorAll(".camera-mode button").forEach((b) => b.classList.toggle("active", b.getAttribute("data-mode") === m));
      shutter.classList.toggle("video", m === "video");
    }
    function takePhoto() {
      if (!video.videoWidth) return;
      const vw = video.videoWidth, vh = video.videoHeight;
      let cw = vw, ch = Math.round((vw * 16) / 9);
      if (ch > vh) { ch = vh; cw = Math.round((vh * 9) / 16); }
      const canvas = document.createElement("canvas");
      canvas.width = cw; canvas.height = ch;
      canvas.getContext("2d").drawImage(video, (vw - cw) / 2, (vh - ch) / 2, cw, ch, 0, 0, cw, ch);
      canvas.toBlob(async (blob) => {
        if (!blob) return;
        try {
          await uploadFile(new File([blob], `photo_${Date.now()}.jpg`, { type: "image/jpeg" }), slot, false);
          taken += 1; countEl.textContent = `${taken}つ撮れました`;
        } catch (e) { toast(e.message, "error"); }
      }, "image/jpeg", 0.92);
      modal.classList.add("flash"); setTimeout(() => modal.classList.remove("flash"), 150);
    }
    function startRecording() {
      if (!stream || typeof MediaRecorder === "undefined") { toast("このブラウザでは動画を撮れません。スマホのカメラアプリで撮って「アルバムから」で選んでください。", "error"); return; }
      const type = recorderType();
      recorder = new MediaRecorder(stream, type ? { mimeType: type, videoBitsPerSecond: 8000000 } : undefined);
      const chunks = [];
      recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      recorder.onstop = async () => {
        recording = false; recBadge.style.display = "none"; shutter.classList.remove("recording");
        const mime = recorder.mimeType || "video/webm";
        const ext = mime.includes("mp4") ? "mp4" : "webm";
        try {
          await uploadFile(new File([new Blob(chunks, { type: mime })], `clip_${Date.now()}.${ext}`, { type: mime }), slot, false);
          taken += 1; countEl.textContent = `${taken}つ撮れました`;
        } catch (e) { toast(e.message, "error"); }
      };
      recorder.start();
      recording = true; shutter.classList.add("recording");
      let left = 3;
      recBadge.style.display = ""; recBadge.querySelector("span").textContent = left;
      timer = setInterval(() => { left -= 1; recBadge.querySelector("span").textContent = left; if (left <= 0) { clearInterval(timer); if (recorder.state === "recording") recorder.stop(); } }, 1000);
    }
    document.querySelectorAll("[data-camera-open]").forEach((b) => b.addEventListener("click", () => open(b)));
    modal.querySelectorAll(".camera-close").forEach((b) => b.addEventListener("click", close));
    modal.querySelectorAll(".camera-mode button").forEach((b) => b.addEventListener("click", () => { if (!recording) setMode(b.getAttribute("data-mode")); }));
    shutter.addEventListener("click", () => { if (mode === "photo") takePhoto(); else if (recording) { clearInterval(timer); recorder.stop(); } else startRecording(); });
  }

  // ---- 台本: 写真の差し替え ----
  document.querySelectorAll(".picker-trigger").forEach((btn) => {
    btn.addEventListener("click", () => {
      const scene = btn.getAttribute("data-scene");
      const row = document.querySelector(`[data-picker-for="${scene}"]`);
      const openNow = row.style.display !== "none";
      document.querySelectorAll(".picker-row").forEach((r) => (r.style.display = "none"));
      document.querySelectorAll(".picker-trigger").forEach((t) => t.classList.remove("picking"));
      if (!openNow) { row.style.display = ""; btn.classList.add("picking"); row.dataset.targetShot = btn.getAttribute("data-shot"); }
    });
  });
  document.querySelectorAll(".picker-option").forEach((opt) => {
    opt.addEventListener("click", () => {
      const row = opt.closest(".picker-row");
      const scene = row.getAttribute("data-picker-for");
      const shot = row.dataset.targetShot || "0";
      const input = document.querySelector(`input[name="asset_${scene}_${shot}"]`);
      const trigger = document.querySelector(`.picker-trigger[data-scene="${scene}"][data-shot="${shot}"]`);
      if (input) input.value = opt.getAttribute("data-asset");
      if (trigger) { trigger.innerHTML = `<img src="${opt.getAttribute("data-src")}" alt="">`; trigger.classList.remove("picking"); }
      row.style.display = "none";
      toast("写真を入れ替えました（保存で確定）", "success");
    });
  });

  // ---- 自分の声の録音（セリフごと） ----
  document.querySelectorAll(".take-row").forEach((row) => {
    const btn = row.querySelector(".take-record");
    const audio = row.querySelector(".take-audio");
    const status = row.querySelector(".take-status");
    let rec = null, chunks = [], stream = null;
    btn.addEventListener("click", async () => {
      if (rec && rec.state === "recording") { rec.stop(); return; }
      try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch (e) { toast("マイクを使えませんでした", "error"); return; }
      const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((m) => MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(m)) || "";
      rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      chunks = [];
      rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        btn.textContent = "🎙 自分の声で録音"; btn.classList.remove("recording");
        const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
        const fd = new FormData();
        fd.append("file", blob, "take." + ((rec.mimeType || "").includes("mp4") ? "m4a" : "webm"));
        fd.append("scene_index", row.getAttribute("data-take-index"));
        status.textContent = "保存しています…";
        try {
          const r = await fetch(row.getAttribute("data-take-url"), { method: "POST", headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" }, body: fd });
          const data = await r.json();
          if (!r.ok) throw new Error(data.error || "保存できませんでした");
          audio.src = data.url; audio.style.display = ""; status.textContent = "保存しました";
        } catch (e) { status.textContent = e.message; }
      };
      rec.start();
      btn.textContent = "■ 停止"; btn.classList.add("recording"); status.textContent = "録音中…";
    });
  });

  // ---- 声の試聴 ----
  const preview = document.getElementById("voice-preview");
  if (preview) {
    preview.addEventListener("click", async () => {
      const voice = document.querySelector("[name=voice_name]")?.value;
      preview.disabled = true; preview.textContent = "声を作っています…";
      try {
        const r = await fetch(preview.getAttribute("data-url"), { method: "POST", headers: { "X-CSRFToken": csrf(), "Content-Type": "application/json", "X-Requested-With": "fetch" }, body: JSON.stringify({ voice, text: "今日はご来店ありがとうございました。色落ちが気になったら、いつでも相談してくださいね。" }) });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || "試聴できませんでした");
        const a = document.getElementById("voice-audio");
        a.src = data.url; a.style.display = ""; a.play().catch(() => {});
      } catch (e) { toast(e.message, "error"); }
      preview.disabled = false; preview.textContent = "この声で聞いてみる";
    });
  }
})();
