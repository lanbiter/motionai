(function () {
  "use strict";

  function apiPrefix() {
    var p = window.MPT_API_PREFIX;
    if (!p) {
      var loc = window.location;
      return loc.origin.replace(/\/+$/, "") + "/api/v1";
    }
    return p.replace(/\/+$/, "");
  }

  function showAlert(container, message, kind) {
    if (!container) return;
    var div = document.createElement("div");
    div.className = kind === "info" ? "mpt-alert mpt-alert-info" : "mpt-alert";
    div.textContent = message;
    container.appendChild(div);
    setTimeout(function () {
      try {
        container.removeChild(div);
      } catch (e) {}
    }, 8000);
  }

  function mptEscapeAttr(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;")
      .replace(/</g, "&lt;");
  }

  function mptEscapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function mptVideoLinksHtml(urls) {
    var list = urls || [];
    return list
      .map(function (u, i) {
        var label = list.length > 1 ? "成片-" + (i + 1) : "打开成片";
        return (
          '<a href="' +
          mptEscapeAttr(u) +
          '" target="_blank" rel="noopener">' +
          label +
          "</a>"
        );
      })
      .join(" ");
  }

  function mptShortTaskId(id) {
    var s = String(id || "");
    if (!s) return "";
    if (s.length <= 8) return s;
    return s.slice(0, 8) + "…";
  }

  function mptFormatYmd(value) {
    var s = String(value || "");
    if (!s) return "—";
    var m = s.match(/^(\d{4}-\d{2}-\d{2})/);
    if (m) return m[1];
    var d = new Date(s);
    if (isNaN(d.getTime())) return s;
    var y = d.getFullYear();
    var mm = String(d.getMonth() + 1).padStart(2, "0");
    var dd = String(d.getDate()).padStart(2, "0");
    return y + "-" + mm + "-" + dd;
  }

  function val(id) {
    var el = document.getElementById(id);
    return el ? String(el.value || "") : "";
  }

  function num(id, def) {
    var v = parseFloat(val(id));
    return isNaN(v) ? def : v;
  }

  function int(id, def) {
    var v = parseInt(val(id), 10);
    return isNaN(v) ? def : v;
  }

  function checked(id) {
    var el = document.getElementById(id);
    return el ? !!el.checked : false;
  }

  /* ---------- 视频生成页 ---------- */
  var btnSubmit = document.getElementById("mpt-btn-submit-video");
  if (btnSubmit) {
    var alerts = document.getElementById("mpt-video-alerts");
    var statusEl = document.getElementById("mpt-job-status");
    var resultCard = document.getElementById("mpt-video-result");
    var resultBody = document.getElementById("mpt-video-result-body");
    var logsCard = document.getElementById("mpt-video-logs");
    var logsBody = document.getElementById("mpt-video-logs-body");

    function buildPayload(materials) {
      var trans = val("mpt-video-transition");
      return {
        video_subject: val("mpt-video-subject").trim(),
        video_script: val("mpt-video-script"),
        video_terms: val("mpt-video-terms"),
        video_language: val("mpt-video-language"),
        video_source: val("mpt-video-source"),
        video_concat_mode: val("mpt-video-concat"),
        video_transition_mode: trans.length ? trans : null,
        video_aspect: val("mpt-video-aspect"),
        video_clip_duration: int("mpt-clip-duration", 5),
        video_count: int("mpt-video-count", 1),
        voice_name: val("mpt-voice-name"),
        voice_volume: num("mpt-voice-volume", 1),
        voice_rate: num("mpt-voice-rate", 1),
        bgm_type: val("mpt-bgm-type"),
        bgm_file: val("mpt-bgm-file") || "",
        bgm_volume: num("mpt-bgm-volume", 0.2),
        subtitle_enabled: checked("mpt-subtitle-enabled"),
        subtitle_position: val("mpt-subtitle-position"),
        custom_position: num("mpt-custom-position", 70),
        font_name: val("mpt-font-name"),
        text_fore_color: val("mpt-text-fore-color"),
        font_size: int("mpt-font-size", 60),
        stroke_color: val("mpt-stroke-color"),
        stroke_width: num("mpt-stroke-width", 1.5),
        n_threads: int("mpt-n-threads", 2),
        paragraph_number: int("mpt-paragraph-number", 1),
        text_background_color: true,
        video_materials: materials != null ? materials : null,
      };
    }

    function uploadMaterials(files) {
      var base = apiPrefix();
      var chain = Promise.resolve([]);
      Array.prototype.forEach.call(files, function (file) {
        chain = chain.then(function (acc) {
          var fd = new FormData();
          fd.append("file", file);
          return fetch(base + "/video_materials", { method: "POST", body: fd }).then(function (r) {
            return r.json();
          }).then(function (j) {
            if (j.status !== 200) throw new Error(j.message || "上传失败");
            acc.push({ provider: "local", url: j.data.file, duration: 0 });
            return acc;
          });
        });
      });
      return chain;
    }

    function renderTaskLogs(taskData) {
      if (!logsCard || !logsBody) return;
      var logs = taskData && Array.isArray(taskData.logs) ? taskData.logs : [];
      logsCard.style.display = "block";
      logsBody.textContent = logs.length ? logs.join("\\n") : "暂无日志，任务处理中...";
      logsBody.scrollTop = logsBody.scrollHeight;
    }

    function pollTask(taskId, onTick) {
      var base = apiPrefix();
      return new Promise(function (resolve, reject) {
        function step() {
          fetch(base + "/tasks/" + encodeURIComponent(taskId))
            .then(function (r) {
              return r.json();
            })
            .then(function (j) {
              if (j.status !== 200) throw new Error(j.message || "查询失败");
              var d = j.data;
              var st = d.state;
              var prog = d.progress != null ? d.progress : 0;
              if (onTick) onTick(d);
              if (statusEl) statusEl.textContent = "任务 " + taskId.slice(0, 8) + "… 进度 " + prog + "%";
              if (st === 1) resolve(d);
              else if (st === -1) reject(new Error("任务失败"));
              else setTimeout(step, 1500);
            })
            .catch(reject);
        }
        step();
      });
    }

    document.getElementById("mpt-btn-script").addEventListener("click", function () {
      var base = apiPrefix();
      var subject = val("mpt-video-subject").trim();
      if (!subject) {
        showAlert(alerts, "请先填写视频主题", "err");
        return;
      }
      var body = {
        video_subject: subject,
        video_language: val("mpt-video-language"),
        paragraph_number: int("mpt-paragraph-number", 1),
      };
      if (statusEl) statusEl.textContent = "正在生成文案…";
      fetch(base + "/scripts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
        .then(function (r) {
          return r.json();
        })
        .then(function (j) {
          if (j.status !== 200) throw new Error(j.message || "生成失败");
          var script = j.data.video_script;
          if (typeof script === "string" && script.indexOf("Error: ") === 0) throw new Error(script);
          document.getElementById("mpt-video-script").value = script;
          return fetch(base + "/terms", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              video_subject: subject,
              video_script: script,
              amount: 5,
            }),
          });
        })
        .then(function (r) {
          return r.json();
        })
        .then(function (j) {
          if (j.status !== 200) throw new Error(j.message || "关键词失败");
          var terms = j.data.video_terms;
          if (typeof terms === "string" && terms.indexOf("Error: ") === 0) throw new Error(terms);
          var line = Array.isArray(terms) ? terms.join(", ") : String(terms || "");
          document.getElementById("mpt-video-terms").value = line;
          if (statusEl) statusEl.textContent = "文案与关键词已更新";
          showAlert(alerts, "已写入文案与关键词", "info");
        })
        .catch(function (e) {
          if (statusEl) statusEl.textContent = "";
          showAlert(alerts, e.message || String(e), "err");
        });
    });

    document.getElementById("mpt-btn-terms").addEventListener("click", function () {
      var base = apiPrefix();
      var subject = val("mpt-video-subject").trim();
      var script = val("mpt-video-script");
      if (!script) {
        showAlert(alerts, "请先填写视频文案", "err");
        return;
      }
      if (statusEl) statusEl.textContent = "正在生成关键词…";
      fetch(base + "/terms", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          video_subject: subject,
          video_script: script,
          amount: 5,
        }),
      })
        .then(function (r) {
          return r.json();
        })
        .then(function (j) {
          if (j.status !== 200) throw new Error(j.message || "生成失败");
          var terms = j.data.video_terms;
          if (typeof terms === "string" && terms.indexOf("Error: ") === 0) throw new Error(terms);
          document.getElementById("mpt-video-terms").value = Array.isArray(terms) ? terms.join(", ") : String(terms || "");
          if (statusEl) statusEl.textContent = "关键词已更新";
        })
        .catch(function (e) {
          if (statusEl) statusEl.textContent = "";
          showAlert(alerts, e.message || String(e), "err");
        });
    });

    btnSubmit.addEventListener("click", function () {
      var subject = val("mpt-video-subject").trim();
      var script = val("mpt-video-script").trim();
      if (!subject && !script) {
        showAlert(alerts, "主题与文案不能同时为空", "err");
        return;
      }
      var source = val("mpt-video-source");
      if (source !== "pexels" && source !== "pixabay" && source !== "local") {
        showAlert(alerts, "当前页面仅支持 Pexels / Pixabay / 本地 三种素材来源", "err");
        return;
      }

      var filesInput = document.getElementById("mpt-local-files");
      var files = filesInput && filesInput.files ? filesInput.files : null;
      if (logsCard) logsCard.style.display = "none";
      if (logsBody) logsBody.textContent = "";
      resultCard.style.display = "none";
      resultBody.innerHTML = "";

      Promise.resolve()
        .then(function () {
          if (source === "local" && files && files.length) {
            if (statusEl) statusEl.textContent = "正在上传本地素材…";
            return uploadMaterials(files);
          }
          if (source === "local" && (!files || !files.length)) {
            throw new Error("本地来源时请上传至少一个素材文件");
          }
          return null;
        })
        .then(function (materials) {
          var payload = buildPayload(materials);
          if (statusEl) statusEl.textContent = "正在创建任务…";
          return fetch(apiPrefix() + "/videos", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          }).then(function (r) {
            return r.json();
          });
        })
        .then(function (j) {
          if (j.status !== 200) throw new Error(j.message || "创建任务失败");
          var taskId = j.data && j.data.task_id;
          if (!taskId) throw new Error("响应缺少 task_id");
          if (statusEl) statusEl.textContent = "任务创建成功，正在跳转任务列表…";
          window.location.href = "/admin/tasks";
        })
        .catch(function (e) {
          if (statusEl) statusEl.textContent = "";
          showAlert(alerts, e.message || String(e), "err");
        });
    });
  }

  /* ---------- 任务列表页 ---------- */
  var tbody = document.getElementById("mpt-task-rows");
  if (tbody) {
    var page = 1;
    var pageSize = 10;
    var total = 0;
    var meta = document.getElementById("mpt-tasks-meta");
    var pageLabel = document.getElementById("mpt-tasks-page");
    var base = apiPrefix();
    var taskLogMap = {};
    var logModal = document.getElementById("mpt-task-log-modal");
    var logContent = document.getElementById("mpt-task-log-content");
    var logTitle = document.getElementById("mpt-task-log-title");
    var logClose = document.getElementById("mpt-task-log-close");
    var tFilterSubject = document.getElementById("mpt-tasks-filter-subject");
    var tFilterState = document.getElementById("mpt-tasks-filter-state");
    var tFilterFrom = document.getElementById("mpt-tasks-filter-created-from");
    var tFilterTo = document.getElementById("mpt-tasks-filter-created-to");
    var tFilterApply = document.getElementById("mpt-tasks-filter-apply");
    var tFilterReset = document.getElementById("mpt-tasks-filter-reset");

    function toIsoFromLocal(dtLocal) {
      if (!dtLocal) return "";
      var d = new Date(dtLocal);
      if (isNaN(d.getTime())) return "";
      return d.toISOString();
    }

    function openTaskLogModal(taskId, logs) {
      if (!logModal || !logContent) return;
      var title = "任务日志";
      if (taskId) title += "（" + mptShortTaskId(taskId) + "）";
      if (logTitle) logTitle.textContent = title;
      logContent.textContent =
        Array.isArray(logs) && logs.length
          ? logs.join("\n")
          : "暂无日志";
      logModal.style.display = "flex";
    }

    function closeTaskLogModal() {
      if (!logModal) return;
      logModal.style.display = "none";
    }

    if (logClose) {
      logClose.addEventListener("click", closeTaskLogModal);
    }
    if (logModal) {
      logModal.addEventListener("click", function (evt) {
        if (evt.target && evt.target.classList && evt.target.classList.contains("mpt-task-log-modal-mask")) {
          closeTaskLogModal();
        }
      });
    }

    function stateLabel(s) {
      if (s === 1) return "完成";
      if (s === -1) return "失败";
      if (s === 4) return "进行中";
      return String(s);
    }

    function load() {
      var qs = new URLSearchParams();
      qs.set("page", String(page));
      qs.set("page_size", String(pageSize));
      var subject = tFilterSubject ? tFilterSubject.value.trim() : "";
      var state = tFilterState ? tFilterState.value : "";
      var createdFrom = tFilterFrom ? toIsoFromLocal(tFilterFrom.value) : "";
      var createdTo = tFilterTo ? toIsoFromLocal(tFilterTo.value) : "";
      if (subject) qs.set("video_subject", subject);
      if (state) qs.set("state", state);
      if (createdFrom) qs.set("created_from", createdFrom);
      if (createdTo) qs.set("created_to", createdTo);

      fetch(base + "/tasks?" + qs.toString())
        .then(function (r) {
          return r.json();
        })
        .then(function (j) {
          if (j.status !== 200) throw new Error(j.message || "加载失败");
          var d = j.data;
          total = d.total || 0;
          var tasks = d.tasks || [];
          if (meta) meta.textContent = "共 " + total + " 条";
          if (pageLabel) pageLabel.textContent = "第 " + (d.page || page) + " 页 / 每页 " + (d.page_size || pageSize);
          tbody.innerHTML = "";
          taskLogMap = {};
          tasks.forEach(function (t) {
            var tr = document.createElement("tr");
            var id = t.task_id || "";
            var idCellHtml =
              '<span title="' +
              mptEscapeAttr(id) +
              '" class="mpt-cell-ellipsis">' +
              mptEscapeHtml(mptShortTaskId(id)) +
              "</span>";
            var createdAt = mptFormatYmd(t.created_at || "");
            var links = mptVideoLinksHtml(t.videos);
            var subject = t.video_subject || "—";
            var subjectCellHtml =
              '<span title="' +
              mptEscapeAttr(subject) +
              '" class="mpt-cell-ellipsis">' +
              mptEscapeHtml(subject) +
              "</span>";
            var logs = Array.isArray(t.logs) ? t.logs : [];
            taskLogMap[id] = logs;
            var logAction =
              '<button type="button" class="ant-btn mpt-task-log" data-task-id="' +
              mptEscapeAttr(id) +
              '">查看日志</button>';
            var actionHtml =
              '<div style="display:flex;gap:8px;flex-wrap:wrap;">' +
              '<button type="button" class="ant-btn mpt-task-retry" data-task-id="' +
              mptEscapeAttr(id) +
              '">重试</button>' +
              '<span class="mpt-delete-wrap">' +
              '<button type="button" class="ant-btn mpt-task-delete mpt-btn-delete" data-task-id="' +
              mptEscapeAttr(id) +
              '">删除</button>' +
              '<span class="mpt-delete-popconfirm" style="display:none;">' +
              '<span class="mpt-delete-popconfirm-title">确认删除该任务？</span>' +
              '<span class="mpt-delete-popconfirm-actions">' +
              '<button type="button" class="ant-btn mpt-task-delete-cancel">取消</button>' +
              '<button type="button" class="ant-btn ant-btn-primary mpt-task-delete-confirm" data-task-id="' +
              mptEscapeAttr(id) +
              '">确定</button>' +
              "</span>" +
              "</span>" +
              "</span>" +
              "</div>";
            tr.innerHTML =
              "<td>" +
              idCellHtml +
              "</td><td>" +
              subjectCellHtml +
              "</td><td>" +
              stateLabel(t.state) +
              "</td><td>" +
              (t.progress != null ? t.progress : "") +
              "</td><td>" +
              (links || "—") +
              "</td><td>" +
              logAction +
              "</td><td>" +
              mptEscapeHtml(createdAt) +
              "</td><td>" +
              actionHtml +
              "</td>";
            tbody.appendChild(tr);
          });
        })
        .catch(function (e) {
          if (meta) meta.textContent = e.message || String(e);
        });
    }

    tbody.addEventListener("click", function (evt) {
      var target = evt.target;
      if (!(target instanceof HTMLElement)) return;

      function hideAllDeletePopconfirm() {
        var allPops = tbody.querySelectorAll(".mpt-delete-popconfirm");
        allPops.forEach(function (el) {
          el.style.display = "none";
        });
      }

      if (target.classList.contains("mpt-task-log")) {
        var logTaskId = target.getAttribute("data-task-id");
        if (!logTaskId) return;
        openTaskLogModal(logTaskId, taskLogMap[logTaskId] || []);
        return;
      }

      if (target.classList.contains("mpt-task-delete")) {
        var wrap = target.closest(".mpt-delete-wrap");
        if (!wrap) return;
        var pop = wrap.querySelector(".mpt-delete-popconfirm");
        if (!pop) return;
        var isVisible = pop.style.display !== "none";
        hideAllDeletePopconfirm();
        pop.style.display = isVisible ? "none" : "flex";
        return;
      }

      if (target.classList.contains("mpt-task-delete-cancel")) {
        var cancelWrap = target.closest(".mpt-delete-wrap");
        if (!cancelWrap) return;
        var cancelPop = cancelWrap.querySelector(".mpt-delete-popconfirm");
        if (cancelPop) cancelPop.style.display = "none";
        return;
      }

      if (target.classList.contains("mpt-task-retry")) {
        var retryTaskId = target.getAttribute("data-task-id");
        if (!retryTaskId) return;
        target.disabled = true;
        fetch(base + "/tasks/" + encodeURIComponent(retryTaskId) + "/retry", {
          method: "POST",
        })
          .then(function (r) {
            return r.json();
          })
          .then(function (j) {
            if (j.status !== 200) throw new Error(j.message || "重试失败");
            load();
          })
          .catch(function (e) {
            if (meta) meta.textContent = e.message || String(e);
          })
          .finally(function () {
            target.disabled = false;
          });
        return;
      }

      if (target.classList.contains("mpt-task-delete-confirm")) {
        var deleteTaskId = target.getAttribute("data-task-id");
        if (!deleteTaskId) return;
        target.disabled = true;
        fetch(base + "/tasks/" + encodeURIComponent(deleteTaskId), {
          method: "DELETE",
        })
          .then(function (r) {
            return r.json();
          })
          .then(function (j) {
            if (j.status !== 200) throw new Error(j.message || "删除失败");
            hideAllDeletePopconfirm();
            load();
          })
          .catch(function (e) {
            if (meta) meta.textContent = e.message || String(e);
          })
          .finally(function () {
            target.disabled = false;
          });
      }
    });

    document.addEventListener("click", function (evt) {
      if (!(evt.target instanceof HTMLElement)) return;
      if (evt.target.closest("#mpt-task-rows .mpt-delete-wrap")) return;
      var allPops = document.querySelectorAll("#mpt-task-rows .mpt-delete-popconfirm");
      allPops.forEach(function (el) {
        el.style.display = "none";
      });
    });

    document.getElementById("mpt-tasks-refresh").addEventListener("click", function () {
      load();
    });
    if (tFilterApply) {
      tFilterApply.addEventListener("click", function () {
        page = 1;
        load();
      });
    }
    if (tFilterReset) {
      tFilterReset.addEventListener("click", function () {
        if (tFilterSubject) tFilterSubject.value = "";
        if (tFilterState) tFilterState.value = "";
        if (tFilterFrom) tFilterFrom.value = "";
        if (tFilterTo) tFilterTo.value = "";
        page = 1;
        load();
      });
    }
    document.getElementById("mpt-tasks-prev").addEventListener("click", function () {
      if (page > 1) {
        page--;
        load();
      }
    });
    document.getElementById("mpt-tasks-next").addEventListener("click", function () {
      if (page * pageSize < total) {
        page++;
        load();
      }
    });
    load();
  }

  /* ---------- 视频列表页（SQLite 已生成成片） ---------- */
  var vCards = document.getElementById("mpt-videos-cards");
  if (vCards) {
    var vPage = 1;
    var vPageSize = 10;
    var vTotal = 0;
    var vMeta = document.getElementById("mpt-videos-meta");
    var vPageLabel = document.getElementById("mpt-videos-page");
    var vEmpty = document.getElementById("mpt-videos-empty");
    var vFilterSubject = document.getElementById("mpt-videos-filter-subject");
    var vFilterState = document.getElementById("mpt-videos-filter-state");
    var vFilterFrom = document.getElementById("mpt-videos-filter-created-from");
    var vFilterTo = document.getElementById("mpt-videos-filter-created-to");
    var vFilterApply = document.getElementById("mpt-videos-filter-apply");
    var vFilterReset = document.getElementById("mpt-videos-filter-reset");
    var vAppliedFilters = {
      subject: "",
      state: "",
      createdFrom: "",
      createdTo: "",
    };

    // 默认展示全部：首次进入先清空输入框，避免浏览器自动回填导致被筛选。
    if (vFilterSubject) vFilterSubject.value = "";
    if (vFilterState) vFilterState.value = "";
    if (vFilterFrom) vFilterFrom.value = "";
    if (vFilterTo) vFilterTo.value = "";

    function loadVideos() {
      var base = apiPrefix();
      var qs = new URLSearchParams();
      qs.set("page", String(vPage));
      qs.set("page_size", String(vPageSize));
      var subject = vAppliedFilters.subject;
      var state = vAppliedFilters.state;
      var createdFrom = vAppliedFilters.createdFrom;
      var createdTo = vAppliedFilters.createdTo;
      if (subject) qs.set("video_subject", subject);
      if (state) qs.set("state", state);
      if (createdFrom) qs.set("created_from", createdFrom);
      if (createdTo) qs.set("created_to", createdTo);
      fetch(base + "/video_generations?" + qs.toString())
        .then(function (r) {
          return r.json();
        })
        .then(function (j) {
          if (j.status !== 200) throw new Error(j.message || "加载失败");
          var d = j.data;
          vTotal = d.total || 0;
          var tasks = d.tasks || [];
          if (vMeta) vMeta.textContent = "共 " + vTotal + " 条";
          if (vPageLabel)
            vPageLabel.textContent =
              "第 " + (d.page || vPage) + " 页 / 每页 " + (d.page_size || vPageSize);
          vCards.innerHTML = "";
          if (vEmpty) vEmpty.style.display = tasks.length ? "none" : "block";
          tasks.forEach(function (t) {
            var urls = t.videos || [];
            var previewHtml =
              urls.length > 0
                ? '<video controls playsinline preload="metadata" class="mpt-video-card-preview" src="' +
                  mptEscapeAttr(urls[0]) +
                  '"></video>'
                : '<div class="mpt-video-card-no-preview">—</div>';
            var links = mptVideoLinksHtml(urls);
            var card = document.createElement("div");
            card.className = "ant-card ant-card-bordered mpt-video-card";
            var taskId = t.task_id || "";
            var taskIdHtml =
              '<span title="' +
              mptEscapeAttr(taskId) +
              '" class="mpt-cell-ellipsis">' +
              mptEscapeHtml(mptShortTaskId(taskId)) +
              "</span>";
            card.innerHTML =
              '<div class="ant-card-body">' +
              '<div class="mpt-video-card-media">' +
              previewHtml +
              "</div>" +
              '<div class="mpt-video-card-field"><span class="mpt-video-card-label">主题</span><span class="mpt-video-card-value mpt-cell-ellipsis" title="' +
              mptEscapeAttr(t.video_subject || "") +
              '">' +
              mptEscapeHtml(t.video_subject || "—") +
              "</span></div>" +
              '<div class="mpt-video-card-field"><span class="mpt-video-card-label">任务 ID</span><span class="mpt-video-card-value">' +
              taskIdHtml +
              "</span></div>" +
              '<div class="mpt-video-card-field"><span class="mpt-video-card-label">创建日期</span><span class="mpt-video-card-value">' +
              mptEscapeHtml(mptFormatYmd(t.created_at || "")) +
              "</span></div>" +
              '<div class="mpt-video-card-field"><span class="mpt-video-card-label">完成时间</span><span class="mpt-video-card-value mpt-cell-ellipsis" title="' +
              mptEscapeAttr(t.completed_at || "") +
              '">' +
              mptEscapeHtml(t.completed_at || "—") +
              "</span></div>" +
              '<div class="mpt-video-card-field"><span class="mpt-video-card-label">素材来源</span><span class="mpt-video-card-value">' +
              mptEscapeHtml(t.video_source || "—") +
              "</span></div>" +
              '<div class="mpt-video-card-field"><span class="mpt-video-card-label">成片链接</span><span class="mpt-video-card-value">' +
              (links || "—") +
              "</span></div>" +
              "</div>";
            vCards.appendChild(card);
          });
        })
        .catch(function (e) {
          if (vMeta) vMeta.textContent = e.message || String(e);
        });
    }

    document.getElementById("mpt-videos-refresh").addEventListener("click", function () {
      loadVideos();
    });
    if (vFilterApply) {
      vFilterApply.addEventListener("click", function () {
        vAppliedFilters.subject = vFilterSubject ? vFilterSubject.value.trim() : "";
        vAppliedFilters.state = vFilterState ? vFilterState.value : "";
        vAppliedFilters.createdFrom = vFilterFrom ? toIsoFromLocal(vFilterFrom.value) : "";
        vAppliedFilters.createdTo = vFilterTo ? toIsoFromLocal(vFilterTo.value) : "";
        vPage = 1;
        loadVideos();
      });
    }
    if (vFilterReset) {
      vFilterReset.addEventListener("click", function () {
        if (vFilterSubject) vFilterSubject.value = "";
        if (vFilterState) vFilterState.value = "";
        if (vFilterFrom) vFilterFrom.value = "";
        if (vFilterTo) vFilterTo.value = "";
        vAppliedFilters.subject = "";
        vAppliedFilters.state = "";
        vAppliedFilters.createdFrom = "";
        vAppliedFilters.createdTo = "";
        vPage = 1;
        loadVideos();
      });
    }
    document.getElementById("mpt-videos-prev").addEventListener("click", function () {
      if (vPage > 1) {
        vPage--;
        loadVideos();
      }
    });
    document.getElementById("mpt-videos-next").addEventListener("click", function () {
      if (vPage * vPageSize < vTotal) {
        vPage++;
        loadVideos();
      }
    });
    loadVideos();
  }
})();
