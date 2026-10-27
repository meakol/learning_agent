(function (global) {
  "use strict";

  const TAG_RE = /^\s*(?:\*\*|__)?\s*[\[【]\s*(核心|重点|了解|core|key|info|important|must[\s-]?know)\s*[\]】]\s*(?:\*\*|__)?\s*/i;
  const TAG_MAP = {
    "核心": "core", "重点": "key", "了解": "info",
    "core": "core", "key": "key", "info": "info",
    "important": "key", "mustknow": "key"
  };

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function renderMath(expression, displayMode) {
    const expr = String(expression == null ? "" : expression).trim();
    if (!expr) return "";
    if (global.katex && typeof global.katex.renderToString === "function") {
      try {
        return global.katex.renderToString(expr, {
          displayMode: Boolean(displayMode),
          throwOnError: false,
          strict: "ignore",
          trust: false
        });
      } catch (error) {
        return '<span class="math-error">' + escapeHtml(expr) + "</span>";
      }
    }
    return "<code>" + escapeHtml(expr) + "</code>";
  }

  function tagKey(raw) {
    return String(raw).toLowerCase().replace(/[\s-]/g, "");
  }

  function tagLabel(raw) {
    const key = tagKey(raw);
    if (["core", "key", "info"].indexOf(key) !== -1) {
      return key.charAt(0).toUpperCase() + key.slice(1);
    }
    if (key === "important") return "Key";
    if (key === "mustknow") return "Must-know";
    return raw;
  }

  function extractTag(content) {
    const match = TAG_RE.exec(content);
    if (!match) return { cls: "", label: "", text: content };
    return {
      cls: TAG_MAP[tagKey(match[1])] || "",
      label: match[1],
      text: content.slice(match[0].length)
    };
  }

  function inline(text) {
    let source = String(text == null ? "" : text);
    const codeStash = [];
    const mathStash = [];

    source = source.replace(/`([^`\n]+)`/g, function (_, code) {
      codeStash.push("<code>" + escapeHtml(code) + "</code>");
      return "\u0000" + (codeStash.length - 1) + "\u0000";
    });
    source = source.replace(/\$\$([\s\S]+?)\$\$/g, function (_, expression) {
      mathStash.push(renderMath(expression, true));
      return "\u0001" + (mathStash.length - 1) + "\u0001";
    });
    source = source.replace(/(^|[^\\])\$([^\n$]+?)\$(?!\$)/g, function (_, prefix, expression) {
      mathStash.push(renderMath(expression, false));
      return prefix + "\u0001" + (mathStash.length - 1) + "\u0001";
    });
    source = source.replace(/\\\(([\s\S]+?)\\\)/g, function (_, expression) {
      mathStash.push(renderMath(expression, false));
      return "\u0001" + (mathStash.length - 1) + "\u0001";
    });

    source = escapeHtml(source);
    source = source.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    source = source.replace(/__([^_\n]+)__/g, "<strong>$1</strong>");
    source = source.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
    source = source.replace(/~~([^~\n]+)~~/g, "<del>$1</del>");

    source = source.replace(
      /\[(?:p{1,2}\.)?\s*(\d+)(?:\s*[-–—~]\s*(\d+))?\]/gi,
      function (whole, start, end) {
        if (!/^\s*\[[pP]/.test(whole)) return whole;
        const label = end ? "p." + start + "–" + end : "p." + start;
        return (
          '<button type="button" class="src-ref" data-page="' + start +
          (end ? '" data-page-end="' + end : "") + '" title="定位到第 ' + start +
          ' 页">' + label + "</button>"
        );
      }
    );
    source = source.replace(/\[第\s*(\d+)\s*页\]/g, function (_, page) {
      return '<button type="button" class="src-ref" data-page="' + page +
        '" title="定位到第 ' + page + ' 页">p.' + page + "</button>";
    });
    source = source.replace(
      /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
    );
    source = source.replace(
      /[\[【]\s*(核心|重点|了解|Core|Key|Info|Important)\s*[\]】]/gi,
      function (_, raw) {
        const cls = TAG_MAP[tagKey(raw)] || "neutral";
        return '<span class="imp-tag ' + cls + '">' + tagLabel(raw) + "</span>";
      }
    );
    source = source.replace(/\u0001(\d+)\u0001/g, function (_, index) {
      return mathStash[Number(index)] || "";
    });
    source = source.replace(/\u0000(\d+)\u0000/g, function (_, index) {
      return codeStash[Number(index)] || "";
    });
    return source;
  }

  function renderParagraphText(text) {
    const normalized = String(text || "").replace(/\s+/g, " ").trim();
    if (!normalized) return "";
    if (normalized.length < 320) return "<p>" + inline(normalized) + "</p>";
    const parts = normalized
      .split(/(?<=[。！？；])|(?<=[.!?;])\s+/)
      .map(function (part) { return part.trim(); })
      .filter(Boolean);
    if (parts.length < 2) return "<p>" + inline(normalized) + "</p>";
    const groups = [];
    let current = [];
    parts.forEach(function (part) {
      current.push(part);
      const length = current.join(" ").length;
      if (current.length >= 2 || length >= 420) {
        groups.push(current.join(" "));
        current = [];
      }
    });
    if (current.length) groups.push(current.join(" "));
    return groups.map(function (group) {
      return "<p>" + inline(group) + "</p>";
    }).join("");
  }

  function stripFences(md) {
    let text = String(md || "").trim();
    const match = /^```(?:markdown|md)?\s*\n([\s\S]*?)\n```$/i.exec(text);
    if (match) text = match[1].trim();
    return text;
  }

  function isTableSeparator(line) {
    if (!line || line.indexOf("|") === -1) return false;
    const cells = line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|");
    return cells.length > 0 && cells.every(function (cell) {
      return /^\s*:?-{2,}:?\s*$/.test(cell);
    });
  }

  function splitRow(line) {
    return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(function (cell) {
      return cell.trim();
    });
  }

  function renderTable(lines, start) {
    const headers = splitRow(lines[start]);
    let index = start + 2;
    const rows = [];
    while (index < lines.length && lines[index].trim() && lines[index].indexOf("|") !== -1) {
      rows.push(splitRow(lines[index]));
      index += 1;
    }
    let html = "<table><thead><tr>";
    headers.forEach(function (cell) { html += "<th>" + inline(cell) + "</th>"; });
    html += "</tr></thead><tbody>";
    rows.forEach(function (row) {
      html += "<tr>";
      headers.forEach(function (_, col) {
        html += "<td>" + inline(row[col] == null ? "" : row[col]) + "</td>";
      });
      html += "</tr>";
    });
    html += "</tbody></table>";
    return { tableHtml: html, next: index };
  }

  function tablePlugin(title, tableHtml) {
    return (
      '<div class="table-plugin">' +
        '<div class="table-plugin-head">' +
          '<span class="table-kicker">TABLE</span>' +
          '<span class="table-title">' + (title ? inline(title) : "数据表") + "</span>" +
          '<button type="button" class="table-copy" title="复制表格为 TSV">复制</button>' +
        "</div>" +
        '<div class="table-scroll">' + tableHtml + "</div>" +
      "</div>"
    );
  }

  function renderTableBlock(lines, start, title) {
    const table = renderTable(lines, start);
    return { html: tablePlugin(title || "", table.tableHtml), next: table.next };
  }

  function parseStructuredItems(lines) {
    const items = [];
    lines.forEach(function (raw) {
      const match = /^(\s*)[-*+•·]\s+(.*)$/.exec(raw);
      if (!match) return;
      const indent = Math.min(3, Math.floor(match[1].replace(/\t/g, "  ").length / 2));
      const content = match[2];
      const english = /^(?:EN|En|en|English|英文)\s*[:：]\s*(.*)$/.exec(content);
      if (english && items.length) {
        items[items.length - 1].en.push(english[1]);
        return;
      }
      const tag = extractTag(content);
      items.push({ text: tag.text, cls: tag.cls, label: tag.label, en: [], level: indent });
    });
    return items;
  }

  function structuredBadge(item) {
    return item.cls
      ? '<span class="imp-tag ' + item.cls + '">' + escapeHtml(tagLabel(item.label)) + "</span>"
      : "";
  }

  function structuredEnglish(item) {
    return item.en.map(function (line) {
      return '<div class="en-line"><span class="en-label">EN</span><span>' +
        inline(line) + "</span></div>";
    }).join("");
  }

  function renderBranches(title, body) {
    const items = parseStructuredItems(body);
    if (!items.length) return "";
    const intro = body.filter(function (line) {
      return line.trim() && !/^\s*[-*+•·]\s+/.test(line);
    }).map(function (line) { return inline(line.trim()); }).join(" ");
    const branches = items.map(function (item) {
      return (
        '<div class="branch-item ' + (item.cls || "") + '" style="--branch-indent:' + item.level + '">' +
          '<span class="branch-dot"></span>' +
          '<div class="branch-text">' + structuredBadge(item) + inline(item.text) +
            structuredEnglish(item) + "</div>" +
        "</div>"
      );
    }).join("");
    return (
      '<div class="viz viz-branches">' +
        (title ? '<div class="viz-title">' + inline(title) + "</div>" : "") +
        (intro ? '<p class="viz-intro">' + intro + "</p>" : "") +
        '<div class="branch-body">' +
          '<svg class="branch-brace" viewBox="0 0 24 120" preserveAspectRatio="none" aria-hidden="true">' +
            '<path d="M19 4C10 4 12 45 4 60C12 75 10 116 19 116" fill="none" stroke="currentColor" ' +
            'stroke-width="2.6" stroke-linecap="round"/></svg>' +
          '<div class="branch-list">' + branches + "</div>" +
        "</div>" +
      "</div>"
    );
  }

  function parsePyramidRows(lines) {
    const rows = [];
    lines.forEach(function (raw) {
      const line = raw.trim();
      if (!line) return;
      let cells = null;
      if (line.indexOf("|") !== -1) {
        cells = line.replace(/^\|/, "").replace(/\|$/, "").split("|").map(function (cell) {
          return cell.trim();
        });
      } else {
        const item = /^[-*+•·]\s+(.*)$/.exec(line);
        if (!item) return;
        cells = [item[1], ""];
      }
      const label = cells[0] || "";
      const desc = cells[1] || "";
      let english = "";
      const rest = cells.slice(2).join(" · ").trim();
      if (/^EN\s*[:：]/i.test(rest)) {
        english = rest.replace(/^EN\s*[:：]\s*/i, "");
      }
      rows.push({ label: label, desc: desc, en: english });
    });
    return rows;
  }

  function renderPyramid(title, body) {
    const rows = parsePyramidRows(body);
    if (!rows.length) return "";
    const levels = rows.map(function (row, index) {
      const width = rows.length === 1 ? 84 : 56 + (index * 44 / (rows.length - 1));
      return (
        '<div class="pyramid-level" style="width:' + width.toFixed(1) + "%;--level:" + index + '">' +
          '<div class="pyramid-label">' + inline(row.label) + "</div>" +
          (row.desc ? '<div class="pyramid-desc">' + inline(row.desc) + "</div>" : "") +
          (row.en ? '<div class="en-line"><span class="en-label">EN</span><span>' + inline(row.en) + "</span></div>" : "") +
        "</div>"
      );
    }).join("");
    return (
      '<div class="viz viz-pyramid">' +
        (title ? '<div class="viz-title">' + inline(title) + "</div>" : "") +
        '<div class="pyramid-stack">' + levels + "</div>" +
      "</div>"
    );
  }

  function renderMindmap(title, body) {
    const items = parseStructuredItems(body);
    if (!items.length) return "";
    const groups = [];
    items.forEach(function (item) {
      if (item.level === 0 || !groups.length) {
        groups.push({ item: item, children: [] });
      } else {
        groups[groups.length - 1].children.push(item);
      }
    });
    let root = title;
    if (!root && groups.length > 1) {
      root = groups.shift().item.text;
    }
    const branches = groups.map(function (group) {
      const children = group.children.map(function (child) {
        return '<span class="mindmap-child">' + structuredBadge(child) + inline(child.text) +
          structuredEnglish(child) + "</span>";
      }).join("");
      return (
        '<div class="mindmap-branch">' +
          '<div class="mindmap-node ' + (group.item.cls || "") + '">' +
            structuredBadge(group.item) + inline(group.item.text) + structuredEnglish(group.item) +
          "</div>" +
          (children ? '<div class="mindmap-children">' + children + "</div>" : "") +
        "</div>"
      );
    }).join("");
    return (
      '<div class="viz viz-mindmap">' +
        '<div class="mindmap-root"><span>' + inline(root || "核心主题") + "</span></div>" +
        '<div class="mindmap-branches">' + branches + "</div>" +
      "</div>"
    );
  }

  function renderDirective(type, title, body) {
    if (type === "branches") return renderBranches(title, body);
    if (type === "pyramid") return renderPyramid(title, body);
    if (type === "mindmap") return renderMindmap(title, body);
    if (type === "table") {
      let start = -1;
      for (let i = 0; i < body.length - 1; i += 1) {
        if (body[i].indexOf("|") !== -1 && isTableSeparator(body[i + 1])) {
          start = i;
          break;
        }
      }
      if (start === -1) return "";
      const intro = body.slice(0, start).filter(function (line) { return line.trim(); })
        .map(function (line) { return inline(line.trim()); }).join("<br>");
      const table = renderTableBlock(body, start, title);
      return (intro ? "<p>" + intro + "</p>" : "") + table.html;
    }
    const lines = body.filter(function (line) { return line.trim(); });
    if (!lines.length) return "";
    return '<div class="viz viz-fallback">' + lines.map(function (line) {
      return "<p>" + inline(line.trim()) + "</p>";
    }).join("") + "</div>";
  }

  function renderHeading(level, text) {
    const tag = extractTag(text);
    const badge = tag.cls
      ? '<span class="imp-tag ' + tag.cls + '">' + escapeHtml(tagLabel(tag.label)) + "</span>"
      : "";
    return "<h" + level + ">" + badge + inline(tag.text) + "</h" + level + ">";
  }

  function renderList(list) {
    const html = list.items.map(function (item) {
      const badge = item.cls
        ? '<span class="imp-tag ' + item.cls + '">' + escapeHtml(tagLabel(item.label)) + "</span>"
        : "";
      const marker = item.marker
        ? '<span class="ord-marker">' + escapeHtml(item.marker) + "</span>"
        : "";
      const english = item.en.length
        ? item.en.map(function (line) {
            return '<div class="en-line"><span class="en-label">EN</span><span>' +
              inline(line) + "</span></div>";
          }).join("")
        : "";
      return (
        '<li class="note-item ' + (item.cls || "") + '" style="--indent:' + item.indent + '">' +
        badge + '<div class="note-text">' + marker + inline(item.text) + english + "</div></li>"
      );
    }).join("");
    return '<ul class="note-list">' + html + "</ul>";
  }

  function render(markdown) {
    const text = stripFences(markdown);
    const lines = text.replace(/\r\n?/g, "\n").split("\n");
    let html = "";
    let paragraph = [];
    let list = null;
    let index = 0;

    function flushParagraph() {
      if (!paragraph.length) return;
      const joined = paragraph.join(" ").trim();
      if (joined) html += renderParagraphText(joined);
      paragraph = [];
    }
    function flushList() {
      if (list) html += renderList(list);
      list = null;
    }

    while (index < lines.length) {
      const raw = lines[index];
      const line = raw.replace(/\s+$/, "");

      if (/^\s*```/.test(line)) {
        flushParagraph();
        flushList();
        const code = [];
        index += 1;
        while (index < lines.length && !/^\s*```/.test(lines[index])) {
          code.push(lines[index]);
          index += 1;
        }
        index += 1;
        html += "<pre><code>" + escapeHtml(code.join("\n")) + "</code></pre>";
        continue;
      }

      const directive = /^\s*:::\s*([a-zA-Z][\w-]*)\s*(.*)$/.exec(line);
      if (directive) {
        let close = index + 1;
        while (close < lines.length && !/^\s*:::\s*$/.test(lines[close])) {
          close += 1;
        }
        if (close < lines.length) {
          flushParagraph();
          flushList();
          const type = directive[1].toLowerCase();
          const title = directive[2].trim();
          const body = lines.slice(index + 1, close);
          index = close + 1;
          html += renderDirective(type, title, body);
          continue;
        }
      }

      if (!line.trim()) {
        flushParagraph();
        flushList();
        index += 1;
        continue;
      }

      const visual = /^\s*\[\[VISUAL\s+p\.?\s*(\d+)(?:\s+caption\s*=\s*"([^"]*)")?\s*\]\]\s*$/i.exec(line);
      if (visual) {
        flushParagraph();
        flushList();
        html += '<figure class="note-figure visual-slot" data-page="' + Number(visual[1]) +
          '" data-caption="' + escapeHtml(visual[2] || "") + '"></figure>';
        index += 1;
        continue;
      }

      const mathOpen = /^\s*(\$\$|\\\[)/.exec(line);
      if (mathOpen) {
        flushParagraph();
        flushList();
        const open = mathOpen[1];
        const close = open === "$$" ? "$$" : "\\]";
        let rest = line.trim().slice(open.length);
        let expression = "";
        index += 1;
        if (rest.length >= close.length && rest.slice(-close.length) === close) {
          expression = rest.slice(0, -close.length);
        } else {
          expression = rest;
          while (index < lines.length) {
            const current = lines[index];
            const position = current.indexOf(close);
            if (position !== -1) {
              expression += "\n" + current.slice(0, position);
              index += 1;
              break;
            }
            expression += "\n" + current;
            index += 1;
          }
        }
        html += '<div class="math-block">' + renderMath(expression, true) + "</div>";
        continue;
      }

      if (/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
        flushParagraph();
        flushList();
        html += "<hr>";
        index += 1;
        continue;
      }

      let match = /^(#{1,4})\s+(.*)$/.exec(line);
      if (match) {
        flushParagraph();
        flushList();
        html += renderHeading(match[1].length, match[2]);
        index += 1;
        continue;
      }

      if (line.indexOf("|") !== -1 && isTableSeparator(lines[index + 1])) {
        flushParagraph();
        flushList();
        const table = renderTableBlock(lines, index, "");
        html += table.html;
        index = table.next;
        continue;
      }

      if (/^\s*>/.test(line)) {
        flushParagraph();
        flushList();
        const quote = [];
        while (index < lines.length && /^\s*>/.test(lines[index])) {
          quote.push(lines[index].replace(/^\s*>\s?/, ""));
          index += 1;
        }
        html += "<blockquote>" + quote.map(inline).join("<br>") + "</blockquote>";
        continue;
      }

      match = /^(\s*)([-*+•·])\s+(.*)$/.exec(raw);
      let ordered = false;
      if (!match) {
        match = /^(\s*)(\d+)[.)、]\s+(.*)$/.exec(raw);
        if (match) ordered = true;
      }
      if (match) {
        flushParagraph();
        if (!list) list = { items: [], ordered: ordered };
        const indent = Math.min(4, Math.floor(match[1].replace(/\t/g, "  ").length / 2));
        let content = match[3];
        const english = /^(?:EN|En|en|English|英文)\s*[:：]\s*/.exec(content);
        if (english && list.items.length) {
          list.items[list.items.length - 1].en.push(content.slice(english[0].length));
        } else {
          const tag = extractTag(content);
          list.items.push({
            cls: tag.cls,
            label: tag.label,
            text: tag.text,
            indent: indent,
            en: [],
            marker: ordered ? match[2] + "." : ""
          });
        }
        index += 1;
        continue;
      }

      flushList();
      paragraph.push(line.trim());
      index += 1;
    }

    flushParagraph();
    flushList();
    return html || '<p class="markdown-placeholder">正在等待内容…</p>';
  }

  function stats(markdown) {
    const counts = { core: 0, key: 0, info: 0 };
    const regex = /[\[【]\s*(核心|重点|了解|core|key|info|important|must[\s-]?know)\s*[\]】]/gi;
    let match;
    while ((match = regex.exec(String(markdown || ""))) !== null) {
      const cls = TAG_MAP[tagKey(match[1])];
      if (cls) counts[cls] += 1;
    }
    return counts;
  }

  var SECTION_PAGE_RE = /\[p{1,2}\.?\s*(\d+)(?:\s*[-–—~]\s*(\d+))?\]|\[第\s*(\d+)\s*页\]/gi;
  var SECTION_TAG_RE = /\[p{1,2}\.?\s*\d+(?:\s*[-–—~]\s*\d+)?\]|\[第\s*\d+\s*页\]/gi;
  var ADMIN_TITLE_RE = /课程(安排|计划|大纲|进度|信息|须知)|教学(安排|计划|大纲)|考核方式|评分标准|成绩构成|考试安排|考试时间|参考(书|文献)|推荐阅读|联系方式|答疑时间|课程目标|作业要求|attendance|grading policy|course (schedule|outline|logistics|description)|syllabus/i;

  function pagesInText(text) {
    var pages = [];
    var source = String(text || "");
    var match;
    SECTION_PAGE_RE.lastIndex = 0;
    while ((match = SECTION_PAGE_RE.exec(source)) !== null) {
      var start = parseInt(match[3] || match[1], 10);
      if (!start) continue;
      var end = match[3] ? start : (match[2] ? parseInt(match[2], 10) : start);
      var low = Math.min(start, end);
      var high = Math.min(Math.max(start, end), low + 40);
      for (var page = low; page <= high; page += 1) pages.push(page);
    }
    return pages;
  }

  function sections(markdown) {
    var text = String(markdown || "").replace(/\r\n?/g, "\n");
    var lines = text.split("\n");
    var level2 = [];
    var level3 = [];
    var current2 = null;
    var current3 = null;
    var fence = false;

    lines.forEach(function (line) {
      var trimmed = line.trim();
      if (trimmed.indexOf("```") === 0) {
        fence = !fence;
        return;
      }
      if (fence) return;
      var heading = /^(#{2,4})\s+(.+)$/.exec(trimmed);
      if (heading) {
        var level = heading[1].length;
        var title = heading[2].replace(SECTION_TAG_RE, "").trim();
        var item = { title: title, level: level, pages: pagesInText(heading[2]), text: "" };
        if (level === 2) {
          item.domIndex = level2.length;
          level2.push(item);
          current2 = item;
          current3 = null;
        } else if (level === 3) {
          item.domIndex = level3.length;
          level3.push(item);
          current3 = item;
          if (current2) current2.pages = current2.pages.concat(item.pages);
        } else {
          current3 = item;
        }
        return;
      }
      if (current3) {
        current3.text += line + "\n";
        current3.pages = current3.pages.concat(pagesInText(line));
      }
      if (current2) {
        current2.text += line + "\n";
        current2.pages = current2.pages.concat(pagesInText(line));
      }
    });

    var picked = level2.length ? level2 : level3;
    var seen = {};
    var result = [];
    var lastPage = 0;
    picked.forEach(function (item, index) {
      var title = String(item.title || "").trim();
      if (!title || ADMIN_TITLE_RE.test(title)) return;
      var pages = [];
      var seenPage = {};
      item.pages.forEach(function (page) {
        if (typeof page === "number" && !seenPage[page]) {
          seenPage[page] = true;
          pages.push(page);
        }
      });
      pages.sort(function (a, b) { return a - b; });
      if (!pages.length) pages = [lastPage || 1];
      lastPage = pages[pages.length - 1];
      var key = title + "|" + pages.join(",");
      if (seen[key]) return;
      seen[key] = true;
      result.push({
        index: index,
        domIndex: typeof item.domIndex === "number" ? item.domIndex : index,
        title: title,
        level: item.level,
        pages: pages,
        text: String(item.text || "").trim()
      });
    });
    return result;
  }

  global.NotesMarkdown = {
    render: render,
    stats: stats,
    sections: sections,
    escapeHtml: escapeHtml
  };
})(window);
