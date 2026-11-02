(() => {
  "use strict";
  const P = window.PROGRAMME;
  const S = P.schedule;
  const E = P.entries;
  const THEMES = P.themes;
  const TZ = "Europe/Lisbon";

  const $ = (s) => document.querySelector(s);
  const setHdr = () => document.documentElement.style.setProperty("--hdr", $(".top").offsetHeight + "px");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
  };

  // ---- where/when each code is scheduled ----
  const slots = {}; // code -> [{date, label, start, end, room}]
  const addSlot = (code, s) => (slots[code] ||= []).push(s);
  S.days.forEach((day) => day.rows.forEach(([start, end, slot]) => {
    if (Array.isArray(slot)) slot.forEach((c, i) => c && addSlot(c, { date: day.date, label: day.label, start, end, room: S.rooms[i] }));
    else if (slot.keynote) addSlot(slot.keynote, { date: day.date, label: day.label, start, end, room: "Room 1" });
  }));
  S.posters.forEach((p) => p.boards.forEach(([board, codes]) => codes.forEach((c) =>
    addSlot(c, { date: p.date, label: p.label, start: p.session, end: "", room: "Poster " + board }))));

  // ---- state ----
  let stars = new Set(store.get("icffr-stars", []));
  let hiddenThemes = new Set(store.get("icffr-hidden-themes", []));
  let query = "";
  const TABS = [...S.days.map((d) => ({ id: d.date, label: d.label })), { id: "posters", label: "Posters" }, { id: "picks", label: "★ My picks" }, { id: "other", label: "Other days" }];

  // ---- Lisbon clock ----
  function lisbonNow() {
    const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
      .formatToParts(new Date()).map((p) => [p.type, p.value]));
    return { date: `${parts.year}-${parts.month}-${parts.day}`, time: `${parts.hour}:${parts.minute}` };
  }
  const now = lisbonNow();
  let tab = store.get("icffr-tab", null);
  if (S.days.some((d) => d.date === now.date)) tab = now.date;
  if (!TABS.some((t) => t.id === tab)) tab = S.days[0].date;

  // ---- search ----
  const haystack = {};
  for (const [code, e] of Object.entries(E)) {
    const alt = e.altSpeaker || {};
    haystack[code] = [code, e.title, e.presenter, e.country, e.institution, (e.authors || []).join(" "), e.keywords, e.abstract,
      alt.speaker, alt.country, alt.institution,
      ...(e.conflicts || []).flatMap((c) => [c.title, c.presenter])].join(" \n ").toLowerCase();
  }
  const fold = (s) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  for (const k in haystack) haystack[k] = fold(haystack[k]);
  function matches(code) {
    if (!query) return true;
    const h = haystack[code];
    return !!h && query.split(/\s+/).every((w) => h.includes(w));
  }
  const visible = (code) => {
    const e = E[code];
    return !(e && hiddenThemes.has(e.theme));
  };

  // ---- rendering helpers ----
  const short = (name) => (name || "").split(",")[0];
  // theme colour + search/filter state; on a grid cell these go on the <td> so the colour fills the whole cell
  function stateClasses(code) {
    const e = E[code];
    if (!e) return [];
    const cls = [e.kind === "keynote" ? "kn" : "th-" + e.theme];
    if (query) cls.push(matches(code) ? "hit" : "dim");
    else if (!visible(code)) cls.push("dim");
    return cls;
  }
  function talkButton(code, opts = {}) {
    const e = E[code];
    if (!e) return `<button class="talk" data-code="${esc(code)}"><div class="code">${esc(code)}</div><div class="p">No details listed</div></button>`;
    const cls = ["talk", ...(opts.inCell ? [] : stateClasses(code))];
    if (stars.has(code)) cls.push("starred");
    if (e.conflicts) cls.push("warn");
    const head = e.kind === "keynote" ? `${code} · ${short(e.presenter)}` : code;
    return `<button class="${cls.join(" ")}" data-code="${esc(code)}">
      <span class="star" aria-label="starred">★</span>
      <div class="code">${esc(head)}${opts.room ? `<span class="room">${esc(opts.room)}</span>` : ""}</div>
      <div class="t">${esc(e.title)}</div>
      ${e.kind === "keynote" || opts.noPresenter ? "" : `<div class="p">${esc(e.presenter)}${e.country ? ` · ${esc(e.country)}` : ""}</div>`}
    </button>`;
  }

  function rowState(day, start, end) {
    if (day.date !== now.date) return day.date < now.date ? "past" : "";
    if (now.time >= start && now.time < end) return "now";
    return now.time >= end ? "past" : "";
  }

  function renderDay(day) {
    const cols = S.rooms.length;
    let html = `<div class="scroller"><table class="grid"><colgroup><col class="time">${S.rooms.map(() => "<col>").join("")}</colgroup>
      <thead><tr><th class="time">Time</th>${S.rooms.map((r) => `<th>${esc(r)}</th>`).join("")}</tr></thead><tbody>`;
    for (const [start, end, slot] of day.rows) {
      html += `<tr class="${rowState(day, start, end)}"><td class="time">${start}–${end}</td>`;
      if (Array.isArray(slot)) {
        html += slot.map((c, i) => (c ? `<td class="cell ${stateClasses(c).join(" ")}">${talkButton(c, { room: S.rooms[i], inCell: true })}</td>` : `<td class="empty"></td>`)).join("");
      } else if (slot.keynote) {
        html += `<td colspan="${cols}" class="evc-keynote">${talkButton(slot.keynote)}</td>`;
      } else {
        const kind = slot.kind || "break";
        html += `<td colspan="${cols}" class="evc-${kind}"><div class="ev ${kind}">${esc(slot.event)}${slot.note ? `<small>${esc(slot.note)}</small>` : ""}</div></td>`;
      }
      html += "</tr>";
    }
    return html + "</tbody></table></div>";
  }

  function renderPosters() {
    let html = `<p class="daynote">Poster boards (TV screens) by day. Coffee breaks double as poster sessions.</p>`;
    for (const p of S.posters) {
      html += `<h2 class="section">${esc(p.label)} <small>· ${esc(p.session)}</small></h2><div class="boards">`;
      for (const [board, codes, note] of p.boards) {
        html += `<div class="board"><h3>${esc(board)}</h3>${note ? `<div class="note">${esc(note)}</div>` : ""}${codes.map((c) => talkButton(c)).join("")}</div>`;
      }
      html += "</div>";
    }
    if (P.unscheduled.length) {
      html += `<h2 class="section">Listed but not in the schematic <small>· in the organisers' code lists but absent from the PDF grid (possibly withdrawn)</small></h2>
        <div class="boards"><div class="board">${P.unscheduled.map((c) => talkButton(c)).join("")}</div></div>`;
    }
    return html;
  }

  function slotLine(s) {
    return `${s.label} · ${s.start}${s.end ? "–" + s.end : ""} · ${s.room}`;
  }

  function renderPicks() {
    const picked = [...stars].filter((c) => E[c]);
    if (!picked.length) return `<p class="empty-msg">Nothing starred yet. Open a talk and press ★ Star to collect it here.</p>`;
    const rows = picked.flatMap((c) => (slots[c] || [{ label: "Unscheduled", date: "9999", start: "", end: "", room: "" }]).map((s) => ({ c, s })));
    rows.sort((a, b) => (a.s.date + a.s.start).localeCompare(b.s.date + b.s.start));
    let html = `<div class="list">`;
    let last = "";
    for (const { c, s } of rows) {
      const head = slotLine(s);
      if (head !== last) html += `<div class="when">${esc(head)}</div>`;
      last = head;
      html += talkButton(c);
    }
    return html + "</div>";
  }

  function renderOther() {
    return `<div class="list">${S.extraDays.map((d) => `<div class="when">${esc(d.label)}</div><div class="board">${esc(d.text)}</div>`).join("")}
      <p class="daynote" style="margin-top:16px">See <a href="https://events.adai.pt/en/10th-icffr/related-events" target="_blank" rel="noopener">short courses &amp; related events</a>.</p></div>`;
  }

  function hitsFor(tabId) {
    if (!query) return 0;
    const set = new Set();
    if (tabId === "posters") {
      S.posters.forEach((p) => p.boards.forEach(([, codes]) => codes.forEach((c) => matches(c) && set.add(c))));
      P.unscheduled.forEach((c) => matches(c) && set.add(c));
    }
    else {
      const day = S.days.find((d) => d.date === tabId);
      if (!day) return 0;
      day.rows.forEach(([, , slot]) => (Array.isArray(slot) ? slot : [slot.keynote]).forEach((c) => c && matches(c) && set.add(c)));
    }
    return set.size;
  }

  function renderTabs() {
    $("#tabs").innerHTML = TABS.map((t) => {
      const n = hitsFor(t.id);
      const cls = t.id === now.date ? "today" : "";
      return `<button role="tab" class="${cls}" data-tab="${t.id}" aria-selected="${t.id === tab}">${esc(t.label)}${n ? `<span class="hits">${n}</span>` : ""}</button>`;
    }).join("");
  }

  function renderLegend() {
    $("#legend").innerHTML = Object.entries(THEMES).map(([k, name]) =>
      `<button class="th-${k}${hiddenThemes.has(k) ? " off" : ""}" data-theme="${k}" title="Show/hide ${esc(name)}">${k}<span class="ln"> · ${esc(name)}</span></button>`).join("") +
      (hiddenThemes.size ? `<button class="clear" data-theme="">show all</button>` : "");
  }

  function render() {
    renderTabs();
    renderLegend();
    setHdr();
    const day = S.days.find((d) => d.date === tab);
    const prev = $("#view .scroller");
    const keepX = prev && prev.dataset.tab === tab ? prev.scrollLeft : 0;
    $("#view").innerHTML = day ? renderDay(day) : tab === "posters" ? renderPosters() : tab === "picks" ? renderPicks() : renderOther();
    const total = query ? Object.keys(E).filter(matches).length : 0;
    const sc = $("#view .scroller");
    if (sc) { sc.dataset.tab = tab; sc.scrollLeft = keepX; }
    $("#search-count").textContent = query ? `${total} match${total === 1 ? "" : "es"}` : "";
  }

  // ---- detail content ----
  const affiliation = (country, institution) => {
    const parts = [country, institution].filter(Boolean);
    return parts.length ? `<br><span class="d-aff">${esc(parts.join(" · "))}</span>` : "";
  };
  function detailHTML(code, full) {
    const e = E[code];
    if (!e) return `<div class="d-title">${esc(code)}</div><p>No details listed for this code.</p>`;
    const theme = e.kind === "keynote" ? "Keynote" : THEMES[e.theme] + (e.kind === "poster" ? " · poster" : "");
    const when = (slots[code] || []).map(slotLine).join("<br>") || "Not in the schematic grid";
    const authors = (e.authors || []).filter(Boolean);
    let html = `<div class="d-head"><span class="d-code th-${e.kind === "keynote" ? "KN" : e.theme}">${esc(code)}</span><span class="d-theme">${esc(theme)}</span></div>
      <div class="d-title">${esc(e.title)}</div>
      <div class="d-when">${when}</div>
      <div class="d-who"><b>${esc(e.presenter)}</b>${affiliation(e.country, e.institution)}${authors.length > 1 ? `<br><span class="d-theme">${esc(authors.join(", "))}</span>` : ""}</div>`;
    if (e.altSpeaker) {
      const a = e.altSpeaker;
      html += `<div class="d-warn">The organisers' detailed programme lists the speaker as <b>${esc(a.speaker)}</b>${affiliation(a.country, a.institution)}</div>`;
    }
    if (full) html += `<button class="star-btn${stars.has(code) ? " on" : ""}" data-star="${esc(code)}">${stars.has(code) ? "★ Starred" : "☆ Star"}</button>`;
    if (e.conflicts) {
      html += `<div class="d-warn">⚠ The organisers' by-theme list also gives code ${esc(code)} to:` +
        e.conflicts.map((c) => `<details><summary><b>${esc(c.title)}</b> — ${esc(c.presenter)}</summary>${c.abstract ? `<div class="d-abs">${esc(c.abstract)}</div>` : ""}</details>`).join("") +
        `Check the room on the day.</div>`;
    }
    if (e.keywords) html += `<div class="d-kw">${esc(e.keywords)}</div>`;
    if (e.abstract) html += `<div class="d-label">${e.kind === "keynote" ? "Summary" : "Abstract"}</div><div class="d-abs">${esc(e.abstract)}</div>`;
    else html += `<div class="d-kw">No abstract published.</div>`;
    if (full && e.bio) html += `<div class="d-label">Speaker</div><div class="d-abs">${esc(e.bio)}</div>`;
    return html;
  }

  // ---- tooltip (hover, fine pointers only) ----
  const tip = $("#tip");
  const canHover = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
  let tipFor = null;
  function showTip(el) {
    const code = el.dataset.code;
    if (tipFor === code) return;
    tipFor = code;
    tip.innerHTML = detailHTML(code, false) + `<span class="more">click to open</span>`;
    tip.style.maxHeight = "";
    tip.hidden = false;
    const r = el.getBoundingClientRect();
    const tw = tip.offsetWidth, vw = innerWidth, vh = innerHeight, gap = 10;
    let th = tip.offsetHeight, left, top;
    if (r.right + gap + tw <= vw - 8) { left = r.right + gap; top = Math.max(8, Math.min(vh - th - 8, r.top)); }
    else if (r.left - gap - tw >= 8) { left = r.left - gap - tw; top = Math.max(8, Math.min(vh - th - 8, r.top)); }
    else {
      // no room beside the cell: go above or below, whichever has more space, and never cover the cell
      left = Math.max(8, Math.min(vw - tw - 8, r.left));
      const below = vh - r.bottom - gap - 8, above = r.top - gap - 8;
      const room = Math.max(below, above, 120);
      if (th > room) { tip.style.maxHeight = room + "px"; th = room; }
      top = below >= above ? r.bottom + gap : r.top - gap - th;
    }
    tip.style.left = left + "px";
    tip.style.top = top + "px";
  }
  function hideTip() { tip.hidden = true; tipFor = null; }
  if (canHover) {
    document.addEventListener("mouseover", (ev) => {
      const el = ev.target.closest(".talk");
      if (el && !$("#panel").contains(el)) showTip(el); else hideTip();
    });
    document.addEventListener("scroll", hideTip, true);
    document.addEventListener("mouseout", (ev) => { if (!ev.relatedTarget) hideTip(); });
    addEventListener("blur", hideTip);
  }

  // ---- panel (click / tap) ----
  // Opening the panel adds one history entry, so the phone/browser back button closes it
  // instead of leaving the site. Switching talks while it is open reuses that entry.
  const panel = $("#panel"), scrim = $("#scrim");
  const baseURL = () => location.pathname + location.search;
  const codeURL = (code) => "#" + encodeURIComponent(code);
  let panelEntry = false; // true while the panel owns a history entry we pushed
  function showPanel(code) {
    hideTip();
    $("#panel-body").innerHTML = detailHTML(code, true);
    panel.hidden = false;
    scrim.hidden = false;
  }
  function openPanel(code) {
    const wasOpen = !panel.hidden;
    showPanel(code);
    panel.scrollTop = 0;
    if (wasOpen && panelEntry) history.replaceState({ panel: code }, "", codeURL(code));
    else { history.pushState({ panel: code }, "", codeURL(code)); panelEntry = true; }
  }
  function refreshPanel(code) { // re-render in place (e.g. after starring) without touching history
    const top = panel.scrollTop;
    showPanel(code);
    panel.scrollTop = top;
  }
  function hidePanel() {
    panel.hidden = true;
    scrim.hidden = true;
  }
  function closePanel() {
    hidePanel();
    if (panelEntry) { panelEntry = false; history.back(); }
    else history.replaceState(null, "", baseURL());
  }
  addEventListener("popstate", (ev) => {
    const code = ev.state && ev.state.panel;
    if (code && E[code]) { showPanel(code); panelEntry = true; } // forward button
    else { hidePanel(); panelEntry = false; }
  });

  // ---- events ----
  document.addEventListener("click", (ev) => {
    const t = ev.target;
    const talk = t.closest(".talk");
    if (talk) return openPanel(talk.dataset.code);
    const tabBtn = t.closest("[data-tab]");
    if (tabBtn) { tab = tabBtn.dataset.tab; store.set("icffr-tab", tab); render(); return; }
    const themeBtn = t.closest("[data-theme]");
    if (themeBtn) {
      const k = themeBtn.dataset.theme;
      if (!k) hiddenThemes.clear(); else hiddenThemes.has(k) ? hiddenThemes.delete(k) : hiddenThemes.add(k);
      store.set("icffr-hidden-themes", [...hiddenThemes]);
      render();
      return;
    }
    const starBtn = t.closest("[data-star]");
    if (starBtn) {
      const c = starBtn.dataset.star;
      stars.has(c) ? stars.delete(c) : stars.add(c);
      store.set("icffr-stars", [...stars]);
      render();
      refreshPanel(c);
      return;
    }
    if (t === scrim || t.closest("#panel-close")) closePanel();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") { if (!panel.hidden) closePanel(); else if (query) { $("#search").value = ""; setQuery(""); } }
    if (ev.key === "/" && document.activeElement !== $("#search")) { ev.preventDefault(); $("#search").focus(); }
  });
  function setQuery(q) {
    query = fold(q.trim());
    render();
    if (query && hitsFor(tab) === 0) {
      const first = TABS.find((t) => hitsFor(t.id) > 0);
      if (first) { tab = first.id; render(); }
    }
  }
  let qTimer;
  $("#search").addEventListener("input", (ev) => { clearTimeout(qTimer); qTimer = setTimeout(() => setQuery(ev.target.value), 120); });

  addEventListener("resize", setHdr);

  render();
  setHdr();
  let hash = "";
  try { hash = decodeURIComponent(location.hash.slice(1)); } catch { /* malformed link */ }
  if (hash && E[hash]) {
    const s = (slots[hash] || [])[0];
    tab = s && !s.room.startsWith("Poster") ? s.date : E[hash].kind === "keynote" ? tab : "posters";
    render();
    // put a plain entry underneath so back from a shared link closes the panel and stays on the site
    history.replaceState(null, "", baseURL());
    openPanel(hash);
  }
  const nowRow = document.querySelector("tr.now");
  if (nowRow) nowRow.scrollIntoView({ block: "center" });
  // keep the "now" marker fresh while the page stays open
  setInterval(() => {
    Object.assign(now, lisbonNow());
    const day = S.days.find((d) => d.date === tab);
    if (!day) return;
    // only re-render when a row changes state, so scrolling isn't disturbed every minute
    const states = day.rows.map(([a, b]) => rowState(day, a, b)).join();
    const shown = [...document.querySelectorAll(".grid tbody tr")].map((tr) => tr.className).join();
    if (states !== shown) render();
  }, 60000);
})();
