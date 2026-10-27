(function () {
  "use strict";

  const $ = function (id) { return document.getElementById(id); };
  const els = {
    workspace: $("workspace"),
    modeChip: $("modeChip"),
    modelLogo: $("modelLogo"),
    modeText: $("modeText"),
    costText: $("costText"),
    sampleBtn: $("sampleBtn"),
    sampleMenu: $("sampleMenu"),
    uploadBtn: $("uploadBtn"),
    settingsBtn: $("settingsBtn"),
    fileInput: $("fileInput"),
    fileName: $("fileName"),
    fileMeta: $("fileMeta"),
    fileBadge: $("fileBadge"),
    prevBtn: $("prevBtn"),
    nextBtn: $("nextBtn"),
    pageIndicator: $("pageIndicator"),
    zoomOutBtn: $("zoomOutBtn"),
    zoomInBtn: $("zoomInBtn"),
    zoomLabel: $("zoomLabel"),
    fitBtn: $("fitBtn"),
    slideStage: $("slideStage"),
    viewerEmpty: $("viewerEmpty"),
    viewerLoading: $("viewerLoading"),
    viewerLoadingText: $("viewerLoadingText"),
    thumbRail: $("thumbRail"),
    emptyUploadBtn: $("emptyUploadBtn"),
    demoPptxBtn: $("demoPptxBtn"),
    demoPdfBtn: $("demoPdfBtn"),
    agentStatus: $("agentStatus"),
    copyBtn: $("copyBtn"),
    exportBtn: $("exportBtn"),
    printBtn: $("printBtn"),
    controls: document.querySelector(".controls"),
    langSeg: $("langSeg"),
    levelRange: $("levelRange"),
    levelName: $("levelName"),
    levelTicks: $("levelTicks"),
    levelDesc: $("levelDesc"),
    localHint: $("localHint"),
    generateBtn: $("generateBtn"),
    generateLabel: document.querySelector("#generateBtn .generate-label"),
    stopBtn: $("stopBtn"),
    notesScroll: $("notesScroll"),
    notesEmpty: $("notesEmpty"),
    docWarnings: $("docWarnings"),
    notesBody: $("notesBody"),
    errorCard: $("errorCard"),
    errorText: $("errorText"),
    errorSettingsBtn: $("errorSettingsBtn"),
    fallbackBtn: $("fallbackBtn"),
    noteStats: $("noteStats"),
    notesFooter: $("notesFooter"),
    sectionProgress: $("sectionProgress"),
    splitter: $("splitter"),
    dropOverlay: $("dropOverlay"),
    toasts: $("toasts"),
    settingsModal: $("settingsModal"),
    closeSettingsBtn: $("closeSettingsBtn"),
    cancelSettingsBtn: $("cancelSettingsBtn"),
    saveSettingsBtn: $("saveSettingsBtn"),
    providerSelect: $("providerSelect"),
    baseUrlInput: $("baseUrlInput"),
    modelInput: $("modelInput"),
    apiKeyInput: $("apiKeyInput"),
    toggleKeyBtn: $("toggleKeyBtn"),
    forceLocalInput: $("forceLocalInput"),
    embeddingModeInput: $("embeddingModeInput"),
    embeddingBaseUrlInput: $("embeddingBaseUrlInput"),
    embeddingModelInput: $("embeddingModelInput"),
    embeddingApiKeyInput: $("embeddingApiKeyInput"),
    embeddingMaxTokensInput: $("embeddingMaxTokensInput"),
    embeddingDeviceInput: $("embeddingDeviceInput")
  };

  const LS = {
    settings: "ln_agent_settings_v1",
    prefs: "ln_agent_prefs_v1",
    lastDoc: "ln_agent_last_doc_v1",
    split: "ln_agent_split_v1",
    notes: "ln_agent_notes_v1"
  };

  const DEFAULT_LEVELS = [
    { level: 1, zh: "速览", desc: "只保留最核心的考点，考前 3 分钟扫一遍。" },
    { level: 2, zh: "精简", desc: "每页提炼 1–2 个要点，快速建立框架。" },
    { level: 3, zh: "标准", desc: "完整的复习笔记：定义、原理、步骤与来源页码。" },
    { level: 4, zh: "详细", desc: "补充解释、公式条件、易错点与例子。" },
    { level: 5, zh: "精讲", desc: "深度理解：背景、对比、推导、考法与自测。" }
  ];

  const state = {
    config: null,
    settings: {
      baseUrl: "", model: "", apiKey: "", forceLocal: false, provider: "",
      embeddingMode: "hybrid", embeddingModeVersion: 2,
      embeddingBaseUrl: "", embeddingModel: "",
      embeddingApiKey: "", embeddingMaxTokens: "", embeddingDevice: ""
    },
    doc: null,
    page: 0,
    zoom: 1,
    fitScale: 1,
    lang: "zh",
    level: 3,
    generating: false,
    stopped: false,
    markdown: "",
    sections: [],
    sectionSignature: "",
    sectionLevel: 2,
    sectionDom: [],
    sectionError: "",
    controller: null,
    pendingRender: 0,
    autoFollow: true,
    noteMode: "",
    startedAt: 0,
    lastCost: null,
    lastUsage: null
  };

  function readJSON(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (error) {
      return fallback;
    }
  }

  function writeJSON(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (error) { /* ignore */ }
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function truncate(value, length) {
    const text = String(value == null ? "" : value);
    return text.length > length ? text.slice(0, length - 1) + "…" : text;
  }

  function toast(message, type, duration) {
    const node = document.createElement("div");
    node.className = "toast" + (type ? " " + type : "");
    node.textContent = message;
    els.toasts.appendChild(node);
    requestAnimationFrame(function () { node.classList.add("show"); });
    setTimeout(function () {
      node.classList.remove("show");
      setTimeout(function () { node.remove(); }, 250);
    }, duration || 3800);
  }

  function setStatus(text, kind) {
    els.agentStatus.className = kind || "";
    els.agentStatus.innerHTML = '<i class="status-dot"></i>' + escapeHtml(text);
  }

  function levelInfo(level) {
    const list = (state.config && state.config.levels) || DEFAULT_LEVELS;
    return list[clamp(level, 1, 5) - 1] || DEFAULT_LEVELS[2];
  }

  function loadPrefs() {
    const prefs = readJSON(LS.prefs, {});
    state.lang = ["zh", "en", "bilingual"].indexOf(prefs.lang) !== -1 ? prefs.lang : "zh";
    state.level = clamp(parseInt(prefs.level, 10) || 3, 1, 5);

    const saved = readJSON(LS.settings, {});
    state.settings = {
      baseUrl: saved.baseUrl || "",
      model: saved.model || "",
      apiKey: saved.apiKey || "",
      forceLocal: Boolean(saved.forceLocal),
      provider: saved.provider || "",
      embeddingMode: saved.embeddingModeVersion === 2
        ? (saved.embeddingMode || "hybrid")
        : (saved.embeddingMode === "keyword" ? "hybrid" : (saved.embeddingMode || "hybrid")),
      embeddingModeVersion: 2,
      embeddingBaseUrl: saved.embeddingBaseUrl || "",
      embeddingModel: saved.embeddingModel || "",
      embeddingApiKey: saved.embeddingApiKey || "",
      embeddingMaxTokens: saved.embeddingMaxTokens || "",
      embeddingDevice: saved.embeddingDevice || ""
    };

    const split = parseFloat(localStorage.getItem(LS.split));
    if (split >= 38 && split <= 68) {
      document.documentElement.style.setProperty("--left", split.toFixed(2) + "%");
    }
  }

  function updateLangUI() {
    Array.prototype.forEach.call(els.langSeg.querySelectorAll("button"), function (button) {
      const active = button.dataset.lang === state.lang;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function updateLevelUI() {
    const info = levelInfo(state.level);
    els.levelRange.value = String(state.level);
    els.levelRange.style.setProperty("--pct", ((state.level - 1) / 4 * 100).toFixed(2) + "%");
    els.levelName.textContent = info.zh;
    els.levelDesc.textContent = info.desc || "";
    Array.prototype.forEach.call(els.levelTicks.querySelectorAll("span"), function (span) {
      span.classList.toggle("active", Number(span.dataset.level) === state.level);
    });
  }

  function savePrefs() {
    writeJSON(LS.prefs, { lang: state.lang, level: state.level });
  }

  function isLocalMode() {
    if (state.settings.forceLocal) return true;
    if (state.settings.apiKey) return false;
    return !(state.config && state.config.llm_configured);
  }

  function currentProvider() {
    const providers = (state.config && state.config.providers) || [];
    const model = state.settings.model || (state.config && state.config.defaults && state.config.defaults.model) || "";
    const base = state.settings.baseUrl || (state.config && state.config.defaults && state.config.defaults.base_url) || "";
    if (model) {
      const byModel = providers.find(function (provider) {
        return provider.id !== "custom" && provider.model &&
          (model === provider.model || model.indexOf(provider.model) === 0);
      });
      if (byModel) return byModel;
    }
    if (base) {
      const byBase = providers.find(function (provider) {
        return provider.id !== "custom" && provider.base_url && base.indexOf(provider.base_url) === 0;
      });
      if (byBase) return byBase;
    }
    return providers.find(function (provider) { return provider.id === "custom"; }) || {
      name: "自定义", logo: "✦", color: "#4f46e5", pricing: null
    };
  }

  function currentPricing(provider) {
    const model = (
      state.settings.model ||
      (state.config && state.config.defaults && state.config.defaults.model) ||
      ""
    ).toLowerCase();
    const map = (state.config && state.config.model_pricing) || {};
    const keys = Object.keys(map).sort(function (a, b) { return b.length - a.length; });
    for (let index = 0; index < keys.length; index += 1) {
      const key = keys[index];
      if (model === key || model.indexOf(key + "-") === 0 || model.indexOf(key + ":") === 0) {
        return map[key];
      }
    }
    if (provider && provider.model && model === String(provider.model).toLowerCase()) {
      return provider.pricing || null;
    }
    if (provider && provider.id === "ollama") {
      return provider.pricing || { input: 0, output: 0, currency: "USD" };
    }
    return null;
  }

  function formatCost(usd) {
    const value = Number(usd) || 0;
    if (value <= 0) return "$0";
    if (value < 0.0001) return "<$0.0001";
    if (value < 0.01) return "$" + value.toFixed(4);
    return "$" + value.toFixed(3);
  }

  function estimateRunCost() {
    if (isLocalMode()) return { usd: 0, free: true, estimated: true };
    const provider = currentProvider();
    const pricing = currentPricing(provider);
    if (!pricing) return null;
    const sourceChars = state.doc && state.doc.stats ? Number(state.doc.stats.chars) || 0 : 0;
    const outputBase = { 1: 700, 2: 1200, 3: 1900, 4: 3000, 5: 4600 }[state.level] || 1900;
    const languageMultiplier = state.lang === "bilingual" ? 1.75 : state.lang === "en" ? 1.1 : 1;
    const inputTokens = Math.max(1, Math.round((sourceChars + 1500) / 1.7));
    const outputTokens = Math.max(1, Math.round((outputBase * languageMultiplier) / 1.7));
    const usd =
      inputTokens / 1_000_000 * Number(pricing.input || 0) +
      outputTokens / 1_000_000 * Number(pricing.output || 0);
    return {
      usd: usd,
      inputTokens: inputTokens,
      outputTokens: outputTokens,
      estimated: true,
      currency: pricing.currency || "USD"
    };
  }

  function updateModeChip() {
    if (!state.config) {
      els.modeChip.className = "mode-chip";
      els.modeText.textContent = "检测中…";
      els.costText.textContent = "正在估算费用";
      return;
    }
    const local = isLocalMode();
    const provider = currentProvider();
    els.modeChip.className = "mode-chip " + (local ? "local" : "ai");

    if (local) {
      els.modelLogo.textContent = "⌂";
      els.modelLogo.style.background = "linear-gradient(135deg, #f59e0b, #d97706)";
      els.modeText.textContent = "本地摘录";
      els.costText.textContent = "免费 · 本机";
      els.modeChip.title = "本地摘录模式：不调用大模型，不产生 API 费用";
    } else {
      const model = state.settings.model || state.config.defaults.model || "LLM";
      els.modelLogo.textContent = provider.logo || model.charAt(0).toUpperCase() || "✦";
      els.modelLogo.style.background = provider.color || "#4f46e5";
      els.modeText.textContent = model;
      const cost = state.lastCost || estimateRunCost();
      if (cost) {
        els.costText.textContent =
          (state.lastCost ? "本轮 ≈ " : "预估 ≈ ") + formatCost(cost.usd);
      } else {
        els.costText.textContent = "费用未知（自定义模型）";
      }
      const pricing = currentPricing(provider);
      const priceNote = pricing
        ? "参考价 USD/1M tokens：输入 " + pricing.input + "，输出 " + pricing.output + "；"
        : "该模型未内置价格；";
      const usage = state.lastUsage;
      const usageNote = usage
        ? "本次估算 tokens：输入 " + usage.input_tokens + "，输出 " + usage.output_tokens + "；"
        : "";
      els.modeChip.title =
        provider.name + " · " + model + " · " + priceNote + usageNote +
        "实际费用以服务商账单为准。" +
        (state.settings.apiKey ? " 使用浏览器中的 Key。" : " 使用服务端 Key。");
    }

    if (els.localHint) {
      if (local) {
        els.localHint.hidden = false;
        els.localHint.textContent = state.settings.forceLocal
          ? "已强制使用本地摘录模式：不调用大模型，仅抽取原文要点。"
          : "未配置 API Key：将使用本地摘录模式，英文/双语模式不会翻译。点击右上角设置可配置模型。";
      } else {
        els.localHint.hidden = true;
      }
    }
  }

  function detectProvider(baseUrl) {
    if (!state.config || !baseUrl) return "";
    const found = state.config.providers.find(function (provider) {
      return provider.id !== "custom" && provider.base_url &&
        (baseUrl === provider.base_url || baseUrl.indexOf(provider.base_url) === 0);
    });
    return found ? found.id : "custom";
  }

  function populateProviderOptions() {
    const providers = (state.config && state.config.providers) || [];
    els.providerSelect.innerHTML = providers.map(function (provider) {
      return '<option value="' + escapeHtml(provider.id) + '">' + escapeHtml(provider.name) + "</option>";
    }).join("");
  }

  function openSettings() {
    if (!state.config) {
      toast("后端配置尚未加载，请稍后重试。", "error");
      return;
    }
    populateProviderOptions();
    const defaults = state.config.defaults || {};
    const baseUrl = state.settings.baseUrl || defaults.base_url || "";
    const model = state.settings.model || defaults.model || "";
    els.baseUrlInput.value = baseUrl;
    els.modelInput.value = model;
    els.apiKeyInput.value = state.settings.apiKey;
    els.apiKeyInput.type = "password";
    els.toggleKeyBtn.textContent = "显示";
    els.forceLocalInput.checked = state.settings.forceLocal;
    els.embeddingModeInput.value = state.settings.embeddingMode || "hybrid";
    els.embeddingBaseUrlInput.value = state.settings.embeddingBaseUrl || "";
    els.embeddingModelInput.value = state.settings.embeddingModel || "";
    els.embeddingApiKeyInput.value = state.settings.embeddingApiKey || "";
    els.embeddingMaxTokensInput.value = state.settings.embeddingMaxTokens || "";
    els.embeddingDeviceInput.value = state.settings.embeddingDevice || "";
    els.providerSelect.value = state.settings.provider || detectProvider(baseUrl) || "custom";
    els.settingsModal.hidden = false;
    setTimeout(function () { els.baseUrlInput.focus(); }, 30);
  }

  function closeSettings() {
    els.settingsModal.hidden = true;
  }

  function saveSettings() {
    state.settings.baseUrl = els.baseUrlInput.value.trim();
    state.settings.model = els.modelInput.value.trim();
    state.settings.apiKey = els.apiKeyInput.value.trim();
    state.settings.forceLocal = els.forceLocalInput.checked;
    state.settings.provider = els.providerSelect.value;
    state.settings.embeddingMode = els.embeddingModeInput.value || "hybrid";
    state.settings.embeddingModeVersion = 2;
    state.settings.embeddingBaseUrl = els.embeddingBaseUrlInput.value.trim();
    state.settings.embeddingModel = els.embeddingModelInput.value.trim();
    state.settings.embeddingApiKey = els.embeddingApiKeyInput.value.trim();
    state.settings.embeddingMaxTokens = els.embeddingMaxTokensInput.value.trim();
    state.settings.embeddingDevice = els.embeddingDeviceInput.value.trim();
    state.lastCost = null;
    state.lastUsage = null;
    writeJSON(LS.settings, state.settings);
    updateModeChip();
    closeSettings();
    toast("设置已保存（仅存于本机浏览器）。", "success");
  }

  function applyProviderPreset() {
    const id = els.providerSelect.value;
    const provider = (state.config && state.config.providers || []).find(function (item) {
      return item.id === id;
    });
    if (!provider || id === "custom") return;
    els.baseUrlInput.value = provider.base_url;
    els.modelInput.value = provider.model;
  }

  function setNoteActions(enabled) {
    els.copyBtn.disabled = !enabled;
    els.exportBtn.disabled = !enabled;
    els.printBtn.disabled = !enabled;
  }

  function showViewerLoading(text) {
    els.viewerEmpty.hidden = true;
    els.viewerLoading.hidden = false;
    els.viewerLoadingText.textContent = text || "正在解析课件…";
    els.thumbRail.hidden = true;
    const shell = $("slideShell");
    if (shell) shell.remove();
    els.prevBtn.disabled = true;
    els.nextBtn.disabled = true;
    els.zoomInBtn.disabled = true;
    els.zoomOutBtn.disabled = true;
    els.fitBtn.disabled = true;
  }

  function restoreViewer() {
    els.viewerLoading.hidden = true;
    if (!state.doc) {
      els.viewerEmpty.hidden = false;
      els.thumbRail.hidden = true;
      return;
    }
    renderThumbs();
    renderViewer();
  }

  function setNotesEmptyMode(mode) {
    const heading = els.notesEmpty.querySelector("h2");
    const paragraph = els.notesEmpty.querySelector("p");
    const steps = els.notesEmpty.querySelector(".empty-steps");
    const mark = els.notesEmpty.querySelector(".notes-empty-mark");
    if (mode === "doc") {
      mark.textContent = "✎";
      heading.textContent = "课件已就绪，生成你的第一版笔记";
      paragraph.textContent = "已从 " + state.doc.page_count + " 页课件中提取内容。选择语言与难度，点击「生成笔记」。";
      if (steps) steps.hidden = true;
    } else {
      mark.textContent = "✎";
      heading.textContent = "像学生一样记笔记，而不是复制 PPT";
      paragraph.textContent = "智能体会重写、压缩并重组课件知识点，按重要度着色，并标出出处页码。";
      if (steps) steps.hidden = false;
    }
  }

  function resetNotesForDoc() {
    if (state.pendingRender) {
      clearTimeout(state.pendingRender);
      state.pendingRender = 0;
    }
    state.markdown = "";
    state.noteMode = "";
    state.sections = [];
    state.sectionSignature = "";
    state.sectionLevel = 2;
    state.sectionDom = [];
    state.sectionError = "";
    sectionSyncKey = "";
    els.notesBody.innerHTML = "";
    els.notesBody.hidden = true;
    els.errorCard.hidden = true;
    els.notesFooter.hidden = true;
    els.noteStats.textContent = "";
    updateSectionProgress();
    setNoteActions(false);
    els.notesEmpty.hidden = false;
    setNotesEmptyMode("doc");
    state.autoFollow = true;
    els.notesScroll.scrollTop = 0;
  }

  function noteCacheKey() {
    if (!state.doc) return "";
    return [state.doc.doc_id, state.lang, String(state.level)].join("|");
  }

  function saveNoteCache(info) {
    if (!state.doc || !state.markdown.trim()) return;
    var cache = readJSON(LS.notes, {});
    var key = noteCacheKey();
    cache[key] = {
      markdown: state.markdown,
      mode: info && info.mode ? info.mode : state.noteMode,
      savedAt: new Date().toISOString()
    };
    var keys = Object.keys(cache);
    if (keys.length > 24) {
      keys.sort(function (a, b) {
        return String(cache[a].savedAt || "").localeCompare(String(cache[b].savedAt || ""));
      });
      keys.slice(0, keys.length - 24).forEach(function (oldKey) { delete cache[oldKey]; });
    }
    try {
      var raw = JSON.stringify(cache);
      if (raw.length > 4_500_000) {
        delete cache[key];
        return;
      }
      localStorage.setItem(LS.notes, raw);
    } catch (ignored) { /* storage full: keep current page usable */ }
  }

  function restoreCachedNotes() {
    if (!state.doc) return false;
    var cache = readJSON(LS.notes, {});
    var entry = cache[noteCacheKey()];
    if (!entry || !entry.markdown) return false;
    state.markdown = entry.markdown;
    state.noteMode = entry.mode || "cached";
    state.autoFollow = false;
    renderNotesNow();
    els.notesBody.classList.remove("is-streaming");
    decorateVisuals();
    updateNoteMeta();
    updateModeChip();
    setNoteActions(true);
    els.notesBody.hidden = false;
    els.notesEmpty.hidden = true;
    els.errorCard.hidden = true;
    els.notesFooter.hidden = false;
    els.notesScroll.scrollTop = 0;
    setStatus("已恢复上次生成的笔记", "done");
    return true;
  }

  function renderWarnings(warnings) {
    if (!warnings || !warnings.length) {
      els.docWarnings.hidden = true;
      els.docWarnings.innerHTML = "";
      return;
    }
    els.docWarnings.innerHTML = warnings.map(function (warning) {
      return "<p>⚠️ " + escapeHtml(warning) + "</p>";
    }).join("");
    els.docWarnings.hidden = false;
  }

  function updateFileInfo(doc) {
    els.fileName.textContent = doc.filename || "未命名课件";
    els.fileName.title = doc.filename || "";
    const chars = doc.stats && doc.stats.chars ? doc.stats.chars : 0;
    els.fileMeta.textContent = doc.page_count + " 页 · " + doc.kind.toUpperCase() +
      (chars ? " · " + chars.toLocaleString() + " 字" : "") + " · 滚轮翻页";
    els.fileBadge.textContent = doc.kind === "pdf" ? "PDF" : "PPTX";
    els.fileBadge.className = "file-badge" + (doc.kind === "pdf" ? " pdf" : "");
  }

  function applyDoc(doc) {
    if (state.generating) {
      state.stopped = true;
      if (state.controller) state.controller.abort();
    }
    state.doc = doc;
    state.zoom = 1;
    state.lastCost = null;
    state.lastUsage = null;
    const saved = readJSON(LS.lastDoc, {});
    let pageIndex = 0;
    if (saved && saved.docId === doc.doc_id && Number.isInteger(saved.pageIndex)) {
      pageIndex = clamp(saved.pageIndex, 0, doc.slides.length - 1);
    }
    state.page = pageIndex;
    writeJSON(LS.lastDoc, { docId: doc.doc_id, pageIndex: pageIndex });

    updateFileInfo(doc);
    els.viewerEmpty.hidden = true;
    els.viewerLoading.hidden = true;
    els.thumbRail.hidden = false;
    els.controls.classList.remove("disabled");
    els.generateBtn.disabled = false;
    els.generateLabel.textContent = "生成笔记";
    resetNotesForDoc();
    renderWarnings(doc.warnings);
    updateLangUI();
    updateLevelUI();
    updateModeChip();
    renderThumbs();
    renderViewer();
    if (!restoreCachedNotes()) {
      setStatus("课件已就绪 · " + doc.page_count + " 页", "");
    }
    els.notesScroll.scrollTop = 0;
    document.dispatchEvent(new CustomEvent("notes:doc-changed", { detail: { doc: doc } }));
  }

  async function parseErrorResponse(response) {
    try {
      const data = await response.json();
      if (typeof data.detail === "string") return data.detail;
      if (Array.isArray(data.detail)) {
        return data.detail.map(function (item) { return item.msg || String(item); }).join("；");
      }
    } catch (error) { /* ignore */ }
    return "请求失败（HTTP " + response.status + "）";
  }

  async function uploadFile(file) {
    if (!file) return;
    const name = file.name || "";
    const ext = name.toLowerCase().slice(name.lastIndexOf("."));
    if ([".pptx", ".pdf", ".ppt"].indexOf(ext) === -1) {
      toast("仅支持 .pptx 和 .pdf 文件。", "error");
      return;
    }
    const limitMb = (state.config && state.config.max_upload_mb) || 50;
    if (file.size > limitMb * 1024 * 1024) {
      toast("文件超过 " + limitMb + " MB 限制。", "error");
      return;
    }
    if (state.generating) stopGeneration();
    showViewerLoading("正在解析 " + truncate(name, 30) + " …");
    setStatus("正在解析课件…", "busy");
    els.generateBtn.disabled = true;

    const form = new FormData();
    form.append("file", file);
    try {
      const response = await fetch("/api/upload", { method: "POST", body: form });
      if (!response.ok) throw new Error(await parseErrorResponse(response));
      const doc = await response.json();
      applyDoc(doc);
      toast("已解析 " + doc.page_count + " 页课件。", "success");
      if (doc.warnings && doc.warnings.length) {
        toast(doc.warnings[0], "", 5200);
      }
    } catch (error) {
      restoreViewer();
      setStatus("课件解析失败", "error");
      if (state.doc) els.generateBtn.disabled = false;
      toast(error.message || "课件解析失败。", "error", 5200);
    }
  }

  async function loadDemo(kind) {
    if (state.generating) stopGeneration();
    showViewerLoading(kind === "pdf" ? "正在加载 PDF 示例…" : "正在加载示例课件…");
    setStatus("正在加载示例课件…", "busy");
    els.generateBtn.disabled = true;
    try {
      const response = await fetch("/api/demo?kind=" + encodeURIComponent(kind), { method: "POST" });
      if (!response.ok) throw new Error(await parseErrorResponse(response));
      const doc = await response.json();
      applyDoc(doc);
      toast("示例课件已加载。", "success");
    } catch (error) {
      restoreViewer();
      setStatus("示例加载失败", "error");
      if (state.doc) els.generateBtn.disabled = false;
      toast(error.message || "示例课件加载失败。", "error", 5200);
    }
  }

  function safeFont(name) {
    const cleaned = String(name || "").replace(/[^a-zA-Z0-9 \-_]/g, "").trim();
    return cleaned ? "font-family:'" + cleaned + "',var(--font-sans);" : "";
  }

  function buildSlideElement(element) {
    const base = [
      "left:" + (Number(element.x) || 0) + "px",
      "top:" + (Number(element.y) || 0) + "px",
      "width:" + (Number(element.w) || 0) + "px",
      "height:" + (Number(element.h) || 0) + "px"
    ];
    if (element.rotation) base.push("transform:rotate(" + Number(element.rotation) + "deg)");

    if (element.type === "text") {
      if (element.fill) base.push("background:" + element.fill);
      if (element.line) base.push("border:1px solid " + element.line);
      if (element.radius) base.push("border-radius:" + element.radius);
      base.push("padding:6px 10px");
      base.push("justify-content:" + (element.valign || "flex-start"));
      base.push("color:" + (element.default_color || "#1f2937"));
      let counter = 0;
      const paragraphs = (element.paragraphs || []).map(function (paragraph) {
        let bullet = "";
        if (paragraph.bullet) {
          if (paragraph.bullet === "#") {
            counter += 1;
            bullet = '<span class="sl-bullet">' + counter + ".</span>";
          } else {
            bullet = '<span class="sl-bullet">' + escapeHtml(paragraph.bullet) + "</span>";
          }
        }
        const runs = (paragraph.runs || []).map(function (run) {
          const style = [
            "font-size:" + (Number(run.size) || 18) + "px",
            "color:" + (run.color || element.default_color || "#1f2937"),
            "font-weight:" + (run.bold ? "700" : "400"),
            "font-style:" + (run.italic ? "italic" : "normal"),
            "text-decoration:" + (run.underline ? "underline" : "none")
          ];
          const font = safeFont(run.font);
          if (font) style.push(font.replace(/;$/, ""));
          return '<span class="sl-run" style="' + style.join(";") + '">' +
            escapeHtml(run.text) + "</span>";
        }).join("");
        const align = paragraph.align || "left";
        const justify = align === "center" ? "center" : align === "right" ? "flex-end" : "flex-start";
        return '<p class="sl-para" style="text-align:' + align +
          ";justify-content:" + justify +
          ";margin:0 0 " + (Number(paragraph.space_after) || 0) + "px 0" +
          ";padding-left:" + ((Number(paragraph.level) || 0) * 1.25) + 'em">' +
          bullet + "<span>" + runs + "</span></p>";
      }).join("");
      return '<div class="sl-element sl-text" style="' + base.join(";") + '">' + paragraphs + "</div>";
    }

    if (element.type === "image") {
      return '<div class="sl-element" style="' + base.join(";") + '">' +
        '<img class="sl-image" src="' + escapeHtml(element.url) + '" alt="" draggable="false"></div>';
    }

    if (element.type === "table") {
      const cols = (element.col_widths || []).map(function (width) {
        return '<col style="width:' + (Number(width) || 60) + 'px">';
      }).join("");
      const rows = (element.rows || []).map(function (row, rowIndex) {
        const cells = row.map(function (cell) {
          const header = element.header && rowIndex === 0;
          return '<td class="' + (header ? "header" : "") + '">' + escapeHtml(cell) + "</td>";
        }).join("");
        return "<tr>" + cells + "</tr>";
      }).join("");
      return '<table class="sl-table" style="position:absolute;' + base.join(";") +
        '">' + (cols ? "<colgroup>" + cols + "</colgroup>" : "") + "<tbody>" + rows + "</tbody></table>";
    }

    if (element.type === "placeholder") {
      return '<div class="sl-element sl-placeholder" style="' + base.join(";") + '">' +
        escapeHtml(element.label || "图形") + "</div>";
    }

    if (element.fill) base.push("background:" + element.fill);
    if (element.line) base.push("border:1px solid " + element.line);
    if (element.radius) base.push("border-radius:" + element.radius);
    return '<div class="sl-element" style="' + base.join(";") + '"></div>';
  }

  function slidePreviewHTML(preview, title) {
    const width = Number(preview.width) || 1280;
    const height = Number(preview.height) || 720;
    let inner = "";
    if (preview.type === "image") {
      inner = '<img class="pdf-page" src="' + escapeHtml(preview.url) + '" alt="' +
        escapeHtml(title || "PDF 页面") + '" draggable="false">';
    } else {
      inner = (preview.elements || []).map(buildSlideElement).join("");
    }
    return {
      width: width,
      height: height,
      html: '<div class="slide-canvas" style="width:' + width + "px;height:" + height +
        "px;background:" + escapeHtml(preview.background || "#ffffff") + '">' + inner + "</div>"
    };
  }

  function renderThumbs() {
    if (!state.doc) {
      els.thumbRail.hidden = true;
      els.thumbRail.innerHTML = "";
      return;
    }
    const frameWidth = 142;
    const frameHeight = 76;
    els.thumbRail.innerHTML = state.doc.slides.map(function (slide, index) {
      const preview = slide.preview || {};
      const width = Number(preview.width) || 1280;
      const height = Number(preview.height) || 720;
      const scale = Math.min(frameWidth / width, frameHeight / height);
      const left = (frameWidth - width * scale) / 2;
      const top = (frameHeight - height * scale) / 2;
      const built = slidePreviewHTML(preview, slide.title);
      const content = built.html.replace('class="slide-canvas"', 'class="thumb-canvas"');
      return (
        '<button type="button" class="thumb' + (index === state.page ? " active" : "") +
        '" data-index="' + index + '" title="第 ' + slide.index + " 页 · " +
        escapeHtml(slide.title || "") + '">' +
        '<span class="thumb-frame"><span class="thumb-inner" style="width:' + width +
        "px;height:" + height + "px;left:" + left + "px;top:" + top +
        "px;transform:scale(" + scale + ');background:' + escapeHtml(preview.background || "#fff") +
        '">' + content + "</span></span>" +
        '<span class="thumb-no">' + String(slide.index).padStart(2, "0") + " · " +
        escapeHtml(truncate(slide.title || "未命名", 16)) + "</span></button>"
      );
    }).join("");
  }

  function slideForPage(page) {
    if (!state.doc) return null;
    const number = Number(page);
    return state.doc.slides.find(function (slide) { return slide.index === number; }) || null;
  }

  function visualForPage(page) {
    const slide = slideForPage(page);
    if (!slide) return null;
    const candidates = (slide.visuals || []).filter(function (visual) {
      return (
        visual.kind === "image" &&
        Number(visual.confidence || 0) >= 0.65
      );
    });
    if (!candidates.length) return null;
    candidates.sort(function (a, b) {
      const confidenceDiff = Number(b.confidence || 0) - Number(a.confidence || 0);
      return confidenceDiff || (Number(b.area || 0) - Number(a.area || 0));
    });
    return Object.assign({ slide: slide }, candidates[0]);
  }

  function cropForVisual(candidate) {
    const slide = candidate.slide;
    const preview = slide.preview || {};
    const width = Number(preview.width) || 1280;
    const height = Number(preview.height) || 720;
    const padX = Math.min(width * 0.02, Math.max(8, (Number(candidate.w) || width) * 0.10));
    const padY = Math.min(height * 0.02, Math.max(8, (Number(candidate.h) || height) * 0.12));
    let x = Math.max(0, (Number(candidate.x) || 0) - padX);
    let y = Math.max(0, (Number(candidate.y) || 0) - padY);
    let w = Math.min(width - x, (Number(candidate.w) || width) + padX * 2);
    let h = Math.min(height - y, (Number(candidate.h) || height * 0.8) + padY * 2);
    if (w < 40 || h < 30) {
      x = 0;
      y = 0;
      w = width;
      h = height * 0.82;
    }
    return { x: x, y: y, w: w, h: h };
  }

  function figureCaption(page, slide, candidate, custom) {
    if (custom) return custom;
    const title = (slide && slide.title) || "第 " + page + " 页";
    if (candidate.kind === "table") return title + " · 表格";
    if (candidate.kind === "image") return title + " · 图示";
    return title + " · 页面摘录";
  }

  function createVisualFigure(page, customCaption) {
    const candidate = visualForPage(page);
    if (!candidate) return null;
    const slide = candidate.slide;
    const preview = slide.preview || {};
    const title = figureCaption(page, slide, candidate, customCaption);

    const figure = document.createElement("figure");
    figure.className = "note-figure";
    figure.dataset.page = String(page);

    const frame = document.createElement("div");
    frame.className = "figure-frame";
    const isPdf = preview.type === "image";
    if (isPdf) {
      const image = document.createElement("img");
      image.src = candidate.url || preview.url;
      image.alt = title;
      image.loading = "lazy";
      image.draggable = false;
      image.addEventListener("error", function () { image.style.visibility = "hidden"; });
      if (candidate.w && candidate.h) {
        frame.style.aspectRatio = String(candidate.w) + " / " + String(candidate.h);
      }
      frame.appendChild(image);
    } else {
      const crop = cropForVisual(candidate);
      frame.classList.add("ppt-crop");
      frame.style.aspectRatio = String(crop.w) + " / " + String(crop.h);
      frame.dataset.crop = JSON.stringify(crop);
      const built = slidePreviewHTML(preview, slide.title);
      const holder = document.createElement("div");
      holder.innerHTML = built.html;
      const canvas = holder.firstElementChild;
      if (!canvas) return null;
      canvas.classList.remove("slide-canvas");
      canvas.classList.add("fig-canvas");
      frame.appendChild(canvas);
    }

    const caption = document.createElement("figcaption");
    caption.className = "figure-caption";
    caption.innerHTML =
      '<span class="fig-kicker">课件截取</span>' +
      '<span class="fig-title">' + escapeHtml(title) + "</span>" +
      '<button type="button" class="figure-open" data-page="' + Number(page) + '">查看原页 ↗</button>';
    figure.appendChild(frame);
    figure.appendChild(caption);
    return figure;
  }

  function pageForSection(heading) {
    const direct = heading.querySelector(".src-ref");
    if (direct) return Number(direct.dataset.page);
    const text = heading.textContent || "";
    const match = /\[p\.?\s*(\d+)/i.exec(text);
    return match ? Number(match[1]) : null;
  }

  function decorateVisuals() {
    const body = els.notesBody;
    if (!body || body.hidden) return;
    const used = new Set();

    Array.prototype.forEach.call(body.querySelectorAll("figure.visual-slot"), function (slot) {
      const page = Number(slot.dataset.page);
      if (!page) {
        slot.remove();
        return;
      }
      used.add(page);
      const figure = createVisualFigure(page, slot.dataset.caption || "");
      if (figure) slot.replaceWith(figure);
      else slot.remove();
    });

    let autoCount = 0;
    Array.prototype.forEach.call(body.querySelectorAll("h2"), function (heading) {
      if (autoCount >= 4) return;
      const page = pageForSection(heading);
      if (!page || used.has(page)) return;
      const slide = slideForPage(page);
      if (!slide) return;
      const hasContentVisual = (slide.visuals || []).some(function (visual) {
        return (
          visual.kind === "image" &&
          Number(visual.confidence || 0) >= 0.82
        );
      });
      if (!hasContentVisual) return;
      const figure = createVisualFigure(page, "");
      if (!figure) return;
      let anchor = heading;
      while (anchor.nextElementSibling && anchor.nextElementSibling.tagName !== "H2") {
        anchor = anchor.nextElementSibling;
      }
      anchor.after(figure);
      used.add(page);
      autoCount += 1;
    });

    layoutPptFigures();
  }

  function layoutPptFigures() {
    Array.prototype.forEach.call(document.querySelectorAll(".ppt-crop"), function (frame) {
      let crop = null;
      try { crop = JSON.parse(frame.dataset.crop || "null"); } catch (error) { crop = null; }
      const canvas = frame.querySelector(".fig-canvas");
      if (!crop || !canvas || !crop.w || !crop.h) return;
      const width = frame.clientWidth;
      if (!width) return;
      const scale = width / crop.w;
      canvas.style.transform = "scale(" + scale + ")";
      canvas.style.left = (-crop.x * scale).toFixed(2) + "px";
      canvas.style.top = (-crop.y * scale).toFixed(2) + "px";
    });
  }

  function updateActiveThumb() {
    Array.prototype.forEach.call(els.thumbRail.querySelectorAll(".thumb"), function (thumb) {
      const active = Number(thumb.dataset.index) === state.page;
      thumb.classList.toggle("active", active);
      if (active && thumb.scrollIntoView) {
        thumb.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
      }
    });
  }

  function updateNav() {
    const doc = state.doc;
    const slide = doc && doc.slides[state.page];
    els.pageIndicator.textContent = slide ? slide.index + " / " + doc.page_count : "0 / 0";
    els.prevBtn.disabled = !doc || state.page <= 0;
    els.nextBtn.disabled = !doc || state.page >= doc.slides.length - 1;
    els.zoomInBtn.disabled = !doc;
    els.zoomOutBtn.disabled = !doc;
    els.fitBtn.disabled = !doc;
  }

  function renderViewer() {
    if (!state.doc) {
      updateNav();
      return;
    }
    const slide = state.doc.slides[state.page];
    if (!slide) return;
    const preview = slide.preview || {};
    const built = slidePreviewHTML(preview, slide.title);

    let shell = $("slideShell");
    if (!shell) {
      shell = document.createElement("div");
      shell.id = "slideShell";
      els.slideStage.appendChild(shell);
    }
    shell.className = "slide-shell slide-fade";
    shell.innerHTML = built.html;
    shell.dataset.width = String(built.width);
    shell.dataset.height = String(built.height);
    shell.style.background = preview.background || "#ffffff";
    Array.prototype.forEach.call(shell.querySelectorAll("img"), function (image) {
      image.addEventListener("error", function () {
        image.style.visibility = "hidden";
      });
    });
    updateNav();
    updateActiveThumb();
    layoutSlide();
  }

  function layoutSlide() {
    const shell = $("slideShell");
    if (!shell) return;
    const stage = els.slideStage;
    const style = window.getComputedStyle(stage);
    const padX = (parseFloat(style.paddingLeft) || 0) + (parseFloat(style.paddingRight) || 0);
    const padY = (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0);
    const availW = Math.max(80, stage.clientWidth - padX - 6);
    const availH = Math.max(80, stage.clientHeight - padY - 6);
    const width = Number(shell.dataset.width) || 1280;
    const height = Number(shell.dataset.height) || 720;
    const fit = Math.min(availW / width, availH / height);
    state.fitScale = clamp(fit, 0.02, 2.5);
    const scale = state.fitScale * state.zoom;
    shell.style.width = (width * scale).toFixed(2) + "px";
    shell.style.height = (height * scale).toFixed(2) + "px";
    const canvas = shell.firstElementChild;
    if (canvas) canvas.style.transform = "scale(" + scale + ")";
    const overflowing = width * scale > availW + 1 || height * scale > availH + 1;
    stage.classList.toggle("overflowing", overflowing);
    els.zoomLabel.textContent = Math.round(state.zoom * 100) + "%";
  }

  function persistPage() {
    if (!state.doc) return;
    writeJSON(LS.lastDoc, { docId: state.doc.doc_id, pageIndex: state.page });
  }

  function setPageIndex(index, options) {
    if (!state.doc) return;
    options = options || {};
    state.page = clamp(index, 0, state.doc.slides.length - 1);
    persistPage();
    renderViewer();
    if (options.resetScroll) {
      els.slideStage.scrollTop = 0;
      els.slideStage.scrollLeft = 0;
    }
    if (options.flash) {
      const shell = $("slideShell");
      if (shell) {
        shell.classList.remove("flash-target");
        void shell.offsetWidth;
        shell.classList.add("flash-target");
        setTimeout(function () { shell.classList.remove("flash-target"); }, 1000);
      }
    }
  }

  function goToPage(pageNumber, options) {
    if (!state.doc) return;
    const target = Number(pageNumber);
    let index = state.doc.slides.findIndex(function (slide) { return slide.index === target; });
    if (index < 0) index = clamp(target - 1, 0, state.doc.slides.length - 1);
    setPageIndex(index, Object.assign({ resetScroll: true }, options || {}));
  }

  function changePage(delta) {
    if (!state.doc) return;
    setPageIndex(state.page + delta, { resetScroll: true });
  }

  function setZoom(zoom) {
    state.zoom = clamp(zoom, 0.35, 4);
    layoutSlide();
  }

  function setGeneratingUI(on) {
    state.generating = on;
    els.generateBtn.hidden = on;
    els.stopBtn.hidden = !on;
    els.notesBody.classList.toggle("is-streaming", on);
    Array.prototype.forEach.call(els.langSeg.querySelectorAll("button"), function (button) {
      button.disabled = on;
    });
    els.levelRange.disabled = on;
    els.levelTicks.style.pointerEvents = on ? "none" : "";
    if (!on) {
      els.generateBtn.disabled = !state.doc;
      els.generateLabel.textContent = state.markdown ? "重新生成" : "生成笔记";
    }
    if (on) setNoteActions(false);
  }

  // ------------------------------------------------------------------------- //
  // Note sections: the notes outline doubles as the study checklist.
  // ------------------------------------------------------------------------- //
  let sectionSyncKey = "";
  let sectionSyncTimer = 0;
  let sectionErrorNotified = false;

  function noteSignature() {
    return state.lang + "|" + state.level;
  }

  function normalizeTitle(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function collectSections() {
    if (!state.markdown.trim() || !window.NotesMarkdown || !NotesMarkdown.sections) return [];
    return NotesMarkdown.sections(state.markdown).map(function (item) {
      return {
        title: normalizeTitle(item.title).slice(0, 80),
        pages: (item.pages || []).slice(0, 60),
        level: item.level,
        domIndex: item.domIndex
      };
    }).filter(function (item) {
      return item.title && item.pages.length;
    }).slice(0, 60);
  }

  function updateSectionProgress() {
    if (!els.sectionProgress) return;
    if (state.sectionError) {
      els.sectionProgress.hidden = false;
      els.sectionProgress.textContent = state.sectionError;
      els.sectionProgress.classList.remove("all-done");
      return;
    }
    const sections = state.sections || [];
    if (!sections.length) {
      els.sectionProgress.hidden = true;
      els.sectionProgress.textContent = "";
      return;
    }
    const done = sections.filter(function (item) { return item.completed; }).length;
    els.sectionProgress.hidden = false;
    els.sectionProgress.textContent = "章节 " + done + "/" + sections.length + " 已完成";
    els.sectionProgress.classList.toggle("all-done", done === sections.length);
  }

  function decorateSections() {
    if (!els.notesBody || state.generating) return;
    const sections = state.sections || [];
    const dom = state.sectionDom || [];
    const selector = state.sectionLevel >= 3 ? "h3" : "h2";
    const headings = els.notesBody.querySelectorAll(selector);
    Array.prototype.forEach.call(headings, function (heading, index) {
      const position = dom.indexOf(index);
      const item = position >= 0 ? sections[position] : null;
      const existing = heading.querySelector(".section-check");
      if (!item) {
        if (existing) existing.remove();
        const stale = heading.querySelector(".section-quiz-btn");
        if (stale) stale.remove();
        heading.classList.remove("is-complete");
        return;
      }
      let label = existing;
      if (!label) {
        label = document.createElement("label");
        label.className = "section-check";
        label.title = "勾选表示该章节已学完；勾选后才能出题";
        const box = document.createElement("input");
        box.type = "checkbox";
        label.appendChild(box);
        const mark = document.createElement("span");
        mark.className = "section-check-mark";
        label.appendChild(mark);
        heading.insertBefore(label, heading.firstChild);
      }
      const input = label.querySelector("input");
      input.dataset.sectionId = item.section_id || "";
      input.checked = Boolean(item.completed);
      input.disabled = !item.section_id;
      heading.classList.toggle("is-complete", Boolean(item.completed));

      let quizBtn = heading.querySelector(".section-quiz-btn");
      if (!quizBtn) {
        quizBtn = document.createElement("button");
        quizBtn.type = "button";
        quizBtn.className = "section-quiz-btn";
        quizBtn.textContent = "生成测试";
        quizBtn.title = "跳到章节测试，并为该章节出题";
        heading.appendChild(quizBtn);
        quizBtn.addEventListener("click", function (event) {
          event.preventDefault();
          event.stopPropagation();
          const box = label.querySelector("input");
          requestSectionQuiz(box ? box.dataset.sectionId : "");
        });
      }
      quizBtn.disabled = !item.section_id;
    });
  }

  function requestSectionQuiz(sectionId) {
    if (!state.doc || !sectionId) {
      toast("章节还没注册好，请稍后再试。", "error");
      return;
    }
    document.dispatchEvent(new CustomEvent("notes:quiz-request", {
      detail: {
        doc_id: state.doc.doc_id,
        signature: noteSignature(),
        section_id: sectionId
      }
    }));
  }


  function scheduleSectionSync() {
    if (!state.doc || !state.markdown.trim() || state.generating) return;
    if (sectionSyncTimer) clearTimeout(sectionSyncTimer);
    sectionSyncTimer = setTimeout(function () {
      sectionSyncTimer = 0;
      syncSections();
    }, 240);
  }

  function dispatchSectionsChanged(signature, summary) {
    document.dispatchEvent(new CustomEvent("notes:sections-changed", {
      detail: {
        doc_id: state.doc ? state.doc.doc_id : "",
        signature: signature,
        sections: state.sections || [],
        summary: summary || null
      }
    }));
  }

  async function syncSections() {
    if (!state.doc || !state.markdown.trim() || state.generating) return;
    const signature = noteSignature();
    const raw = collectSections();
    state.sectionLevel = raw.length && raw[0].level >= 3 ? 3 : 2;
    const key = [state.doc.doc_id, signature, raw.length, state.markdown.length].join("|");
    if (key === sectionSyncKey && state.sectionSignature === signature) {
      decorateSections();
      updateSectionProgress();
      return;
    }
    sectionSyncKey = key;
    try {
      const response = await fetch("/api/sections", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          doc_id: state.doc.doc_id,
          signature: signature,
          sections: raw
        })
      });
      if (!response.ok) throw new Error("HTTP " + response.status);
      const data = await response.json();
      if (!state.doc || noteSignature() !== signature) return;
      state.sections = data.sections || [];
      state.sectionSignature = signature;
      state.sectionError = "";
      sectionErrorNotified = false;
      // Match each registered section back to its heading, even if the server
      // dropped an item during validation.
      state.sectionDom = state.sections.map(function (item, index) {
        var pageKey = (item.pages || []).join(",");
        for (var i = 0; i < raw.length; i += 1) {
          if (normalizeTitle(raw[i].title) === normalizeTitle(item.title) &&
              (raw[i].pages || []).join(",") === pageKey) {
            return raw[i].domIndex;
          }
        }
        // Server order matches the posted order, so fall back to position.
        return raw[index] ? raw[index].domIndex : -1;
      });
      decorateSections();
      updateSectionProgress();
      dispatchSectionsChanged(signature, data.summary);
    } catch (error) {
      sectionSyncKey = "";
      state.sectionSignature = "";
      state.sectionError = "章节注册失败：" + (error && error.message ? error.message : "网络错误");
      if (!sectionErrorNotified) {
        sectionErrorNotified = true;
        toast(state.sectionError + "（请重启后端服务后刷新页面）", "error", 7000);
      }
      // Keep the checklist visible (disabled) so the notes UI never disappears.
      state.sections = raw.map(function (item) {
        return {
          section_id: "",
          title: item.title,
          pages: item.pages,
          level: item.level,
          completed: false
        };
      });
      state.sectionDom = raw.map(function (item) { return item.domIndex; });
      decorateSections();
      updateSectionProgress();
    }
  }

  async function toggleSection(sectionId, completed) {
    if (!state.doc || !sectionId) return;
    const signature = noteSignature();
    try {
      const response = await fetch(
        "/api/sections/" + encodeURIComponent(state.doc.doc_id) + "/toggle",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            signature: signature,
            section_id: sectionId,
            completed: Boolean(completed)
          })
        }
      );
      if (!response.ok) throw new Error("toggle request failed");
      const data = await response.json();
      state.sections = data.sections || [];
      state.sectionSignature = signature;
      decorateSections();
      updateSectionProgress();
      dispatchSectionsChanged(signature, data.summary);
    } catch (error) {
      sectionSyncKey = "";
      decorateSections();
      toast("章节进度保存失败，请重试。", "error");
    }
  }



  function updateNoteMeta() {
    const counts = NotesMarkdown.stats(state.markdown);
    const total = counts.core + counts.key + counts.info;
    const chars = state.markdown.replace(/\s+/g, "").length;
    els.noteStats.textContent =
      total + " 个知识点 · 核心 " + counts.core + " / 重点 " + counts.key +
      " / 了解 " + counts.info + " · " + chars + " 字";
    els.notesFooter.hidden = !state.markdown;
    setNoteActions(Boolean(state.markdown) && !state.generating);
  }

  function renderNotesNow() {
    if (!state.markdown) return;
    const scroller = els.notesScroll;
    const nearBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 160;
    els.notesBody.innerHTML = NotesMarkdown.render(state.markdown);
    els.notesBody.hidden = false;
    els.notesEmpty.hidden = true;
    updateNoteMeta();
    if (!state.generating) {
      decorateSections();
      scheduleSectionSync();
    }
    if (state.autoFollow || nearBottom) {
      scroller.scrollTop = scroller.scrollHeight;
    }
  }

  function scheduleNotesRender() {
    if (state.pendingRender) return;
    state.pendingRender = setTimeout(function () {
      state.pendingRender = 0;
      renderNotesNow();
    }, 70);
  }

  function skeletonHTML() {
    return (
      '<div class="notes-skeleton">' +
      '<div class="sk-line sk-title"></div>' +
      '<div class="sk-line" style="width:88%"></div>' +
      '<div class="sk-line" style="width:64%"></div>' +
      '<div class="sk-line sk-head"></div>' +
      '<div class="sk-row"></div><div class="sk-row"></div><div class="sk-row"></div>' +
      '<div class="sk-line sk-head" style="width:52%"></div>' +
      '<div class="sk-row"></div><div class="sk-row"></div>' +
      "</div>"
    );
  }

  function showError(message, canFallback) {
    els.errorText.textContent = message || "生成过程中出现未知错误。";
    els.fallbackBtn.hidden = canFallback === false;
    els.errorCard.hidden = false;
  }

  function failGeneration(info) {
    if (state.stopped) return;
    if (state.pendingRender) {
      clearTimeout(state.pendingRender);
      state.pendingRender = 0;
    }
    setGeneratingUI(false);
    state.controller = null;
    if (state.markdown) {
      renderNotesNow();
      els.notesBody.classList.remove("is-streaming");
      decorateVisuals();
      updateNoteMeta();
    }
    showError(info.message, info.can_fallback);
    els.notesEmpty.hidden = true;
    els.notesBody.hidden = !state.markdown;
    setNoteActions(Boolean(state.markdown));
    setStatus("生成中断", "error");
  }

  function finishGeneration(data) {
    if (state.stopped) return;
    if (state.pendingRender) {
      clearTimeout(state.pendingRender);
      state.pendingRender = 0;
    }
    state.markdown = ensureEnglishParallel(state.markdown);
    state.controller = null;
    if (!state.markdown.trim()) {
      failGeneration({ message: "模型没有返回内容，请重试或更换模型。", can_fallback: true });
      return;
    }
    const returnToTop = state.autoFollow;
    setGeneratingUI(false);
    renderNotesNow();
    els.notesBody.classList.remove("is-streaming");
    decorateVisuals();
    updateNoteMeta();
    if (returnToTop) {
      setTimeout(function () {
        els.notesScroll.scrollTop = 0;
      }, 200);
    }
    const counts = NotesMarkdown.stats(state.markdown);
    const total = counts.core + counts.key + counts.info;
    const elapsed = data && data.elapsed ? Number(data.elapsed) : 0;
    setStatus(
      "完成 · " + total + " 个知识点" + (elapsed ? " · " + elapsed.toFixed(1) + "s" : ""),
      "done"
    );
    updateModeChip();
    saveNoteCache(data || {});
    toast("笔记已生成" + (total ? "：" + total + " 个知识点" : "") + "。", "success");
  }

  function stopGeneration() {
    if (!state.generating) return;
    state.stopped = true;
    state.generating = false;
    if (state.controller) {
      try { state.controller.abort(); } catch (error) { /* ignore */ }
    }
    if (state.pendingRender) {
      clearTimeout(state.pendingRender);
      state.pendingRender = 0;
      renderNotesNow();
    }
    setGeneratingUI(false);
    state.controller = null;
    els.notesBody.classList.remove("is-streaming");
    if (state.markdown) {
      updateNoteMeta();
      decorateVisuals();
      saveNoteCache({ mode: state.noteMode });
      setStatus("已停止 · 保留已生成内容", "");
      toast("已停止生成，保留当前内容。", "", 3000);
    } else {
      els.notesBody.hidden = true;
      els.notesEmpty.hidden = false;
      setNotesEmptyMode("doc");
      setStatus("已停止生成", "");
    }
  }

  function processSSEBlock(block) {
    block.split("\n").forEach(function (line) {
      if (line.indexOf("data:") !== 0) return;
      const raw = line.slice(5).trim();
      if (!raw || raw === "[DONE]") return;
      try {
        handleStreamEvent(JSON.parse(raw));
      } catch (error) {
        console.warn("无法解析流事件", raw, error);
      }
    });
  }

  function handleStreamEvent(event) {
    if (!event || !event.type) return;
    if (!state.generating && event.type !== "error") return;
    if (event.type === "meta") {
      state.noteMode = event.mode;
      if (event.mode === "local") {
        setStatus("本地摘录模式 · 正在提炼…", "busy");
        if (state.lang !== "zh") {
          toast("本地摘录模式不支持翻译，结果保持课件原语言。", "", 5200);
        }
      } else {
        const model = truncate(event.model || "模型", 24);
        setStatus(model + " · " + (event.level_name || "标准") + "笔记生成中…", "busy");
      }
      return;
    }
    if (event.type === "status") {
      setStatus((event.stage || "正在生成") + "…", "busy");
      return;
    }
    if (event.type === "notice") {
      toast(event.message, "", 4600);
      return;
    }
    if (event.type === "delta") {
      if (!state.markdown) els.notesBody.innerHTML = "";
      state.markdown += event.text || "";
      scheduleNotesRender();
      return;
    }
    if (event.type === "done") {
      if (event.cost) state.lastCost = event.cost;
      if (event.usage) state.lastUsage = event.usage;
      finishGeneration(event);
      return;
    }
    if (event.type === "error") {
      failGeneration(event);
    }
  }

  async function generateNotes(forceLocal) {
    if (!state.doc) {
      toast("请先上传或加载一份课件。", "error");
      return;
    }
    if (state.generating) stopGeneration();

    state.markdown = "";
    state.stopped = false;
    state.noteMode = "";
    state.autoFollow = true;
    state.startedAt = performance.now();
    state.lastCost = null;
    state.lastUsage = null;
    updateModeChip();
    els.errorCard.hidden = true;
    els.notesFooter.hidden = true;
    els.noteStats.textContent = "";
    els.notesEmpty.hidden = true;
    els.notesBody.hidden = false;
    els.notesBody.className = "notes markdown is-streaming";
    els.notesBody.innerHTML = skeletonHTML();
    els.notesScroll.scrollTop = 0;
    setGeneratingUI(true);
    setStatus("正在阅读 " + state.doc.page_count + " 页课件…", "busy");

    const api = {};
    if (state.settings.apiKey) api.api_key = state.settings.apiKey;
    if (state.settings.baseUrl) api.base_url = state.settings.baseUrl;
    if (state.settings.model) api.model = state.settings.model;
    const body = {
      doc_id: state.doc.doc_id,
      language: state.lang,
      level: state.level,
      force_local: Boolean(forceLocal || state.settings.forceLocal),
      api: Object.keys(api).length ? api : null
    };

    const controller = new AbortController();
    state.controller = controller;
    try {
      const response = await fetch("/api/notes/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal
      });
      if (!response.ok) throw new Error(await parseErrorResponse(response));
      if (!response.body) throw new Error("当前浏览器不支持流式响应。");

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        buffer = buffer.replace(/\r/g, "");
        let cut = buffer.indexOf("\n\n");
        while (cut !== -1) {
          const block = buffer.slice(0, cut);
          buffer = buffer.slice(cut + 2);
          if (block.trim()) processSSEBlock(block);
          cut = buffer.indexOf("\n\n");
        }
      }
      buffer += decoder.decode();
      if (buffer.trim()) processSSEBlock(buffer);
      if (state.stopped) return;
      if (state.generating) {
        failGeneration({ message: "连接意外结束，未收到完成信号，请重试。", can_fallback: true });
      }
    } catch (error) {
      if (error.name === "AbortError" || state.stopped) return;
      failGeneration({ message: error.message || "网络请求失败，请检查后端服务。", can_fallback: true });
    }
  }

  function notesFileName() {
    const raw = (state.doc && state.doc.filename) || "lecture";
    const base = raw.replace(/\.[^.]+$/, "").replace(/[\\/:*?"<>|]/g, "_").slice(0, 60);
    const language = { zh: "中文", en: "EN", bilingual: "双语" }[state.lang] || "中文";
    return base + "_笔记_L" + state.level + "_" + language + ".md";
  }

  function copyTable(table) {
    const rows = Array.prototype.slice.call(table.querySelectorAll("tr")).map(function (row) {
      return Array.prototype.slice.call(row.querySelectorAll("th, td")).map(function (cell) {
        return (cell.innerText || cell.textContent || "").replace(/\s+/g, " ").trim();
      }).join("\t");
    });
    const text = rows.join("\n");
    const done = function () { toast("表格已复制为 TSV。", "success"); };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done).catch(function () { legacyCopy(text, done); });
    } else {
      legacyCopy(text, done);
    }
  }

  function splitEnglishParagraphs(markdown) {
    if (state.lang !== "en") return markdown;
    const lines = String(markdown || "").split("\n");
    const output = [];
    let directiveDepth = 0;
    let code = false;
    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index];
      const trimmed = line.trim();
      if (/^```/.test(trimmed)) {
        code = !code;
        output.push(line);
        continue;
      }
      if (code) {
        output.push(line);
        continue;
      }
      if (/^:::\s*[a-zA-Z]/.test(trimmed)) {
        directiveDepth += 1;
        output.push(line);
        continue;
      }
      if (/^:::\s*$/.test(trimmed)) {
        directiveDepth = Math.max(0, directiveDepth - 1);
        output.push(line);
        continue;
      }
      const special =
        directiveDepth > 0 ||
        !trimmed ||
        /^#{1,4}\s/.test(trimmed) ||
        /^\s*[-*+]\s/.test(line) ||
        /^\s*\d+[.)]\s/.test(line) ||
        /^\s*\|/.test(line) ||
        /^\s*>/.test(line) ||
        /^\s*\[\[VISUAL/.test(trimmed) ||
        trimmed.indexOf("$") !== -1;
      if (special) {
        output.push(line);
        continue;
      }
      const words = trimmed.split(/\s+/);
      if (words.length <= 45) {
        output.push(line);
        continue;
      }
      const sentences = trimmed.split(/(?<=[.!?])\s+(?=[A-Z0-9(])/).filter(Boolean);
      if (sentences.length < 2) {
        output.push(line);
        continue;
      }
      const paragraphs = [];
      for (let cursor = 0; cursor < sentences.length; cursor += 2) {
        paragraphs.push(sentences.slice(cursor, cursor + 2).join(" "));
      }
      output.push(paragraphs.join("\n\n"));
    }
    return output.join("\n");
  }

  function ensureEnglishParallel(markdown) {
    if (state.lang !== "en" || state.noteMode !== "llm") return markdown;
    markdown = splitEnglishParagraphs(markdown);
    if (/:::(branches|pyramid|mindmap)/.test(markdown)) return markdown;
    const lines = String(markdown || "").split("\n");
    const output = [];
    let inserted = false;
    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      if (!inserted && /^##\s+/.test(line)) {
        let sectionEnd = index + 1;
        while (sectionEnd < lines.length && !/^##\s+/.test(lines[sectionEnd])) {
          sectionEnd += 1;
        }
        let start = -1;
        let end = -1;
        for (let probe = index + 1; probe < sectionEnd; probe += 1) {
          if (/^\s*[-*+]\s+/.test(lines[probe])) {
            if (start < 0) start = probe;
            end = probe + 1;
          } else if (start >= 0) {
            break;
          }
        }
        if (start >= 0 && end - start >= 3) {
          output.push(
            line,
            ...lines.slice(index + 1, start),
            "",
            ":::branches",
            ...lines.slice(start, end),
            ":::",
            ...lines.slice(end, sectionEnd)
          );
          index = sectionEnd;
          inserted = true;
          continue;
        }
      }
      output.push(line);
      index += 1;
    }
    return inserted ? output.join("\n") : markdown;
  }

  function exportableMarkdown() {
    return state.markdown.replace(
      /\[\[VISUAL\s+p\.?\s*(\d+)(?:\s+caption\s*=\s*"([^"]*)")?\s*\]\]\s*/gi,
      function (_, page, caption) {
        return "> 课件图示：第 " + page + " 页" + (caption ? "（" + caption + "）" : "") + "\n";
      }
    );
  }

  function exportMarkdown() {
    if (!state.markdown) return;
    const blob = new Blob([exportableMarkdown()], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = notesFileName();
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    toast("已导出 Markdown 文件。", "success");
  }

  function legacyCopy(text, done) {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try {
      document.execCommand("copy");
      done();
    } catch (error) {
      toast("复制失败，请使用导出功能。", "error");
    }
    area.remove();
  }

  function copyMarkdown() {
    if (!state.markdown) return;
    const text = exportableMarkdown();
    const done = function () { toast("Markdown 已复制到剪贴板。", "success"); };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done).catch(function () {
        legacyCopy(text, done);
      });
    } else {
      legacyCopy(text, done);
    }
  }

  function printNotes() {
    if (!state.markdown) return;
    renderNotesNow();
    decorateVisuals();
    setTimeout(function () { window.print(); }, 120);
  }

  function initSplitter() {
    let dragging = false;
    function update(clientX) {
      const rect = els.workspace.getBoundingClientRect();
      const pct = clamp((clientX - rect.left) / rect.width * 100, 38, 68);
      document.documentElement.style.setProperty("--left", pct.toFixed(2) + "%");
    }
    function end() {
      if (!dragging) return;
      dragging = false;
      document.body.classList.remove("resizing");
      const pct = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--left"));
      if (pct) localStorage.setItem(LS.split, String(pct));
      layoutSlide();
      layoutPptFigures();
    }
    els.splitter.addEventListener("pointerdown", function (event) {
      if (window.matchMedia("(max-width: 980px)").matches) return;
      dragging = true;
      document.body.classList.add("resizing");
      try { els.splitter.setPointerCapture(event.pointerId); } catch (error) { /* ignore */ }
      update(event.clientX);
      event.preventDefault();
    });
    window.addEventListener("pointermove", function (event) {
      if (!dragging) return;
      update(event.clientX);
      layoutSlide();
    });
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
    els.splitter.addEventListener("dblclick", function () {
      document.documentElement.style.setProperty("--left", "53%");
      localStorage.removeItem(LS.split);
      layoutSlide();
    });
  }

  function bindEvents() {
    const pickFile = function () { els.fileInput.click(); };
    els.uploadBtn.addEventListener("click", pickFile);
    els.emptyUploadBtn.addEventListener("click", pickFile);
    els.fileInput.addEventListener("change", function () {
      const file = els.fileInput.files && els.fileInput.files[0];
      els.fileInput.value = "";
      if (file) uploadFile(file);
    });
    els.sampleBtn.addEventListener("click", function (event) {
      event.stopPropagation();
      const open = els.sampleMenu.hidden;
      els.sampleMenu.hidden = !open;
      els.sampleBtn.setAttribute("aria-expanded", String(open));
    });
    els.sampleMenu.addEventListener("click", function (event) {
      const item = event.target.closest("button[data-demo]");
      if (!item) return;
      els.sampleMenu.hidden = true;
      els.sampleBtn.setAttribute("aria-expanded", "false");
      loadDemo(item.dataset.demo);
    });
    document.addEventListener("click", function (event) {
      if (els.sampleMenu.hidden) return;
      if (event.target.closest(".sample-wrap")) return;
      els.sampleMenu.hidden = true;
      els.sampleBtn.setAttribute("aria-expanded", "false");
    });
    els.demoPptxBtn.addEventListener("click", function () { loadDemo("pptx"); });
    els.demoPdfBtn.addEventListener("click", function () { loadDemo("pdf"); });

    els.settingsBtn.addEventListener("click", openSettings);
    els.closeSettingsBtn.addEventListener("click", closeSettings);
    els.cancelSettingsBtn.addEventListener("click", closeSettings);
    els.saveSettingsBtn.addEventListener("click", saveSettings);
    els.providerSelect.addEventListener("change", applyProviderPreset);
    els.toggleKeyBtn.addEventListener("click", function () {
      const show = els.apiKeyInput.type === "password";
      els.apiKeyInput.type = show ? "text" : "password";
      els.toggleKeyBtn.textContent = show ? "隐藏" : "显示";
    });
    els.settingsModal.addEventListener("click", function (event) {
      if (event.target === els.settingsModal) closeSettings();
    });

    els.langSeg.addEventListener("click", function (event) {
      const button = event.target.closest("button[data-lang]");
      if (!button || state.generating) return;
      state.lang = button.dataset.lang;
      state.lastCost = null;
      state.lastUsage = null;
      updateLangUI();
      updateModeChip();
      savePrefs();
      if (!restoreCachedNotes()) resetNotesForDoc();
    });
    els.levelRange.addEventListener("input", function () {
      if (state.generating) return;
      state.level = clamp(parseInt(els.levelRange.value, 10) || 3, 1, 5);
      state.lastCost = null;
      state.lastUsage = null;
      updateLevelUI();
      updateModeChip();
      savePrefs();
      if (!state.generating && !restoreCachedNotes()) resetNotesForDoc();
    });
    els.levelTicks.addEventListener("click", function (event) {
      const tick = event.target.closest("span[data-level]");
      if (!tick || state.generating) return;
      state.level = clamp(parseInt(tick.dataset.level, 10) || 3, 1, 5);
      state.lastCost = null;
      state.lastUsage = null;
      updateLevelUI();
      updateModeChip();
      savePrefs();
      if (!restoreCachedNotes()) resetNotesForDoc();
    });

    els.prevBtn.addEventListener("click", function () { changePage(-1); });
    els.nextBtn.addEventListener("click", function () { changePage(1); });
    els.zoomInBtn.addEventListener("click", function () { setZoom(state.zoom * 1.2); });
    els.zoomOutBtn.addEventListener("click", function () { setZoom(state.zoom / 1.2); });
    els.fitBtn.addEventListener("click", function () { state.zoom = 1; layoutSlide(); });

    els.thumbRail.addEventListener("click", function (event) {
      const thumb = event.target.closest(".thumb");
      if (!thumb) return;
      setPageIndex(Number(thumb.dataset.index), { resetScroll: true });
    });

    els.generateBtn.addEventListener("click", function () { generateNotes(false); });
    els.stopBtn.addEventListener("click", stopGeneration);
    els.fallbackBtn.addEventListener("click", function () { generateNotes(true); });
    els.errorSettingsBtn.addEventListener("click", openSettings);
    els.copyBtn.addEventListener("click", copyMarkdown);
    els.exportBtn.addEventListener("click", exportMarkdown);
    els.printBtn.addEventListener("click", printNotes);

    els.notesBody.addEventListener("click", function (event) {
      const tableCopy = event.target.closest(".table-copy");
      if (tableCopy) {
        const plugin = tableCopy.closest(".table-plugin");
        const table = plugin && plugin.querySelector("table");
        if (table) copyTable(table);
        return;
      }
      const ref = event.target.closest(".src-ref");
      if (ref) {
        goToPage(ref.dataset.page, { flash: true });
        if (window.matchMedia("(max-width: 980px)").matches) {
          const viewer = $("viewerPanel");
          if (viewer) viewer.scrollIntoView({ behavior: "smooth", block: "start" });
        }
        return;
      }
      const open = event.target.closest(".figure-open");
      if (open) {
        goToPage(open.dataset.page, { flash: true });
        return;
      }
      const frame = event.target.closest(".figure-frame");
      if (frame) {
        const figure = frame.closest(".note-figure");
        if (figure && figure.dataset.page) goToPage(figure.dataset.page, { flash: true });
      }
    });
    els.notesBody.addEventListener("change", function (event) {
      const input = event.target.closest && event.target.closest("input[data-section-id]");
      if (!input) return;
      toggleSection(input.dataset.sectionId, input.checked);
    });

    els.notesScroll.addEventListener("scroll", function () {
      const scroller = els.notesScroll;
      state.autoFollow =
        scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 70;
    }, { passive: true });

    let wheelLock = 0;
    els.slideStage.addEventListener("wheel", function (event) {
      if (!state.doc) return;
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        setZoom(state.zoom * (event.deltaY < 0 ? 1.12 : 1 / 1.12));
        return;
      }
      if (els.slideStage.classList.contains("overflowing")) return;
      if (Math.abs(event.deltaY) < Math.abs(event.deltaX) || Math.abs(event.deltaY) < 4) return;
      event.preventDefault();
      const now = Date.now();
      if (now - wheelLock < 280) return;
      wheelLock = now;
      changePage(event.deltaY > 0 ? 1 : -1);
    }, { passive: false });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !els.settingsModal.hidden) {
        closeSettings();
        return;
      }
      if (!els.settingsModal.hidden) return;
      const tag = (event.target.tagName || "").toLowerCase();
      if (["input", "textarea", "select"].indexOf(tag) !== -1 || event.target.isContentEditable) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        if (state.markdown) {
          event.preventDefault();
          exportMarkdown();
        }
        return;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        changePage(-1);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        changePage(1);
      }
    });

    let dragDepth = 0;
    window.addEventListener("dragenter", function (event) {
      if (!event.dataTransfer) return;
      const types = Array.prototype.slice.call(event.dataTransfer.types || []);
      if (types.indexOf("Files") === -1) return;
      dragDepth += 1;
      els.dropOverlay.hidden = false;
    });
    window.addEventListener("dragover", function (event) {
      if (!event.dataTransfer) return;
      const types = Array.prototype.slice.call(event.dataTransfer.types || []);
      if (types.indexOf("Files") === -1) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    });
    window.addEventListener("dragleave", function () {
      dragDepth = Math.max(0, dragDepth - 1);
      if (!dragDepth) els.dropOverlay.hidden = true;
    });
    window.addEventListener("drop", function (event) {
      if (!event.dataTransfer) return;
      event.preventDefault();
      dragDepth = 0;
      els.dropOverlay.hidden = true;
      const file = event.dataTransfer.files && event.dataTransfer.files[0];
      if (file) uploadFile(file);
    });
  }

  function setupResizeObserver() {
    if (!("ResizeObserver" in window)) return;
    let frame = 0;
    const observer = new ResizeObserver(function () {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(function () {
        layoutSlide();
        layoutPptFigures();
      });
    });
    observer.observe(els.slideStage);
    window.addEventListener("resize", function () {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(function () {
        layoutSlide();
        layoutPptFigures();
      });
    });
  }

  async function loadConfig() {
    try {
      const response = await fetch("/api/config", { cache: "no-store" });
      if (!response.ok) throw new Error("config failed");
      state.config = await response.json();
      if (!state.config.levels || !state.config.levels.length) {
        state.config.levels = DEFAULT_LEVELS;
      }
    } catch (error) {
      state.config = {
        llm_configured: false,
        defaults: { base_url: "", model: "", temperature: 0.3 },
        providers: [],
        levels: DEFAULT_LEVELS,
        max_upload_mb: 50
      };
      toast("无法连接后端服务，请确认已运行 python -m uvicorn backend.main:app", "error", 7000);
    }
    updateModeChip();
    updateLevelUI();
  }

  async function restoreLastDoc() {
    const saved = readJSON(LS.lastDoc, {});
    if (!saved || !saved.docId) {
      updateNav();
      return;
    }
    try {
      const response = await fetch("/api/doc/" + encodeURIComponent(saved.docId), { cache: "no-store" });
      if (!response.ok) throw new Error("not found");
      const doc = await response.json();
      applyDoc(doc);
    } catch (error) {
      try { localStorage.removeItem(LS.lastDoc); } catch (ignored) { /* ignore */ }
      updateNav();
    }
  }

  window.NotesApp = {
    getDoc: function () { return state.doc; },
    getSignature: noteSignature,
    getSections: function () { return state.sections || []; },
    getSectionError: function () { return state.sectionError || ""; },
    refreshSections: function () {
      sectionSyncKey = "";
      return syncSections();
    },
    setSectionCompleted: function (sectionId, completed) {
      return toggleSection(sectionId, Boolean(completed));
    },
    goToPage: function (page, options) { return goToPage(page, options); },
    toast: toast
  };

  async function init() {
    loadPrefs();
    bindEvents();
    initSplitter();
    setupResizeObserver();
    updateLangUI();
    updateLevelUI();
    updateModeChip();
    setStatus("等待课件");
    updateNav();
    await loadConfig();
    await restoreLastDoc();
  }

  init();
})();
