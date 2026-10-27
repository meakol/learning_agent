(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var registry = new Set();
  var state = {
    doc: null,
    signature: "",
    sections: [],
    summary: null,
    selectedSection: "",
    sectionsError: "",
    quiz: null,
    quizRecords: [],
    quizAnswers: {},
    quizController: null,
    chatController: null,
    streaming: false,
    workspace: "notes"
  };

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function notify(message) {
    if (window.NotesApp && window.NotesApp.toast) window.NotesApp.toast(message, "");
  }

  function apiConfig() {
    try {
      var saved = JSON.parse(localStorage.getItem("ln_agent_settings_v1") || "{}");
      if (!saved.apiKey) return null;
      return {
        base_url: saved.baseUrl || undefined,
        api_key: saved.apiKey,
        model: saved.model || undefined
      };
    } catch (ignored) {
      return null;
    }
  }

  function retrievalConfig() {
    try {
      var saved = JSON.parse(localStorage.getItem("ln_agent_settings_v1") || "{}");
      var mode = saved.embeddingMode || "hybrid";
      if (saved.embeddingModeVersion !== 2 && mode === "keyword") mode = "hybrid";
      return {
        retrieval_mode: mode,
        embedding: {
          base_url: saved.embeddingBaseUrl || "",
          model: saved.embeddingModel || "",
          api_key: saved.embeddingApiKey || saved.apiKey || "",
          max_tokens: saved.embeddingMaxTokens ? Number(saved.embeddingMaxTokens) : null,
          device: saved.embeddingDevice || ""
        }
      };
    } catch (ignored) {
      return { retrieval_mode: "hybrid", embedding: null };
    }
  }

  async function api(path, options) {
    var response = await fetch(path, Object.assign({ cache: "no-store" }, options || {}));
    var data = null;
    try { data = await response.json(); } catch (ignored) { /* ignore */ }
    if (!response.ok) throw new Error((data && data.detail) || ("请求失败：" + response.status));
    return data;
  }

  function switchWorkspace(name, options) {
    state.workspace = name;
    var notes = $("notesPanel");
    var panels = { quiz: $("quizPanel"), chat: $("chatPanel") };
    if (notes) notes.hidden = name !== "notes";
    Object.keys(panels).forEach(function (key) {
      if (panels[key]) panels[key].hidden = key !== name;
    });
    Array.prototype.forEach.call(document.querySelectorAll("#workspaceSwitch button"), function (button) {
      var active = button.dataset.workspace === name;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
    });
    try { localStorage.setItem("ln_agent_workspace_v1", name); } catch (ignored) { /* ignore */ }
    if (name !== "quiz" && state.quizController) {
      state.quizController.abort();
      state.quizController = null;
    }
    if (name === "quiz" && !(options && options.skipLoad)) loadQuizWorkspace();
    if (name === "chat") loadChat();
  }

  function loadQuizWorkspace() {
    return Promise.all([loadSections(), loadQuizHistory()]);
  }

  function registerFeature(id, init) {
    if (registry.has(id)) {
      console.warn("duplicate learning feature:", id);
      return false;
    }
    registry.add(id);
    init();
    return true;
  }

  function currentDoc() {
    return state.doc || (window.NotesApp && window.NotesApp.getDoc ? window.NotesApp.getDoc() : null);
  }

  function signature() {
    try {
      if (window.NotesApp && window.NotesApp.getSignature) {
        return String(window.NotesApp.getSignature() || "zh|3");
      }
    } catch (ignored) { /* ignore */ }
    return state.signature || "zh|3";
  }

  function applySections(data) {
    state.sections = (data && data.sections) || [];
    state.summary = (data && data.summary) || null;
    state.signature = (data && data.signature) || signature();
  }

  async function loadSections(retry) {
    var doc = currentDoc();
    if (!doc) {
      renderSectionOptions();
      return;
    }
    var requestedDocId = doc.doc_id;
    var sig = signature();
    var failure = "";
    try {
      var data = await api(
        "/api/sections?doc_id=" + encodeURIComponent(requestedDocId) +
        "&signature=" + encodeURIComponent(sig)
      );
      if (!currentDoc() || currentDoc().doc_id !== requestedDocId) return;
      applySections(data);
    } catch (error) {
      failure = error && error.message ? error.message : "章节读取失败";
      state.sections = [];
      state.summary = null;
    }
    if (!retry && !(state.sections || []).length &&
        window.NotesApp && window.NotesApp.refreshSections) {
      // Notes may have been restored from cache before the checklist sync ran.
      try { await window.NotesApp.refreshSections(); } catch (ignored) { /* ignore */ }
      return loadSections(true);
    }
    state.sectionsError = failure;
    renderSectionOptions();
  }

  function completedSections() {
    return (state.sections || []).filter(function (item) { return item.completed; });
  }

  function quizLanguage() {
    var select = $("quizLanguage");
    var saved = "";
    try { saved = localStorage.getItem("ln_agent_quiz_language_v1") || ""; } catch (ignored) { /* ignore */ }
    if (select) {
      if (!select.dataset.ready) {
        var notesLang = String(signature().split("|")[0] || "zh");
        select.value = saved || (notesLang === "en" ? "en" : "zh");
        select.dataset.ready = "1";
      }
      return select.value === "en" ? "en" : "zh";
    }
    return saved === "en" ? "en" : "zh";
  }

  function syncQuizCount(selectedCount) {
    var input = $("quizCount");
    if (!input) return;
    if (!input.dataset.touched) input.value = String(Math.min(10, Math.max(1, selectedCount * 2)));
  }

  function renderSectionChips(done, pending) {
    var box = $("quizSectionChips");
    if (!box) return;
    var waiting = pending || [];
    if (!done.length && !waiting.length) {
      box.hidden = true;
      box.innerHTML = "";
      return;
    }
    var active = state.selectedSection || "__all__";
    var chips = [];
    if (done.length) {
      chips.push('<button type="button" class="section-chip' +
        (active === "__all__" ? " active" : "") + '" data-section-chip="__all__">' +
        "全部已勾选<span>" + done.length + " 章</span></button>");
    }
    done.forEach(function (item) {
      var pages = item.pages || [];
      var suffix = pages.length > 1
        ? "p." + pages[0] + "-" + pages[pages.length - 1]
        : "p." + pages[0];
      chips.push(
        '<button type="button" class="section-chip' +
        (active === item.section_id ? " active" : "") +
        '" data-section-chip="' + escapeHtml(item.section_id) + '">' +
        escapeHtml(item.title) + "<span>" + suffix + "</span></button>"
      );
    });
    waiting.forEach(function (item) {
      chips.push(
        '<button type="button" class="section-chip pending" data-goto-notes="1"' +
        ' title="到笔记里勾选该章节">' + escapeHtml(item.title) +
        "<span>去勾选</span></button>"
      );
    });
    box.innerHTML = chips.join("");
    box.hidden = false;
    Array.prototype.forEach.call(box.querySelectorAll("[data-section-chip]"), function (chip) {
      chip.addEventListener("click", function () {
        state.selectedSection = chip.getAttribute("data-section-chip");
        renderSectionOptions();
      });
    });
    Array.prototype.forEach.call(box.querySelectorAll("[data-goto-notes]"), function (chip) {
      chip.addEventListener("click", function () {
        switchWorkspace("notes");
      });
    });
  }

  function renderSectionOptions() {
    var select = $("quizSectionSelect");
    var button = $("generateQuizBtn");
    var done = completedSections();
    if (!select) return;
    var previous = state.selectedSection || select.value || "__all__";
    if (!done.length) {
      select.innerHTML = '<option value="">先在笔记中勾选章节</option>';
      select.disabled = true;
      if (button) button.disabled = true;
      renderSectionChips([], state.sections || []);
      var error = state.sectionsError ||
        (window.NotesApp && window.NotesApp.getSectionError ? window.NotesApp.getSectionError() : "");
      $("quizStatus").textContent = error
        ? error
        : (state.sections.length
          ? "已注册 " + state.sections.length + " 个章节，勾选后即可出题"
          : "先生成笔记，再勾选章节");
      return;
    }
    select.disabled = false;
    var options = ['<option value="__all__">全部已勾选章节（' + done.length + "）</option>"];
    done.forEach(function (item) {
      var pages = item.pages || [];
      var suffix = pages.length > 1 ? "p." + pages[0] + "-" + pages[pages.length - 1] : "p." + pages[0];
      options.push(
        '<option value="' + escapeHtml(item.section_id) + '">' +
        escapeHtml(item.title) + " · " + suffix + "</option>"
      );
    });
    select.innerHTML = options.join("");
    var keep = previous !== "__all__" && done.some(function (item) {
      return item.section_id === previous;
    });
    select.value = keep ? previous : "__all__";
    state.selectedSection = select.value;
    if (button) button.disabled = false;
    var total = (state.summary && state.summary.total) || (state.sections || []).length;
    if (!state.quiz) {
      $("quizStatus").textContent = "已完成 " + done.length + "/" + total + " 章，可开始测试";
    }
    syncQuizCount(select.value === "__all__" ? done.length : 1);
    renderSectionChips(done, (state.sections || []).filter(function (item) {
      return !item.completed;
    }));
  }

  function quizSectionIds() {
    var select = $("quizSectionSelect");
    var done = completedSections();
    var value = select ? select.value : "__all__";
    if (!value || value === "__all__") {
      return done.map(function (item) { return item.section_id; });
    }
    return [value];
  }

  function renderQuizEmptyState(message) {
    var box = $("quizQuestions");
    if (box) box.innerHTML = '<div class="learning-empty">' + escapeHtml(message) + "</div>";
    if ($("submitQuizBtn")) $("submitQuizBtn").disabled = true;
    if ($("retryQuizBtn")) $("retryQuizBtn").hidden = true;
    if ($("quizResult")) $("quizResult").textContent = "";
  }

  function restoreQuiz(quiz, result) {
    state.quiz = quiz || null;
    state.quizAnswers = {};
    if (!state.quiz || !(state.quiz.questions || []).length) {
      renderQuizEmptyState("还没有测试，选择章节后点击“生成测试”。");
      $("quizStatus").textContent = "等待生成测试";
      return;
    }
    renderQuiz();
    if (result) renderQuizResult(result);
    $("quizStatus").textContent = result
      ? "已恢复上次测试，得分 " + Math.round(Number(result.score || 0) * 100) + "%"
      : "已恢复上次生成的测试";
  }

  function renderQuizResult(result) {
    var box = $("quizResult");
    if (!box) return;
    box.innerHTML = '<strong>得分 ' + result.correct_count + "/" + result.total_count +
      "（" + Math.round(Number(result.score || 0) * 100) + "%）</strong>" +
      (result.results || []).map(function (item, index) {
        return '<div class="quiz-question"><h4>' + (index + 1) + ". " +
          (item.correct ? "正确" : "错误") + '</h4><div>正确答案：' + escapeHtml(item.correct_answer) +
          '</div><div>' + escapeHtml(item.explanation) + '</div></div>';
      }).join("");
  }

  async function loadQuizHistory() {
    var doc = currentDoc();
    if (!doc) return;
    var requestedDocId = doc.doc_id;
    var sig = signature();
    try {
      var data = await api(
        "/api/quiz/history?doc_id=" + encodeURIComponent(requestedDocId) +
        "&signature=" + encodeURIComponent(sig)
      );
      if (!currentDoc() || currentDoc().doc_id !== requestedDocId) return;
      state.quizRecords = data.records || [];
      renderQuizHistory();
      if (!state.quiz && data.quiz) {
        restoreQuiz(data.quiz, data.result);
      }
    } catch (error) {
      var box = $("quizHistory");
      if (box) box.innerHTML = '<div class="quiz-history-empty">' + escapeHtml(error.message) + "</div>";
    }
  }

  function renderQuizHistory() {
    var box = $("quizHistory");
    if (!box) return;
    var records = state.quizRecords || [];
    if (!records.length) {
      box.innerHTML = '<div class="quiz-history-empty">还没有测试记录。</div>';
      return;
    }
    box.innerHTML = '<div class="quiz-history-title">全部测试记录（' + records.length + '）</div>' +
      records.map(function (record) {
        var score = record.result
          ? record.result.correct_count + "/" + record.result.total_count +
            " · " + Math.round(Number(record.result.score || 0) * 100) + "%"
          : "未提交";
        var source = record.source === "fallback" ? "原文比对题" : "模型题";
        var language = record.language === "en" ? "EN" : "中文";
        var date = String(record.created_at || "").replace("T", " ").slice(0, 16);
        var quiz = record.quiz || {};
        var questions = quiz.questions || [];
        var results = {};
        ((record.result && record.result.results) || []).forEach(function (item) {
          results[item.question_id] = item;
        });
        var detail = '<div class="quiz-history-detail">';
        if (record.result) {
          detail += '<div class="quiz-history-score">得分 ' + record.result.correct_count + "/" +
            record.result.total_count + "（" + Math.round(Number(record.result.score || 0) * 100) +
            "%）</div>";
        } else {
          detail += '<div class="quiz-history-score">尚未提交</div>';
        }
        detail += questions.map(function (question, index) {
          var answer = results[question.question_id];
          var status = answer ? (answer.correct ? "正确" : "错误") : "";
          return '<div class="quiz-history-question"><strong>' + (index + 1) + ". " +
            escapeHtml(question.question_text) + '</strong>' +
            (status ? '<span class="quiz-history-answer">' + status + '</span>' : "") +
            '<div>' + (question.options || []).map(function (option) {
              return '<div>' + escapeHtml(option) + '</div>';
            }).join("") + '</div>' +
            (answer ? '<small>正确答案：' + escapeHtml(answer.correct_answer) +
              ' · ' + escapeHtml(answer.explanation) + '</small>' : "") +
            '</div>';
        }).join("");
        detail += '<button type="button" class="btn ghost small" data-open-record="' +
          escapeHtml(record.quiz_id) + '">在测试面板打开</button></div>';
        return '<details class="quiz-history-item"><summary class="quiz-history-row">' +
          '<span>' + escapeHtml((record.section_titles || []).join("、") || "章节测试") + '</span>' +
          '<small>' + escapeHtml(language) + " · " + escapeHtml(source) + " · " +
          escapeHtml(score) + " · " + escapeHtml(date) +
          '</small></summary>' + detail + '</details>';
      }).join("");
    Array.prototype.forEach.call(box.querySelectorAll("[data-open-record]"), function (button) {
      button.addEventListener("click", function () {
        openQuizRecord(button.getAttribute("data-open-record"));
      });
    });
  }

  async function openQuizRecord(quizId) {
    var doc = currentDoc();
    if (!doc || !quizId) return;
    var requestedDocId = doc.doc_id;
    try {
      var quiz = await api("/api/quiz/" + encodeURIComponent(quizId));
      if (!currentDoc() || currentDoc().doc_id !== requestedDocId) return;
      var record = (state.quizRecords || []).filter(function (item) {
        return item.quiz_id === quizId;
      })[0];
      var select = $("quizSectionSelect");
      if (select && record && (record.section_ids || []).length === 1) {
        var targetId = record.section_ids[0];
        var exists = Array.prototype.some.call(select.options, function (option) {
          return option.value === targetId;
        });
        if (exists) {
          select.value = targetId;
          state.selectedSection = targetId;
        }
      }
      state.quiz = quiz;
      state.quizAnswers = {};
      renderQuiz();
      if (record && record.result) renderQuizResult(record.result);
      $("quizStatus").textContent = record && record.result
        ? "历史测试，得分 " + Math.round(Number(record.result.score || 0) * 100) + "%"
        : "历史测试";
    } catch (error) {
      $("quizStatus").textContent = error.message;
    }
  }

  async function generateQuiz(force) {
    var doc = currentDoc();
    if (!doc) { notify("请先上传课件。"); return; }
    var ids = quizSectionIds();
    if (!ids.length) { notify("请先在笔记中勾选章节。"); return; }
    var requestedDocId = doc.doc_id;
    var requestedSignature = signature();
    var language = quizLanguage();
    var button = $("generateQuizBtn");
    if (state.quizController) state.quizController.abort();
    var controller = new AbortController();
    state.quizController = controller;
    if (button) button.disabled = true;
    $("quizStatus").textContent = "生成中…";
    try {
      var data = await api("/api/quiz", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          doc_id: requestedDocId,
          signature: requestedSignature,
          section_ids: ids,
          question_count: Math.min(10, Math.max(1, Number($("quizCount").value || 5))),
          difficulty: $("quizDifficulty").value,
          language: language,
          force: Boolean(force),
          api: apiConfig()
        })
      });
      if (controller.signal.aborted) return;
      if (!currentDoc() || currentDoc().doc_id !== requestedDocId) return;
      if (quizSectionIds().join("|") !== ids.join("|")) return;
      state.quiz = data.quiz;
      state.quizAnswers = {};
      renderQuiz();
      if (!state.quiz || !(state.quiz.questions || []).length) {
        $("quizStatus").textContent = "内容不足，未能生成题目";
        notify("所选章节内容不足，未能生成题目。");
      } else if (state.quiz.source === "fallback") {
        $("quizStatus").textContent = "使用课件原文比对题（模型未返回有效题目）";
        notify("模型未返回有效题目，已改用课件原文比对题。");
      } else {
        $("quizStatus").textContent = data.cached ? "已复用缓存测试" : "测试已生成";
      }
      loadQuizHistory();
    } catch (error) {
      if (error.name !== "AbortError") {
        $("quizStatus").textContent = error.message;
        notify(error.message);
      }
    } finally {
      if (state.quizController === controller) {
        state.quizController = null;
        if (button) button.disabled = false;
      } else if (!state.quizController && controller.signal.aborted && button) {
        button.disabled = false;
      }
    }
  }

  function renderQuiz() {
    var box = $("quizQuestions");
    if (!box) return;
    if (!state.quiz || !state.quiz.questions || !state.quiz.questions.length) {
      box.innerHTML = '<div class="learning-empty">题目生成失败或内容不足，请稍后重试。</div>';
      $("submitQuizBtn").disabled = true;
      $("retryQuizBtn").hidden = false;
      return;
    }
    box.innerHTML = state.quiz.questions.map(function (question, index) {
      var options = question.options.map(function (option) {
        return '<label class="quiz-option"><input type="radio" name="q-' + index + '" value="' +
          escapeHtml(option.charAt(0)) + '"> ' + escapeHtml(option) + "</label>";
      }).join("");
      var type = question.question_type === "apply"
        ? '<span class="quiz-type apply">应用题</span>'
        : '<span class="quiz-type">辨析题</span>';
      return '<div class="quiz-question"><h4>' + (index + 1) + ". " + escapeHtml(question.question_text) +
        type + '</h4>' + options + '<div class="quiz-hint" data-hint="' + index + '">显示提示</div>' +
        '<div class="quiz-hint-text" id="hint-' + index + '" hidden>' + escapeHtml(question.hint || "") +
        '</div></div>';
    }).join("");
    Array.prototype.forEach.call(box.querySelectorAll("input[type=radio]"), function (input) {
      input.addEventListener("change", function () {
        state.quizAnswers[input.name] = input.value;
        $("submitQuizBtn").disabled = Object.keys(state.quizAnswers).length !== state.quiz.questions.length;
      });
    });
    Array.prototype.forEach.call(box.querySelectorAll("[data-hint]"), function (node) {
      node.addEventListener("click", function () {
        var target = $("hint-" + node.getAttribute("data-hint"));
        if (target) target.hidden = !target.hidden;
      });
    });
    $("submitQuizBtn").disabled = true;
    $("retryQuizBtn").hidden = false;
    $("quizResult").textContent = "";
  }

  async function submitQuiz() {
    if (!state.quiz || !state.quiz.questions) return;
    var answers = state.quiz.questions.map(function (question, index) {
      return { question_id: question.question_id, selected: state.quizAnswers["q-" + index] || "" };
    });
    try {
      var result = await api("/api/quiz/" + encodeURIComponent(state.quiz.quiz_id) + "/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answers: answers })
      });
      $("submitQuizBtn").disabled = true;
      renderQuizResult(result);
      $("quizStatus").textContent = "已完成，得分 " + Math.round(result.score * 100) + "%";
      loadQuizHistory();
    } catch (error) {
      $("quizStatus").textContent = error.message;
    }
  }

  function renderChat(messages) {
    var box = $("chatMessages");
    if (!box) return;
    box.innerHTML = "";
    (messages || []).forEach(function (message) {
      appendChatMessage(message.role, message.content || "");
    });
    box.scrollTop = box.scrollHeight;
  }

  function appendChatMessage(role, text) {
    var box = $("chatMessages");
    if (!box) return null;
    var node = document.createElement("div");
    node.className = "chat-message " + (role === "user" ? "user" : "assistant");
    if (role === "assistant" && window.NotesMarkdown && window.NotesMarkdown.render) {
      node.innerHTML = window.NotesMarkdown.render(text);
    } else {
      node.textContent = text;
    }
    box.appendChild(node);
    box.scrollTop = box.scrollHeight;
    return node;
  }

  async function loadChat() {
    var doc = currentDoc();
    if (!doc) return;
    try {
      var data = await api("/api/chat/history?doc_id=" + encodeURIComponent(doc.doc_id));
      renderChat(data.messages || []);
    } catch (error) {
      $("chatStatus").textContent = error.message;
    }
  }

  function parseSSE(buffer, onEvent) {
    var cut = buffer.indexOf("\n\n");
    while (cut !== -1) {
      var block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      block.split("\n").forEach(function (line) {
        if (line.indexOf("data:") !== 0) return;
        var raw = line.slice(5).trim();
        if (!raw || raw === "[DONE]") return;
        try { onEvent(JSON.parse(raw)); } catch (ignored) { /* ignore */ }
      });
      cut = buffer.indexOf("\n\n");
    }
    return buffer;
  }

  async function sendChat() {
    var doc = currentDoc();
    var input = $("chatInput");
    var message = input.value.trim();
    if (!doc || !message || state.streaming) return;
    input.value = "";
    appendChatMessage("user", message);
    var bubble = appendChatMessage("assistant", "");
    state.streaming = true;
    var controller = new AbortController();
    state.chatController = controller;
    $("sendChatBtn").disabled = true;
    $("chatStatus").textContent = "回答中…";
    try {
      var response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.assign(
          { doc_id: doc.doc_id, message: message, api: apiConfig() },
          retrievalConfig()
        )),
        signal: controller.signal
      });
      if (!response.ok) {
        var errorData = null;
        try { errorData = await response.json(); } catch (ignored) { /* ignore */ }
        throw new Error((errorData && errorData.detail) || "问答请求失败");
      }
      var reader = response.body.getReader();
      var decoder = new TextDecoder("utf-8");
      var buffer = "";
      var answer = "";
      while (true) {
        var chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        buffer = parseSSE(buffer, function (event) {
          if (event.type === "meta") {
            $("chatMode").textContent = "检索模式：" + (event.retrieval_mode || "keyword") +
              (event.degraded ? "（已降级）" : "");
            var banner = $("chatDegraded");
            if (banner) {
              banner.hidden = !(event.degraded || event.index_stale);
              banner.textContent = event.index_stale
                ? "索引已过期，请重建索引后使用向量检索。"
                : (event.degraded ? "语义检索降级，当前使用关键词检索。" + (event.degraded_reason ? " " + event.degraded_reason : "") : "");
            }
          }
          if (event.type === "delta") {
            answer += event.text || "";
            bubble.innerHTML = window.NotesMarkdown && window.NotesMarkdown.render
              ? window.NotesMarkdown.render(answer)
              : escapeHtml(answer);
            bubble.parentElement.scrollTop = bubble.parentElement.scrollHeight;
          }
          if (event.type === "done") {
            $("chatStatus").textContent = event.general_knowledge
              ? "课件未找到直接依据，已使用通用知识回答"
              : (event.grounded ? "已基于课件回答" : "引用校验未通过");
          }
          if (event.type === "error") {
            $("chatStatus").textContent = event.message || "问答失败";
          }
        });
      }
    } catch (error) {
      if (error.name !== "AbortError") $("chatStatus").textContent = error.message;
    } finally {
      state.streaming = false;
      $("sendChatBtn").disabled = false;
    }
  }

  async function clearChat() {
    var doc = currentDoc();
    if (!doc) return;
    try {
      await api("/api/chat/history?doc_id=" + encodeURIComponent(doc.doc_id), { method: "DELETE" });
      renderChat([]);
    } catch (error) {
      notify(error.message);
    }
  }

  async function onQuizRequest(event) {
    var detail = event.detail || {};
    var doc = currentDoc();
    if (!doc || !detail.section_id) {
      notify("章节还没准备好，请稍后再试。");
      return;
    }
    switchWorkspace("quiz", { skipLoad: true });
    $("quizStatus").textContent = "正在准备该章节的测试…";
    await loadSections();
    loadQuizHistory();
    var item = (state.sections || []).filter(function (entry) {
      return entry.section_id === detail.section_id;
    })[0];
    if (!item) {
      var reason = state.sectionsError ||
        (window.NotesApp && window.NotesApp.getSectionError ? window.NotesApp.getSectionError() : "");
      $("quizStatus").textContent = reason || "该章节尚未注册，请重新生成笔记";
      notify(reason || "该章节尚未注册，请重新生成笔记后再试。");
      return;
    }
    if (!item.completed && window.NotesApp && window.NotesApp.setSectionCompleted) {
      state.selectedSection = detail.section_id;
      await window.NotesApp.setSectionCompleted(detail.section_id, true);
      await loadSections();
      var refreshed = (state.sections || []).filter(function (entry) {
        return entry.section_id === detail.section_id;
      })[0];
      if (!refreshed || !refreshed.completed) {
        $("quizStatus").textContent = "勾选该章节失败，请手动勾选后重试";
        notify("勾选该章节失败，请手动勾选后重试。");
        return;
      }
    }
    state.selectedSection = detail.section_id;
    renderSectionOptions();
    generateQuiz(false);
  }

  function onDocChanged(event) {
    if (state.quizController) state.quizController.abort();
    state.quizController = null;
    if (state.chatController) state.chatController.abort();
    state.chatController = null;
    state.doc = event.detail && event.detail.doc;
    state.sections = [];
    state.summary = null;
    state.signature = "";
    state.sectionsError = "";
    state.quiz = null;
    state.quizRecords = [];
    state.quizAnswers = {};
    state.selectedSection = "";
    var historyBox = $("quizHistory");
    if (historyBox) historyBox.innerHTML = "";
    if (state.workspace === "quiz") loadQuizWorkspace();
    if (state.workspace === "chat") loadChat();
  }

  function onSectionsChanged(event) {
    var detail = event.detail || {};
    if (!currentDoc() || !detail.sections) return;
    state.sections = detail.sections;
    state.summary = detail.summary || state.summary;
    state.signature = detail.signature || signature();
    state.sectionsError = "";
    renderSectionOptions();
  }

  function bind() {
    var nav = $("workspaceSwitch");
    if (nav) {
      nav.addEventListener("click", function (event) {
        var button = event.target.closest("button[data-workspace]");
        if (button) switchWorkspace(button.dataset.workspace);
      });
    }
    if ($("generateQuizBtn")) $("generateQuizBtn").addEventListener("click", function () {
      generateQuiz(Boolean(state.quiz));
    });
    if ($("submitQuizBtn")) $("submitQuizBtn").addEventListener("click", submitQuiz);
    if ($("retryQuizBtn")) $("retryQuizBtn").addEventListener("click", function () { generateQuiz(true); });
    if ($("quizSectionSelect")) {
      $("quizSectionSelect").addEventListener("change", function () {
        state.selectedSection = $("quizSectionSelect").value;
        syncQuizCount(state.selectedSection === "__all__" ? completedSections().length : 1);
      });
    }
    if ($("quizCount")) {
      $("quizCount").addEventListener("input", function () {
        $("quizCount").dataset.touched = "1";
      });
    }
    if ($("quizLanguage")) {
      $("quizLanguage").addEventListener("change", function () {
        try {
          localStorage.setItem("ln_agent_quiz_language_v1", quizLanguage());
        } catch (ignored) { /* ignore */ }
      });
    }
    if ($("sendChatBtn")) $("sendChatBtn").addEventListener("click", sendChat);
    if ($("clearChatBtn")) $("clearChatBtn").addEventListener("click", clearChat);
    if ($("chatInput")) {
      $("chatInput").addEventListener("keydown", function (event) {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          sendChat();
        }
      });
    }
    document.addEventListener("notes:doc-changed", onDocChanged);
    document.addEventListener("notes:sections-changed", onSectionsChanged);
    document.addEventListener("notes:quiz-request", onQuizRequest);
  }

  function init() {
    bind();
    state.doc = window.NotesApp && window.NotesApp.getDoc ? window.NotesApp.getDoc() : null;
    var saved = null;
    try { saved = localStorage.getItem("ln_agent_workspace_v1"); } catch (ignored) { /* ignore */ }
    if (saved === "plan") saved = "notes";
    switchWorkspace(saved || "notes");
    loadSections();
    registerFeature("stage3.chat", function () { /* chat handlers bound above */ });
    registerFeature("stage5.quiz", function () { /* quiz handlers bound above */ });
  }

  init();
})();
