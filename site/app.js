(function () {
  "use strict";

  var STORAGE_KEY = "index-x-theme";
  var DEFAULT_LIMIT = 12;

  var root = document.documentElement;
  var themeToggle = document.getElementById("theme-toggle");
  var themeIcon = document.getElementById("theme-icon");
  var menuToggle = document.getElementById("menu-toggle");
  var mobileDrawer = document.getElementById("mobile-drawer");
  var toastEl = document.getElementById("toast");

  var toastTimer = null;
  function showToast(msg) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.classList.add("is-visible");
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toastEl.classList.remove("is-visible");
    }, 2400);
  }

  /* ── Theme Toggle ── */
  function syncThemeUI(theme) {
    if (!themeIcon) return;
    themeIcon.textContent = theme === "dark" ? "☀️" : "🌙";
    if (themeToggle) {
      themeToggle.setAttribute("aria-label", theme === "dark" ? "切换到浅色主题" : "切换到深色主题");
      themeToggle.setAttribute("title", theme === "dark" ? "切换到浅色主题" : "切换到深色主题");
    }
  }

  syncThemeUI(root.getAttribute("data-theme") || "light");

  if (themeToggle) {
    themeToggle.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      syncThemeUI(next);
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch (e) {
        /* ignore storage failures */
      }
    });
  }

  /* ── Mobile Navigation Drawer ── */
  if (menuToggle && mobileDrawer) {
    menuToggle.addEventListener("click", function () {
      var open = !mobileDrawer.classList.contains("is-open");
      mobileDrawer.classList.toggle("is-open", open);
      menuToggle.setAttribute("aria-expanded", String(open));
    });

    mobileDrawer.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        mobileDrawer.classList.remove("is-open");
        menuToggle.setAttribute("aria-expanded", "false");
      });
    });
  }

  /* ── Active Section Nav Highlight ── */
  var navLinks = Array.prototype.slice.call(document.querySelectorAll(".nav-links .nav-link"));
  var sectionIds = navLinks
    .map(function (a) { return a.getAttribute("href"); })
    .filter(function (href) { return href && href.indexOf("#") === 0; })
    .map(function (href) { return href.slice(1); });

  if ("IntersectionObserver" in window && sectionIds.length) {
    var activeMap = {};
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        activeMap[entry.target.id] = entry.isIntersecting;
      });
      var currentId = null;
      for (var i = 0; i < sectionIds.length; i++) {
        if (activeMap[sectionIds[i]]) {
          currentId = sectionIds[i];
          break;
        }
      }
      if (currentId) {
        navLinks.forEach(function (a) {
          a.classList.toggle("is-active", a.getAttribute("href") === "#" + currentId);
        });
      }
    }, { rootMargin: "-25% 0px -60% 0px" });

    sectionIds.forEach(function (id) {
      var el = document.getElementById(id);
      if (el) observer.observe(el);
    });
  }

  /* ── Interactive Footnote Popover (㊟) ── */
  var popover = document.getElementById("note-popover");
  var popoverTitle = document.getElementById("note-popover-title");
  var popoverBody = document.getElementById("note-popover-body");
  var popoverClose = document.getElementById("note-popover-close");
  var activeNoteBtn = null;

  function closePopover() {
    if (!popover) return;
    popover.hidden = true;
    if (activeNoteBtn) {
      activeNoteBtn.setAttribute("aria-expanded", "false");
      activeNoteBtn = null;
    }
  }

  function positionPopover(btn) {
    if (!popover || !btn) return;
    var rect = btn.getBoundingClientRect();
    var popRect = popover.getBoundingClientRect();
    var margin = 12;
    var left = Math.min(
      Math.max(margin, rect.left + rect.width / 2 - popRect.width / 2),
      window.innerWidth - popRect.width - margin
    );
    var top = rect.bottom + 8;
    if (top + popRect.height > window.innerHeight - margin) {
      top = Math.max(margin, rect.top - popRect.height - 8);
    }
    popover.style.left = Math.round(left) + "px";
    popover.style.top = Math.round(top) + "px";
  }

  document.querySelectorAll(".note-trigger").forEach(function (btn) {
    btn.addEventListener("click", function (ev) {
      ev.stopPropagation();
      if (activeNoteBtn === btn && popover && !popover.hidden) {
        closePopover();
        return;
      }
      if (activeNoteBtn) {
        activeNoteBtn.setAttribute("aria-expanded", "false");
      }
      activeNoteBtn = btn;
      btn.setAttribute("aria-expanded", "true");
      if (popoverTitle) popoverTitle.textContent = btn.getAttribute("data-note-title") || "译注";
      if (popoverBody) popoverBody.textContent = btn.getAttribute("data-note") || "";
      if (popover) {
        popover.hidden = false;
        positionPopover(btn);
      }
    });
  });

  if (popoverClose) {
    popoverClose.addEventListener("click", function () {
      var prev = activeNoteBtn;
      closePopover();
      if (prev) prev.focus();
    });
  }

  document.addEventListener("click", function (ev) {
    if (popover && !popover.hidden && !popover.contains(ev.target)) {
      closePopover();
    }
  });

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") {
      closePopover();
    }
  });

  window.addEventListener("resize", function () {
    if (activeNoteBtn && popover && !popover.hidden) {
      positionPopover(activeNoteBtn);
    }
  });

  /* ── Quote Style Toggle (Showcase Lab) ── */
  var quoteBox = document.getElementById("quote-sample-box");
  var quoteCaption = document.getElementById("quote-caption");
  var quoteBtns = document.querySelectorAll("[data-quote-mode]");

  function renderQuoteSample(mode) {
    if (!quoteBox || !quoteCaption) return;
    quoteBox.textContent = "";
    if (mode === "curly") {
      function makeBadCurly(ch) {
        var sp = document.createElement("span");
        sp.style.fontFamily = 'Georgia, "Times New Roman", serif';
        sp.style.color = "var(--bad)";
        sp.style.background = "rgba(244, 63, 94, 0.12)";
        sp.style.borderRadius = "2px";
        sp.textContent = ch;
        return sp;
      }
      var p1 = document.createElement("p");
      p1.style.margin = "0";
      p1.appendChild(document.createTextNode("上条低声念出"));
      p1.appendChild(makeBadCurly("\u201c"));
      p1.appendChild(document.createTextNode("Imagine Breaker"));
      p1.appendChild(makeBadCurly("\u201d"));
      p1.appendChild(document.createTextNode("的名字，回答道："));
      p1.appendChild(makeBadCurly("\u201c"));
      p1.appendChild(document.createTextNode("那我就先把你那无聊的幻想给彻底杀掉！"));
      p1.appendChild(makeBadCurly("\u201d"));
      quoteBox.appendChild(p1);
      quoteCaption.textContent = "在西文优先字体栈下，高亮处的“”按西文窄比例渲染，紧贴汉字造成间距局促。";
    } else {
      var p2 = document.createElement("p");
      p2.style.margin = "0";
      p2.appendChild(document.createTextNode("上条低声念出「Imagine Breaker」的名字，回答道：「那我就先把你那无聊的幻想给彻底杀掉！」"));
      quoteBox.appendChild(p2);
      quoteCaption.textContent = "正文统一使用全角直角引号「」（双层嵌套用『』），间距稳定且与方块字视觉协调。";
    }
    quoteBtns.forEach(function (b) {
      b.classList.toggle("is-active", b.getAttribute("data-quote-mode") === mode);
    });
  }

  renderQuoteSample("corner");
  quoteBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      renderQuoteSample(btn.getAttribute("data-quote-mode"));
    });
  });

  /* ── Catalog Rendering & Filtering ── */
  var catalog = window.INDEX_X_CATALOG || { summary: { doneTotal: 0, pendingTotal: 0 }, series: [], books: [] };
  var overviewEl = document.getElementById("series-overview");
  var activeSeriesNameEl = document.getElementById("active-series-name");
  var resetSeriesBtn = document.getElementById("reset-series-btn");
  var statusTabsEl = document.getElementById("status-tabs");
  var searchInput = document.getElementById("catalog-search");
  var countLabel = document.getElementById("catalog-count-label");
  var bookGrid = document.getElementById("book-grid");
  var moreWrap = document.getElementById("catalog-more");

  var state = {
    series: "all",
    status: "all",
    query: "",
    expanded: false
  };

  var ALL_SERIES_CARD = {
    key: "all",
    code: "ALL",
    name: "全部系列总览",
    done: catalog.summary ? catalog.summary.doneTotal : 82,
    pending: catalog.summary ? catalog.summary.pendingTotal : 8,
    desc: "汇总 S1 旧约、S2 新约、S3 创约、S4 某暗部的少女共栖、S5 外典系列、S6 日期短篇与外传及 S0 阅读说明的全部卷目。"
  };

  function getSeriesCardItems() {
    return [ALL_SERIES_CARD].concat(catalog.series || []);
  }

  function getActiveSeriesMeta() {
    var items = getSeriesCardItems();
    for (var i = 0; i < items.length; i++) {
      if (items[i].key === state.series) return items[i];
    }
    return ALL_SERIES_CARD;
  }

  function renderSeriesOverview() {
    if (!overviewEl) return;
    overviewEl.textContent = "";
    getSeriesCardItems().forEach(function (item) {
      var total = item.done + item.pending;
      var pct = total ? Math.round((item.done / total) * 100) : 0;
      var selected = state.series === item.key;

      var card = document.createElement("button");
      card.type = "button";
      card.className = "series-card" + (selected ? " is-selected" : "");
      card.setAttribute("role", "tab");
      card.setAttribute("aria-selected", String(selected));
      card.setAttribute("data-series-card", item.key);

      var meta = document.createElement("div");
      meta.className = "series-card-meta";

      var code = document.createElement("span");
      code.className = "series-code";
      code.textContent = item.code || item.key;

      var count = document.createElement("span");
      count.className = "series-count";
      count.textContent = item.done + " / " + total + " 册";

      meta.appendChild(code);
      meta.appendChild(count);

      var name = document.createElement("div");
      name.className = "series-name";
      name.textContent = item.name;

      var track = document.createElement("div");
      track.className = "progress-track";
      var fill = document.createElement("div");
      fill.className = "progress-fill";
      fill.style.width = pct + "%";
      track.appendChild(fill);

      var desc = document.createElement("div");
      desc.className = "series-desc";
      desc.textContent = item.desc;

      card.appendChild(meta);
      card.appendChild(name);
      card.appendChild(track);
      card.appendChild(desc);

      card.addEventListener("click", function () {
        if (state.series !== item.key) {
          state.series = item.key;
          state.expanded = false;
          syncCatalog();
        }
      });

      overviewEl.appendChild(card);
    });
  }

  function createBookCard(book) {
    var card = document.createElement("article");
    card.className = "book-card" + (book.status === "pending" ? " is-pending" : "");

    var top = document.createElement("div");
    top.className = "book-top";

    var idEl = document.createElement("span");
    idEl.className = "book-id";
    idEl.textContent = book.id;

    var statusEl = document.createElement("span");
    statusEl.className = "book-status " + (book.status === "done" ? "done" : "pending");
    statusEl.textContent = book.status === "done" ? "已成品" : "待制作";

    top.appendChild(idEl);
    top.appendChild(statusEl);

    var titleEl = document.createElement("div");
    titleEl.className = "book-title";
    titleEl.textContent = book.title;

    var foot = document.createElement("div");
    foot.className = "book-foot";

    var sourceEl = document.createElement("span");
    sourceEl.className = "source-pill";
    sourceEl.textContent = book.source;

    var noteEl = document.createElement("span");
    noteEl.textContent = book.note;

    foot.appendChild(sourceEl);
    foot.appendChild(noteEl);

    card.appendChild(top);
    card.appendChild(titleEl);
    card.appendChild(foot);
    return card;
  }

  function syncCatalog() {
    renderSeriesOverview();

    var activeMeta = getActiveSeriesMeta();
    if (activeSeriesNameEl) {
      activeSeriesNameEl.textContent = "当前查看：" + activeMeta.name;
    }
    if (resetSeriesBtn) {
      resetSeriesBtn.hidden = state.series === "all";
    }

    var seriesBooks = catalog.books.filter(function (book) {
      return state.series === "all" || book.series === state.series;
    });
    var seriesDone = 0;
    var seriesPending = 0;
    seriesBooks.forEach(function (book) {
      if (book.status === "done") seriesDone += 1;
      else seriesPending += 1;
    });

    if (statusTabsEl) {
      var counts = {
        all: seriesBooks.length,
        done: seriesDone,
        pending: seriesPending
      };
      var labels = {
        all: "全部状态",
        done: "已成品",
        pending: "待制作"
      };
      statusTabsEl.querySelectorAll("[data-status]").forEach(function (btn) {
        var key = btn.getAttribute("data-status") || "all";
        btn.textContent = labels[key] + " (" + counts[key] + ")";
        btn.classList.toggle("is-active", key === state.status);
      });
    }

    var q = state.query.trim().toLowerCase();
    var matched = seriesBooks.filter(function (book) {
      if (state.status !== "all" && book.status !== state.status) return false;
      if (!q) return true;
      return (
        book.id.toLowerCase().indexOf(q) !== -1 ||
        book.title.toLowerCase().indexOf(q) !== -1 ||
        book.source.toLowerCase().indexOf(q) !== -1 ||
        book.note.toLowerCase().indexOf(q) !== -1
      );
    });

    if (countLabel) {
      countLabel.textContent = "共匹配 " + matched.length + " 册书目";
    }

    if (!bookGrid || !moreWrap) return;
    bookGrid.textContent = "";
    moreWrap.textContent = "";

    if (matched.length === 0) {
      var empty = document.createElement("div");
      empty.className = "catalog-empty";
      var emptyText = document.createElement("p");
      emptyText.style.margin = "0 0 12px";
      emptyText.textContent = "没有找到符合当前筛选条件的卷目。";
      var resetBtn = document.createElement("button");
      resetBtn.type = "button";
      resetBtn.className = "ghost-btn";
      resetBtn.textContent = "重置筛选条件";
      resetBtn.addEventListener("click", function () {
        state.series = "all";
        state.status = "all";
        state.query = "";
        state.expanded = false;
        if (searchInput) searchInput.value = "";
        syncCatalog();
      });
      empty.appendChild(emptyText);
      empty.appendChild(resetBtn);
      bookGrid.appendChild(empty);
      return;
    }

    var isAllUnfiltered = state.series === "all" && state.status === "all" && !q;
    var limit = isAllUnfiltered && !state.expanded ? DEFAULT_LIMIT : matched.length;
    var visible = matched.slice(0, limit);

    visible.forEach(function (book) {
      bookGrid.appendChild(createBookCard(book));
    });

    if (isAllUnfiltered && matched.length > DEFAULT_LIMIT) {
      var toggleMoreBtn = document.createElement("button");
      toggleMoreBtn.type = "button";
      toggleMoreBtn.className = "btn btn-secondary";
      toggleMoreBtn.textContent = state.expanded
        ? "收起部分列表（仅保留前 " + DEFAULT_LIMIT + " 册）"
        : "展开全部 " + matched.length + " 册书目";
      toggleMoreBtn.addEventListener("click", function () {
        state.expanded = !state.expanded;
        syncCatalog();
      });
      moreWrap.appendChild(toggleMoreBtn);
    }
  }

  if (resetSeriesBtn) {
    resetSeriesBtn.addEventListener("click", function () {
      state.series = "all";
      state.expanded = false;
      syncCatalog();
    });
  }

  if (statusTabsEl) {
    statusTabsEl.querySelectorAll("[data-status]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        state.status = btn.getAttribute("data-status") || "all";
        state.expanded = false;
        syncCatalog();
      });
    });
  }

  if (searchInput) {
    searchInput.addEventListener("input", function () {
      state.query = searchInput.value || "";
      syncCatalog();
    });
  }

  syncCatalog();

  /* ── FAQ Expand / Collapse All ── */
  var faqToggleAll = document.getElementById("faq-toggle-all");
  var faqItems = Array.prototype.slice.call(document.querySelectorAll(".faq-item"));

  if (faqToggleAll && faqItems.length) {
    faqToggleAll.addEventListener("click", function () {
      var expanded = faqToggleAll.getAttribute("data-expanded") === "true";
      var nextOpen = !expanded;
      faqItems.forEach(function (item) {
        item.open = nextOpen;
      });
      faqToggleAll.setAttribute("data-expanded", String(nextOpen));
      faqToggleAll.textContent = nextOpen ? "全部收起" : "全部展开";
    });
  }

  function openFaqById(id) {
    if (!id) return;
    var target = document.getElementById(id);
    if (target && target.tagName === "DETAILS") {
      target.open = true;
    }
  }

  document.querySelectorAll("[data-open-faq]").forEach(function (link) {
    link.addEventListener("click", function () {
      openFaqById(link.getAttribute("data-open-faq"));
    });
  });

  if (window.location.hash && window.location.hash.length > 1) {
    openFaqById(window.location.hash.slice(1));
  }

  /* ── On-demand Detail Drawers (#comparison) ── */
  function setExampleDrawer(rowId, focusCol) {
    var drawer = document.getElementById(rowId);
    if (!drawer) return;

    var row = drawer.closest(".comp-row");
    var dimEl = row ? row.querySelector(".dim-name") : null;
    var dimName = dimEl ? dimEl.textContent.trim() : "";
    var rowCells = document.querySelectorAll('[data-example-row="' + rowId + '"]');
    var panels = drawer.querySelectorAll("[data-col]");
    var badge = drawer.querySelector("[data-drawer-badge]");
    var titleEl = drawer.querySelector("[data-drawer-title]");

    if (!focusCol) {
      drawer.hidden = true;
      drawer.removeAttribute("data-active-side");
      panels.forEach(function (panel) { panel.hidden = true; });
      if (badge) {
        badge.textContent = "";
        badge.className = "ex-col-badge";
      }
      if (titleEl && dimName) {
        titleEl.textContent = dimName;
      }
      rowCells.forEach(function (cell) {
        cell.setAttribute("aria-expanded", "false");
      });
      return;
    }

    drawer.hidden = false;
    drawer.setAttribute("data-active-side", focusCol);
    panels.forEach(function (panel) {
      panel.hidden = panel.getAttribute("data-col") !== focusCol;
    });
    if (badge) {
      badge.textContent = focusCol === "wf" ? "网译 · 民间译本" : "台版 · 官方繁中";
      badge.className = "ex-col-badge " + (focusCol === "wf" ? "wf" : "tw");
    }
    var activeStatus = "";
    rowCells.forEach(function (cell) {
      var f = cell.getAttribute("data-example-focus");
      var isActive = f === focusCol;
      cell.setAttribute("aria-expanded", String(isActive));
      if (isActive) {
        var st = cell.querySelector(".status-line");
        if (st) activeStatus = st.textContent.trim();
      }
    });
    if (titleEl && dimName) {
      titleEl.textContent = activeStatus ? dimName + " · " + activeStatus : dimName;
    }
  }

  function toggleExampleCell(cell) {
    var rowId = cell.getAttribute("data-example-row");
    var focusCol = cell.getAttribute("data-example-focus");
    var drawer = document.getElementById(rowId);
    if (!drawer) return;

    var alreadyOpen = !drawer.hidden;
    var sameCellActive = cell.getAttribute("aria-expanded") === "true";
    if (alreadyOpen && sameCellActive) {
      setExampleDrawer(rowId, null);
    } else {
      setExampleDrawer(rowId, focusCol);
    }
  }

  document.querySelectorAll("[data-example-row]").forEach(function (cell) {
    cell.addEventListener("click", function () {
      if (window.getSelection && window.getSelection().toString().length > 0) {
        return;
      }
      toggleExampleCell(cell);
    });
    cell.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        toggleExampleCell(cell);
      }
    });
  });

  document.querySelectorAll("[data-example-close]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      setExampleDrawer(btn.getAttribute("data-example-close"), null);
    });
  });

  /* ── Copy Buttons ── */
  function fallbackCopy(text) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
    } catch (e) {
      /* ignore */
    }
    document.body.removeChild(ta);
  }

  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var text = btn.getAttribute("data-copy") || "";
      var label = btn.getAttribute("data-copy-label") || text;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () {
          showToast("已复制：" + label);
        }).catch(function () {
          fallbackCopy(text);
          showToast("已复制：" + label);
        });
      } else {
        fallbackCopy(text);
        showToast("已复制：" + label);
      }
    });
  });

  /* ── Progressive Enhancement: Latest GitHub Release Pill ── */
  var releasePill = document.getElementById("latest-release-pill");
  var releasesCta = document.getElementById("releases-cta");

  if (typeof fetch === "function" && typeof AbortController === "function") {
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, 4000);
    fetch("https://api.github.com/repos/1204244136/index-X/releases/latest", {
      signal: controller.signal,
      headers: { Accept: "application/vnd.github+json" }
    })
      .then(function (res) {
        clearTimeout(timer);
        if (!res.ok) return null;
        return res.json();
      })
      .then(function (data) {
        if (!data || !data.tag_name) return;
        if (releasePill) {
          releasePill.textContent = "最新发版：" + data.tag_name;
        }
        if (releasesCta && data.html_url) {
          releasesCta.setAttribute("href", data.html_url);
        }
      })
      .catch(function () {
        clearTimeout(timer);
      });
  }
})();
