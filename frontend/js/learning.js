(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var registry = new Set();
  var state = {
    doc: null,
    plans: [],
    activePlanId: null,
    plan: null,
    progress: null,
    quiz: null,
    quizRecords: [],
    quizAnswers: {},
    quizController: null,
    autoQuizTimer: 0,
    chatController: null,
    streaming: false
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

  function switchWorkspace(name) {
    state.workspace = name;
    var notes = $("notesPanel");
    var panels = { plan: $("planPanel"), quiz: $("quizPanel"), chat: $("chatPanel") };
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
    if (name !== "quiz") {
      if (state.autoQuizTimer) {
        clearTimeout(state.autoQuizTimer);
        state.autoQuizTimer = 0;
      }
      if (state.quizController) {
        state.quizController.abort();
        state.quizController = null;
      }
    }
    if (name === "plan") loadPlans();
    if (name === "quiz") loadQuizWorkspace();
    if (name === "chat") loadChat();
  }

  function loadQuizWorkspace() {
    return loadPlans()
      .then(function () { return loadPlan(); })
      .then(function () {
        renderMilestones();
        return loadQuizState();
      })
      .then(function () { return loadQuizHistory(); });
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

  async function loadPlans() {
    var doc = currentDoc();
    var list = $("planList");
    if (!list) return;
    if (!doc) {
      list.innerHTML = '<div class="learning-empty">先上传课件，再创建学习计划。</div>';
      return;
    }
    try {
      var data = await api("/api/doc/" + encodeURIComponent(doc.doc_id) + "/plans");
      state.plans = data.plans || [];
      state.activePlanId = data.active_plan_id || null;
      renderPlanList();
      if (state.activePlanId) await loadPlan();
    } catch (error) {
      list.innerHTML = '<div class="learning-empty">' + escapeHtml(error.message) + "</div>";
    }
  }

  function renderPlanList() {
    var list = $("planList");
    if (!list) return;
    if (!state.plans.length) {
      list.innerHTML = '<div class="learning-empty">还没有计划。设置天数与每天时长后生成。</div>';
      return;
    }
    list.innerHTML = state.plans.map(function (plan) {
      var active = plan.plan_id === state.activePlanId;
      return '<div class="plan-row"><button type="button" class="plan-card' + (active ? " active" : "") + '" data-plan="' + escapeHtml(plan.plan_id) + '">' +
        '<div class="plan-card-head"><h3>' + escapeHtml(plan.title) + '</h3><small>' + plan.total_milestones + ' 个里程碑</small></div>' +
        '<small>' + plan.total_pages + ' 页 · ' + plan.estimated_days + ' 天 · ' + plan.progress.percent + '%</small>' +
        '</button><button type="button" class="plan-delete" data-delete-plan="' + escapeHtml(plan.plan_id) + '" title="删除计划" aria-label="删除计划">✕</button></div>';
    }).join("");
    Array.prototype.forEach.call(list.querySelectorAll("[data-plan]"), function (button) {
      button.addEventListener("click", function () {
        state.activePlanId = button.dataset.plan;
        api("/api/plan/" + encodeURIComponent(button.dataset.plan) + "/activate", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: "{}"
        }).then(function () { return loadPlan(); })
          .then(function () { renderPlanList(); return loadChat(); })
          .catch(function (error) { notify(error.message); });
      });
    });
    Array.prototype.forEach.call(list.querySelectorAll("[data-delete-plan]"), function (button) {
      button.addEventListener("click", function (event) {
        event.stopPropagation();
        var planId = button.getAttribute("data-delete-plan");
        if (!window.confirm("删除该计划及其进度与测试？此操作不可恢复。")) return;
        button.disabled = true;
        api("/api/plan/" + encodeURIComponent(planId), { method: "DELETE" })
          .then(function () {
            if (state.activePlanId === planId) {
              state.activePlanId = null;
              state.plan = null;
              state.progress = null;
              state.quiz = null;
              var detail = $("planDetail");
              if (detail) detail.innerHTML = '<div class="learning-empty">选择或创建一个计划。</div>';
            }
            return loadPlans();
          })
          .then(function () { notify("计划已删除。"); })
          .catch(function (error) { button.disabled = false; notify(error.message); });
      });
    });
  }

  async function loadPlan() {
    var doc = currentDoc();
    var detail = $("planDetail");
    if (!doc || !state.activePlanId) {
      state.plan = null;
      if (detail) detail.innerHTML = '<div class="learning-empty">选择或创建一个计划。</div>';
      return null;
    }
    try {
      state.plan = await api("/api/plan/" + encodeURIComponent(state.activePlanId));
      state.progress = await api("/api/progress/" + encodeURIComponent(doc.doc_id) + "/" + encodeURIComponent(state.activePlanId));
      renderPlanDetail();
      return state.plan;
    } catch (error) {
      state.plan = null;
      if (detail) detail.innerHTML = '<div class="learning-empty">' + escapeHtml(error.message) + "</div>";
      return null;
    }
  }

  function renderPlanDetail() {
    var detail = $("planDetail");
    if (!detail || !state.plan) return;
    var states = {};
    ((state.progress && state.progress.milestone_states) || []).forEach(function (item) {
      states[item.milestone_id] = item;
    });
    var completed = (state.progress && state.progress.progress && state.progress.progress.completed_pages) || [];
    var sourceLabel = state.plan.source === "fallback" ? "回退计划 · 模型未返回有效结果" : "模型生成计划";
    detail.innerHTML = '<div class="learning-note">' + escapeHtml(sourceLabel) + '</div>' +
      state.plan.milestones.map(function (milestone) {
      var ms = states[milestone.milestone_id] || {};
      var pages = [];
      for (var page = milestone.page_range.start; page <= milestone.page_range.end; page += 1) {
        pages.push('<label><input type="checkbox" data-page="' + page + '"' +
          (completed.indexOf(page) !== -1 ? " checked" : "") + "> 第 " + page + " 页</label>");
      }
      return '<div class="milestone-card" data-milestone="' + escapeHtml(milestone.milestone_id) + '">' +
        '<div class="milestone-title"><span>' + escapeHtml(milestone.title) + '</span><small>' +
        (ms.completed ? "已完成" : (ms.quiz_available ? "可测试" : "进行中")) + '</small></div>' +
        '<small>第 ' + milestone.page_range.start + '–' + milestone.page_range.end + ' 页 · ' +
        milestone.estimated_minutes + ' 分钟</small>' +
        '<div class="milestone-pages">' + pages.join("") + '</div></div>';
    }).join("");
    Array.prototype.forEach.call(detail.querySelectorAll("input[data-page]"), function (input) {
      input.addEventListener("change", function () {
        updatePage(Number(input.dataset.page), input.checked);
      });
    });
  }

  async function updatePage(page, completed) {
    var doc = currentDoc();
    if (!doc || !state.plan) return;
    try {
      var data = await api("/api/progress/" + encodeURIComponent(doc.doc_id) + "/" +
        encodeURIComponent(state.plan.plan_id) + "/page", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ page: page, completed: completed })
      });
      state.progress = data;
      renderPlanDetail();
      if (completed && Array.isArray(data.milestone_completed) && data.milestone_completed.length) {
        scheduleAutoQuiz(data.milestone_completed[0]);
      }
      await loadPlans();
    } catch (error) {
      notify(error.message);
      renderPlanDetail();
    }
  }

  function scheduleAutoQuiz(milestoneId) {
    if (!state.doc || !state.plan || !milestoneId) return;
    if (state.autoQuizTimer) clearTimeout(state.autoQuizTimer);
    var planId = state.plan.plan_id;
    var docId = state.doc.doc_id;
    state.autoQuizTimer = setTimeout(function () {
      state.autoQuizTimer = 0;
      if (!state.doc || state.doc.doc_id !== docId || !state.plan || state.plan.plan_id !== planId) return;
      var select = $("quizMilestoneSelect");
      if (select && select.value && select.value !== milestoneId) return;
      generateQuiz(milestoneId, true);
    }, 500);
  }

  async function createPlan() {
    var doc = currentDoc();
    if (!doc) { notify("请先上传课件。"); return; }
    var button = $("createPlanBtn");
    if (button) button.disabled = true;
    try {
      var plan = await api("/api/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          doc_id: doc.doc_id,
          total_days: Number($("planDays").value || 5),
          daily_minutes: Number($("planMinutes").value || 60),
          difficulty: Number($("planDifficulty").value || 3),
          api: apiConfig()
        })
      });
      state.activePlanId = plan.plan_id;
      state.plan = plan;
      await loadPlans();
      if (plan.source === "fallback") {
        notify("模型未返回有效计划，已生成回退计划。" + (plan.warnings && plan.warnings[0] ? " " + plan.warnings[0] : ""));
      } else {
        notify("学习计划已生成。");
      }
    } catch (error) {
      notify(error.message);
    } finally {
      if (button) button.disabled = false;
    }
  }

  function quizMilestoneKey() {
    var doc = currentDoc();
    return doc && state.plan ? doc.doc_id + "|" + state.plan.plan_id : "";
  }

  function renderMilestones() {
    var select = $("quizMilestoneSelect");
    if (!select) return;
    if (!state.plan) {
      select.innerHTML = '<option value="">先创建学习计划</option>';
      return;
    }
    var savedMilestone = "";
    try {
      savedMilestone = localStorage.getItem("ln_agent_quiz_milestone_v1:" + quizMilestoneKey()) || "";
    } catch (ignored) { /* ignore */ }
    var previous = select.value || savedMilestone;
    select.innerHTML = state.plan.milestones.map(function (milestone) {
      return '<option value="' + escapeHtml(milestone.milestone_id) + '">' +
        escapeHtml(milestone.title) + "</option>";
    }).join("");
    var exists = Array.prototype.some.call(select.options, function (option) {
      return option.value === previous;
    });
    if (exists) {
      select.value = previous;
    } else {
      select.selectedIndex = state.plan.milestones.length - 1;
    }
  }

  async function loadQuizState() {
    var doc = currentDoc();
    var plan = state.plan;
    var select = $("quizMilestoneSelect");
    if (!doc || !plan || !select || !select.value) return;
    var requestedDocId = doc.doc_id;
    var requestedPlanId = plan.plan_id;
    var milestoneId = select.value;
    try {
      var data = await api("/api/quiz/history?doc_id=" + encodeURIComponent(requestedDocId) +
        "&plan_id=" + encodeURIComponent(requestedPlanId) +
        "&milestone_id=" + encodeURIComponent(milestoneId));
      if (!state.doc || state.doc.doc_id !== requestedDocId ||
          !state.plan || state.plan.plan_id !== requestedPlanId ||
          !select || select.value !== milestoneId) {
        return;
      }
      state.quiz = data.quiz || null;
      state.quizAnswers = {};
      if (state.quiz) {
        renderQuiz();
        if (data.result) renderQuizResult(data.result);
        $("quizStatus").textContent = data.result
          ? "已恢复上次测试，得分 " + Math.round(Number(data.result.score || 0) * 100) + "%"
          : "已恢复上次生成的测试";
      } else {
        $("quizQuestions").innerHTML = '<div class="learning-empty">该里程碑还没有测试，点击“生成测试”开始。</div>';
        $("submitQuizBtn").disabled = true;
        $("retryQuizBtn").hidden = true;
        $("quizResult").textContent = "";
        $("quizStatus").textContent = "等待生成测试";
      }
    } catch (error) {
      $("quizStatus").textContent = error.message;
    }
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
    var plan = state.plan;
    if (!doc || !plan) return;
    var requestedDocId = doc.doc_id;
    var requestedPlanId = plan.plan_id;
    try {
      var data = await api("/api/quiz/history?doc_id=" + encodeURIComponent(requestedDocId) +
        "&plan_id=" + encodeURIComponent(requestedPlanId));
      if (!state.doc || state.doc.doc_id !== requestedDocId ||
          !state.plan || state.plan.plan_id !== requestedPlanId) {
        return;
      }
      state.quizRecords = data.records || [];
      renderQuizHistory();
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
        var source = record.source === "fallback" ? "回退题" : "模型题";
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
          '<span>' + escapeHtml(record.milestone_title || record.milestone_id) + '</span>' +
          '<small>' + escapeHtml(source) + " · " + escapeHtml(score) + " · " + escapeHtml(date) +
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
    var plan = state.plan;
    if (!doc || !plan || !quizId) return;
    var requestedDocId = doc.doc_id;
    var requestedPlanId = plan.plan_id;
    try {
      var quiz = await api("/api/quiz/" + encodeURIComponent(quizId));
      if (!state.doc || state.doc.doc_id !== requestedDocId ||
          !state.plan || state.plan.plan_id !== requestedPlanId) return;
      var record = (state.quizRecords || []).filter(function (item) {
        return item.quiz_id === quizId;
      })[0];
      var select = $("quizMilestoneSelect");
      if (select && record && record.milestone_id) {
        var exists = Array.prototype.some.call(select.options, function (option) {
          return option.value === record.milestone_id;
        });
        if (exists) select.value = record.milestone_id;
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

  async function generateQuiz(milestoneId, auto, force) {
    var doc = currentDoc();
    if (!doc || !state.plan) { notify("请先创建学习计划。"); return; }
    var select = $("quizMilestoneSelect");
    if (milestoneId && select) {
      var exists = Array.prototype.some.call(select.options, function (option) {
        return option.value === milestoneId;
      });
      if (exists) select.value = milestoneId;
    }
    var milestone = milestoneId || (select ? select.value : "");
    if (!milestone) { notify("请选择里程碑。"); return; }
    var requestedDocId = doc.doc_id;
    var requestedPlanId = state.plan.plan_id;
    var button = $("generateQuizBtn");
    if (state.quizController) state.quizController.abort();
    var controller = new AbortController();
    state.quizController = controller;
    if (button) button.disabled = true;
    $("quizStatus").textContent = auto ? "已自动生成测试…" : "生成中…";
    try {
      var data = await api("/api/quiz", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          doc_id: requestedDocId,
          plan_id: requestedPlanId,
          milestone_id: milestone,
          question_count: Number($("quizCount").value || 5),
          difficulty: $("quizDifficulty").value,
          force: Boolean(force),
          api: apiConfig()
        })
      });
      if (controller.signal.aborted) return;
      if (!state.doc || state.doc.doc_id !== requestedDocId ||
          !state.plan || state.plan.plan_id !== requestedPlanId ||
          (select && select.options.length > 0 && select.value !== milestone)) {
        return;
      }
      state.quiz = data.quiz;
      state.quizAnswers = {};
      renderQuiz();
      if (state.quiz.source === "fallback") {
        $("quizStatus").textContent = "测试使用回退题（模型未返回有效题目）";
        notify("模型未返回有效题目，已使用回退题。" + (state.quiz.warnings && state.quiz.warnings[0] ? " " + state.quiz.warnings[0] : ""));
      } else {
        $("quizStatus").textContent = data.cached ? "已复用缓存测试" : (auto ? "测试已自动生成" : "测试已生成");
        if (auto) notify("完成里程碑，已自动生成测试。");
      }
      loadQuizHistory();
    } catch (error) {
      if (error.name !== "AbortError") {
        $("quizStatus").textContent = error.message;
        if (auto) notify("自动生成测试失败：" + error.message);
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
      return '<div class="quiz-question"><h4>' + (index + 1) + ". " + escapeHtml(question.question_text) +
        '</h4>' + options + '<div class="quiz-hint" data-hint="' + index + '">显示提示</div>' +
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

  function onDocChanged(event) {
    if (state.quizController) state.quizController.abort();
    state.quizController = null;
    if (state.chatController) state.chatController.abort();
    state.chatController = null;
    state.doc = event.detail && event.detail.doc;
    state.plans = [];
    state.plan = null;
    state.progress = null;
    state.quiz = null;
    state.quizRecords = [];
    state.quizAnswers = {};
    var historyBox = $("quizHistory");
    if (historyBox) historyBox.innerHTML = "";
    if (state.workspace === "plan") loadPlans();
    if (state.workspace === "quiz") loadQuizWorkspace();
    if (state.workspace === "chat") loadChat();
  }

  function bind() {
    var nav = $("workspaceSwitch");
    if (nav) {
      nav.addEventListener("click", function (event) {
        var button = event.target.closest("button[data-workspace]");
        if (button) switchWorkspace(button.dataset.workspace);
      });
    }
    if ($("createPlanBtn")) $("createPlanBtn").addEventListener("click", createPlan);
    if ($("generateQuizBtn")) $("generateQuizBtn").addEventListener("click", function () {
      // After the first quiz is visible, the primary button means "generate a new one".
      generateQuiz(null, false, Boolean(state.quiz));
    });
    if ($("submitQuizBtn")) $("submitQuizBtn").addEventListener("click", submitQuiz);
    if ($("retryQuizBtn")) $("retryQuizBtn").addEventListener("click", function () { generateQuiz(null, false, true); });
    if ($("quizMilestoneSelect")) {
      $("quizMilestoneSelect").addEventListener("change", function () {
        if (state.quizController) {
          state.quizController.abort();
          state.quizController = null;
        }
        try {
          var key = quizMilestoneKey();
          if (key) localStorage.setItem("ln_agent_quiz_milestone_v1:" + key, $("quizMilestoneSelect").value);
        } catch (ignored) { /* ignore */ }
        if (state.workspace === "quiz") loadQuizState();
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
  }

  function init() {
    bind();
    state.doc = window.NotesApp && window.NotesApp.getDoc ? window.NotesApp.getDoc() : null;
    var saved = null;
    try { saved = localStorage.getItem("ln_agent_workspace_v1"); } catch (ignored) { /* ignore */ }
    switchWorkspace(saved || "notes");
    registerFeature("stage3.chat", function () { /* chat handlers bound above */ });
    registerFeature("stage4.plan", function () { /* plan handlers bound above */ });
    registerFeature("stage5.quiz", function () { /* quiz handlers bound above */ });
  }

  init();
})();
