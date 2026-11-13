/*
 * Claude Timer-kort og -dashboard til Home Assistant.
 *
 * Viser Claude-grænserne som i Windows-appen ClaudeTimer: ét kort per grænse med
 * stor procent, bjælke, prognose og nedtælling med sekunder – eller som målere.
 * Skiftet mellem kort og målere sidder i selve kortet og huskes per side.
 *
 *   type: custom:claude-timer-card
 *   view: cards          # cards | gauges (udgangspunkt; kan skiftes i kortet)
 *   device_id: …         # valgfri: kun én konto
 *   layout: auto         # auto | compare | accounts (ved flere konti)
 *   limits: [session]    # valgfri: kun disse grænser (session, weekly, weekly_fable …)
 *   toggle: false        # valgfri: skjul skiftet mellem kort og målere
 *   refresh: false       # valgfri: skjul knappen der henter data igen
 *
 * Et helt dashboard med én fane per konto plus en oversigt:
 *
 *   strategy:
 *     type: custom:claude-timer
 *
 * Indlæses automatisk af integrationen; der skal ikke tilføjes en resource.
 */

const CARD_TAG = "claude-timer-card";
const STRATEGY_TAG = "ll-strategy-dashboard-claude-timer";

// Appens farver (Themes/ThemeManager.cs), lyst og mørkt.
const PALETTE = {
  light: {
    surface: "#FCFCFD", text: "#19191B", muted: "#66656B", stroke: "rgba(0,0,0,.094)",
    accent: "#6D52C7", track: "rgba(0,0,0,.047)", good: "#1A7F37", warning: "#B76E00", critical: "#C4320A",
  },
  dark: {
    surface: "#2A2A2E", text: "#F2F2F4", muted: "#A3A2AA", stroke: "rgba(255,255,255,.133)",
    accent: "#A08CF6", track: "rgba(255,255,255,.133)", good: "#4CC38A", warning: "#F0B429", critical: "#FF7A66",
  },
};

const TEXT = {
  da: {
    session: "AKTUEL SESSION", weekly: "UGENTLIG GRÆNSE", weeklyModel: (m) => `UGENTLIG · ${m.toUpperCase()}`,
    title5h: "5 timer", title7d: "7 døgn", titleModel: (m) => `${m} · 7 døgn`, titleScoped: "7 døgn (afgrænset)",
    used: "udnyttet", resetsIn: "NULSTILLER OM", noReset: "Intet nulstillingstidspunkt",
    reached: "Grænsen er nået", forecast: (p) => `Prognose ved nulstilling: ${p} %`,
    hitsAt: (w) => `Med dette tempo: 100 % ${w}`, at: "kl.", noData: "Ingen Claude Timer-data endnu.",
    cards: "Kort", gauges: "Målere", overview: "Oversigt", history: "Forbrug over tid",
    refresh: "Hent nu", fetched: (w) => `Hentet ${w}`, limited: (w) => `Pause til ${w} (rate-limit)`,
  },
  en: {
    session: "CURRENT SESSION", weekly: "WEEKLY LIMIT", weeklyModel: (m) => `WEEKLY · ${m.toUpperCase()}`,
    title5h: "5 hours", title7d: "7 days", titleModel: (m) => `${m} · 7 days`, titleScoped: "7 days (scoped)",
    used: "used", resetsIn: "RESETS IN", noReset: "No reset time",
    reached: "Limit reached", forecast: (p) => `Forecast at reset: ${p} %`,
    hitsAt: (w) => `At this pace: 100 % ${w}`, at: "at", noData: "No Claude Timer data yet.",
    cards: "Cards", gauges: "Gauges", overview: "Overview", history: "Usage over time",
    refresh: "Refresh", fetched: (w) => `Fetched ${w}`, limited: (w) => `Paused until ${w} (rate limit)`,
  },
};

const WINDOW_MS = { session: 5 * 3600e3, weekly_all: 7 * 86400e3, weekly_scoped: 7 * 86400e3 };
const KIND_ORDER = { session: 0, weekly_all: 1, weekly_scoped: 2 };

// ---------- Ren logik (spejler UsageCardViewModel / usage.py) ----------

export function level(percent) {
  return percent >= 80 ? "critical" : percent >= 50 ? "warning" : "good";
}

/** Forventet forbrug ved nulstilling, eller null når en prognose kun er støj. */
export function projected(percent, resetsAt, windowMs, now) {
  if (percent >= 100) return percent;
  if (!resetsAt || !windowMs || resetsAt <= now) return null;
  const elapsed = windowMs - (resetsAt - now);
  const minimum = Math.max(windowMs / 20, 10 * 60e3);
  if (elapsed < minimum || percent < 1) return null;
  return percent * (windowMs / elapsed);
}

export function pace(percent, resetsAt, windowMs, now, t, locale) {
  if (percent >= 100) return { text: t.reached, warning: true };
  const p = projected(percent, resetsAt, windowMs, now);
  if (p === null) return { text: "", warning: false };
  if (p < 100) return { text: t.forecast(Math.round(p)), warning: false };
  const elapsed = windowMs - (resetsAt - now);
  const hits = new Date(now + elapsed * ((100 - percent) / percent));
  const time = hits.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  const sameDay = hits.toDateString() === new Date(now).toDateString();
  const when = sameDay
    ? `${t.at} ${time}`
    : `${hits.toLocaleDateString(locale, { weekday: "short" })} ${t.at} ${time}`;
  return { text: t.hitsAt(when), warning: true };
}

const pad = (n) => String(n).padStart(2, "0");

/** Som appen: "3d 04:12:09" eller "04:12:09". */
export function countdown(resetsAt, now) {
  if (!resetsAt) return "—";
  const ms = resetsAt - now;
  if (ms <= 0) return "00:00:00";
  const s = Math.floor(ms / 1000);
  const d = Math.floor(s / 86400);
  const hms = `${pad(Math.floor((s % 86400) / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
  return d >= 1 ? `${d}d ${hms}` : hms;
}

export function labels(attrs, t) {
  const kind = attrs.kind || "";
  const model = attrs.model || "";
  const humanize = (k) => (k ? k[0].toUpperCase() + k.slice(1).replace(/_/g, " ") : "");
  let eyebrow;
  if (attrs.group === "session" || kind === "session") eyebrow = t.session;
  else if (attrs.group === "weekly") eyebrow = model ? t.weeklyModel(model) : t.weekly;
  else eyebrow = humanize(kind).toUpperCase();
  let title;
  if (kind === "session") title = t.title5h;
  else if (kind === "weekly_all") title = t.title7d;
  else if (kind === "weekly_scoped") title = model ? t.titleModel(model) : t.titleScoped;
  else title = humanize(kind);
  return { eyebrow, title };
}

const textFor = (hass) => ((hass?.locale?.language || hass?.language || "da").startsWith("da") ? TEXT.da : TEXT.en);

/** Del af entity_id mellem "sensor.claude_timer_" og "_usage", fx "weekly_fable". */
export function slugOf(entityId) {
  const m = /^sensor\.claude_timer_(.+)_usage(?:_\d+)?$/.exec(entityId);
  return m ? m[1] : null;
}

/** Visningsnavn for en konto: brugerens eget navn først, uden "Claude · "-præfikset. */
export function accountName(device) {
  const name = device?.name_by_user || device?.name || "";
  return name.replace(/^Claude\s*·\s*/, "").trim() || "Claude";
}

/** Konti sorteret efter navn; ens navne får (2), (3) … så fanerne kan skelnes. */
export function accountList(deviceIds, devices) {
  const list = deviceIds
    .map((id) => ({ id, name: accountName(devices?.[id]) }))
    .sort((a, b) => a.name.localeCompare(b.name) || String(a.id).localeCompare(String(b.id)));
  const seen = {};
  for (const a of list) {
    seen[a.name] = (seen[a.name] || 0) + 1;
    if (seen[a.name] > 1) a.name = `${a.name} (${seen[a.name]})`;
  }
  return list;
}

/** URL-sikker sti til en fane, fx "Thomas THHA" -> "thomas-thha", "Søren Ågård" -> "soeren-aagaard". */
export function viewPath(name) {
  const map = { æ: "ae", ø: "oe", å: "aa" };
  return (
    name
      .toLowerCase()
      .replace(/[æøå]/g, (c) => map[c])
      .normalize("NFD")
      .replace(/\p{M}/gu, "")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "konto"
  );
}

/** Claude Timer-forbrugssensorer i registeret, evt. kun for én enhed. */
function usageEntries(hass, deviceId) {
  return Object.values(hass.entities || {}).filter(
    (e) =>
      e.platform === "claude_timer" &&
      slugOf(e.entity_id) &&
      slugOf(e.entity_id) !== "extra" &&
      (!deviceId || e.device_id === deviceId),
  );
}

// ---------- Tegning ----------

const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function arcPath(cx, cy, r, from, to) {
  const a0 = ((150 + 240 * from / 100) * Math.PI) / 180;
  const a1 = ((150 + 240 * to / 100) * Math.PI) / 180;
  const large = 240 * (to - from) / 100 > 180 ? 1 : 0;
  const p = (a) => `${(cx + r * Math.cos(a)).toFixed(2)} ${(cy + r * Math.sin(a)).toFixed(2)}`;
  return `M ${p(a0)} A ${r} ${r} 0 ${large} 1 ${p(a1)}`;
}

/** Samme måler som UsageGauge.cs: bue i niveaufarven, svag bue + markør ved prognosen. */
export function gaugeSvg(percent, forecast, colors) {
  const cx = 100, cy = 92, r = 78, w = 13;
  const clamp = (v) => Math.max(0, Math.min(100, v));
  const value = clamp(percent);
  let parts = `<path d="${arcPath(cx, cy, r, 0, 100)}" stroke="${colors.track}" />`;
  if (forecast !== null && forecast !== undefined) {
    const f = clamp(forecast);
    if (f > value) {
      parts += `<path d="${arcPath(cx, cy, r, value, f)}" stroke="${colors.muted}" stroke-opacity=".28" />`;
    }
    const a = ((150 + 240 * f / 100) * Math.PI) / 180;
    const x = (k) => (cx + (r + k) * Math.cos(a)).toFixed(2);
    const y = (k) => (cy + (r + k) * Math.sin(a)).toFixed(2);
    parts += `<line x1="${x(-w * 0.95)}" y1="${y(-w * 0.95)}" x2="${x(w * 0.95)}" y2="${y(w * 0.95)}" stroke="${colors.muted}" stroke-width="2.5" />`;
  }
  if (value > 0) parts += `<path d="${arcPath(cx, cy, r, 0, value)}" stroke="${colors[level(percent)]}" />`;
  return `<svg viewBox="0 0 200 160" class="gauge" aria-hidden="true">
    <g fill="none" stroke-width="${w}" stroke-linecap="round">${parts}</g></svg>`;
}


const STYLE = `
  :host { display: block; }
  .toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 8px; margin-bottom: 12px; }
  .status { font-size: 12px; color: var(--ct-muted); }
  .status.limited { color: var(--ct-warning); font-weight: 600; }
  .icon-btn {
    display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; padding: 0;
    border-radius: 10px; border: 1px solid var(--ct-stroke); background: var(--ct-surface); color: var(--ct-muted);
    cursor: pointer; --mdc-icon-size: 20px;
  }
  .icon-btn:hover { color: var(--ct-text); }
  .icon-btn:disabled { cursor: default; opacity: .6; }
  .icon-btn:focus-visible { outline: 2px solid var(--ct-accent); outline-offset: 1px; }
  .icon-btn.busy ha-icon { animation: spin 1s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .seg {
    display: inline-flex; padding: 3px; gap: 2px; border-radius: 10px;
    background: var(--ct-surface); border: 1px solid var(--ct-stroke);
  }
  .seg button {
    display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border: 0; border-radius: 7px;
    background: none; color: var(--ct-muted); font: 600 13px "Segoe UI Variable", "Segoe UI", var(--ha-font-family-body, Roboto), sans-serif;
    cursor: pointer; --mdc-icon-size: 18px;
  }
  .seg button:hover { color: var(--ct-text); }
  .seg button[aria-pressed="true"] { background: var(--ct-track); color: var(--ct-text); }
  .seg button:focus-visible { outline: 2px solid var(--ct-accent); outline-offset: 1px; }
  .wrap { display: flex; flex-wrap: wrap; gap: 14px; }
  .account { width: 100%; font-size: 13px; font-weight: 600; color: var(--ct-muted); margin: 4px 2px -4px; }
  .tile {
    box-sizing: border-box; flex: 1 1 224px; max-width: 320px; min-height: 340px; padding: 26px;
    display: flex; flex-direction: column; background: var(--ct-surface); color: var(--ct-text);
    border: 1px solid var(--ct-stroke); border-radius: 14px; box-shadow: 0 3px 22px rgba(0,0,0,.07);
    font-family: "Segoe UI Variable", "Segoe UI", var(--ha-font-family-body, Roboto), sans-serif;
  }
  .tile.wide { flex: 1 1 340px; max-width: 520px; min-height: 0; }
  .eyebrow { font-size: 11px; font-weight: 600; color: var(--ct-accent); letter-spacing: .02em; }
  .title { margin-top: 5px; font-size: 22px; font-weight: 600; }
  .middle { flex: 1; display: flex; flex-direction: column; justify-content: center; padding: 10px 0; }
  .pct { font-size: 54px; font-weight: 600; line-height: 1.1; }
  .pct.warning { color: var(--ct-warning); } .pct.critical { color: var(--ct-critical); }
  .used { margin-left: 2px; font-size: 13px; color: var(--ct-muted); }
  .bar { margin-top: 18px; height: 8px; border-radius: 4px; background: var(--ct-track); overflow: hidden; }
  .bar > div { height: 100%; border-radius: 4px; }
  .pace { margin-top: 8px; font-size: 12px; color: var(--ct-muted); }
  .pace.warning { color: var(--ct-critical); font-weight: 600; }
  .gaugebox { position: relative; height: 136px; }
  .gauge { width: 100%; height: 100%; }
  .gaugetext { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; padding-top: 8px; }
  .gaugetext .pct { font-size: 34px; }
  .gaugetext .used { margin: 0; font-size: 12px; }
  .gauges .pace { text-align: center; margin-top: 2px; }
  .label { font-size: 11px; font-weight: 600; color: var(--ct-muted); }
  .count { margin-top: 4px; font-family: "Cascadia Mono", Consolas, ui-monospace, monospace; font-size: 22px; font-weight: 600; }
  .local { margin-top: 7px; font-size: 12px; color: var(--ct-muted); }
  .rows { margin-top: 18px; display: flex; flex-direction: column; gap: 18px; }
  .row .head, .row .foot { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
  .who { font-size: 14px; font-weight: 600; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .row .pct { font-size: 28px; }
  .row .bar { margin-top: 6px; }
  .row .foot { margin-top: 6px; }
  .row .pace { margin-top: 0; }
  .row .count, .mini .count { margin-top: 0; font-size: 14px; white-space: nowrap; }
  .minis { margin-top: 14px; display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); gap: 14px 8px; }
  .mini { text-align: center; min-width: 0; }
  .mini .gaugebox { height: 92px; }
  .mini .gaugetext { padding-top: 6px; }
  .mini .gaugetext .pct { font-size: 22px; }
  .mini .who { font-size: 13px; margin-top: 2px; }
  .mini .count { color: var(--ct-muted); margin-top: 2px; }
  .empty { padding: 16px; color: var(--secondary-text-color); }
`;

// HTMLElement findes ikke uden browser (fx når logikken testes i node).
const Base = typeof HTMLElement !== "undefined" ? HTMLElement : class {};

const storage = {
  get(key) {
    try { return window.localStorage.getItem(key); } catch { return null; }
  },
  set(key, value) {
    try { window.localStorage.setItem(key, value); } catch { /* privat vindue o.l. */ }
  },
};

/** Tal, nulstilling, prognose og tekster for én grænse. */
function limitInfo({ state }, t, locale, now) {
  const a = state.attributes;
  const percent = Number(state.state);
  const resetsAt = a.resets_at ? Date.parse(a.resets_at) : null;
  const windowMs = WINDOW_MS[a.kind] ?? (a.window_hours ? a.window_hours * 3600e3 : null);
  const local = resetsAt
    ? `${new Date(resetsAt).toLocaleDateString(locale, { weekday: "long", day: "numeric", month: "long" })} · ${new Date(resetsAt).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`
    : t.noReset;
  return {
    percent,
    resetsAt,
    lvl: level(percent),
    shown: `${percent.toLocaleString(locale, { maximumFractionDigits: 1 })} %`,
    pace: pace(percent, resetsAt, windowMs, now, t, locale),
    forecast: projected(percent, resetsAt, windowMs, now),
    local,
    ...labels(a, t),
  };
}

const barHtml = (i, colors) =>
  `<div class="bar"><div style="width:${Math.max(0, Math.min(100, i.percent))}%;background:${colors[i.lvl]}"></div></div>`;

class ClaudeTimerCard extends Base {
  setConfig(config) {
    if (config.view && !["cards", "gauges"].includes(config.view)) {
      throw new Error("view skal være 'cards' eller 'gauges'");
    }
    if (config.layout && !["auto", "compare", "accounts"].includes(config.layout)) {
      throw new Error("layout skal være 'auto', 'compare' eller 'accounts'");
    }
    this._config = { view: "cards", layout: "auto", toggle: true, ...config };
    const saved = this._config.toggle ? storage.get(this._storageKey()) : null;
    this._view = ["cards", "gauges"].includes(saved) ? saved : this._config.view;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  static getStubConfig() {
    return { view: "cards" };
  }

  getCardSize() {
    return 7;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  connectedCallback() {
    this._timer = setInterval(() => this._render(), 1000);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
  }

  _storageKey() {
    return `claude-timer-card.view.${this._config.device_id || "all"}`;
  }

  _setView(view) {
    if (view === this._view) return;
    this._view = view;
    storage.set(this._storageKey(), view);
    this._render();
  }

  /** "Sidst hentet"-sensorerne for de viste konti; bruges til at hente igen og vise status. */
  _fetchers(deviceIds) {
    const hass = this._hass;
    return Object.values(hass.entities || {})
      .filter((e) => e.platform === "claude_timer" && /^sensor\.claude_timer_last_fetched(?:_\d+)?$/.test(e.entity_id))
      .filter((e) => deviceIds.has(e.device_id))
      .map((e) => hass.states[e.entity_id])
      .filter(Boolean);
  }

  async _refresh() {
    if (this._busy) return;
    const ids = this._fetchers(new Set(this._limits().map((l) => l.entry.device_id))).map((s) => s.entity_id);
    if (!ids.length) return;
    this._busy = true;
    this._render();
    const started = Date.now();
    try {
      // CoordinatorEntity.async_update -> async_request_refresh: debounced og respekterer 429-pausen.
      await this._hass.callService("homeassistant", "update_entity", { entity_id: ids });
    } catch (err) {
      console.warn("Claude Timer: kunne ikke hente igen", err);
    } finally {
      setTimeout(() => {
        this._busy = false;
        this._render();
      }, Math.max(0, 700 - (Date.now() - started)));
    }
  }

  _status(t, locale, now) {
    const states = this._fetchers(new Set(this._limits().map((l) => l.entry.device_id)));
    const when = (ms) => {
      const d = new Date(ms);
      const time = d.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
      return d.toDateString() === new Date(now).toDateString()
        ? time
        : `${d.toLocaleDateString(locale, { weekday: "short" })} ${time}`;
    };
    const limited = states
      .map((s) => Date.parse(s.attributes.rate_limited_until || ""))
      .filter((ms) => ms > now);
    if (limited.length) return { text: t.limited(when(Math.max(...limited))), limited: true };
    const fetched = states.map((s) => Date.parse(s.state)).filter((ms) => !Number.isNaN(ms));
    return fetched.length ? { text: t.fetched(when(Math.min(...fetched))), limited: false } : { text: "", limited: false };
  }

  _limits() {
    const hass = this._hass;
    const wanted = this._config.limits ? new Set([].concat(this._config.limits)) : null;
    return usageEntries(hass, this._config.device_id)
      .filter((e) => !wanted || wanted.has(slugOf(e.entity_id)))
      .map((e) => ({ entry: e, slug: slugOf(e.entity_id), state: hass.states[e.entity_id] }))
      .filter(({ state }) => state && !["unavailable", "unknown"].includes(state.state))
      .sort((a, b) => {
        const ka = KIND_ORDER[a.state.attributes.kind] ?? 9;
        const kb = KIND_ORDER[b.state.attributes.kind] ?? 9;
        return ka - kb || String(a.state.attributes.model || "").localeCompare(b.state.attributes.model || "");
      });
  }

  /** Ét kort for én grænse på én konto (som i appen). */
  _tile(limit, t, locale, colors, now) {
    const i = limitInfo(limit, t, locale, now);
    const paceHtml = i.pace.text ? `<div class="pace ${i.pace.warning ? "warning" : ""}">${esc(i.pace.text)}</div>` : "";
    const middle =
      this._view === "gauges"
        ? `<div class="gaugebox">${gaugeSvg(i.percent, i.forecast, colors)}
             <div class="gaugetext"><div class="pct">${esc(i.shown)}</div><div class="used">${esc(t.used)}</div></div>
           </div>${paceHtml}`
        : `<div class="pct ${i.lvl}">${esc(i.shown)}</div><div class="used">${esc(t.used)}</div>
           ${barHtml(i, colors)}${paceHtml}`;

    return `<div class="tile">
      <div><div class="eyebrow">${esc(i.eyebrow)}</div><div class="title">${esc(i.title)}</div></div>
      <div class="middle">${middle}</div>
      <div><div class="label">${esc(t.resetsIn)}</div>
        <div class="count">${esc(countdown(i.resetsAt, now))}</div>
        <div class="local">${esc(i.local)}</div></div>
    </div>`;
  }

  /** Ét kort for én grænse med alle konti: rækker med tekst eller små målere. */
  _compareTile(group, names, t, locale, colors, now) {
    const head = limitInfo(group[0], t, locale, now);
    const items = group.map((l) => ({ name: names[l.entry.device_id], i: limitInfo(l, t, locale, now) }));
    const body =
      this._view === "gauges"
        ? `<div class="minis">${items
            .map(
              ({ name, i }) => `<div class="mini" title="${esc(i.pace.text || i.local)}">
                <div class="gaugebox">${gaugeSvg(i.percent, i.forecast, colors)}
                  <div class="gaugetext"><div class="pct">${esc(i.shown)}</div></div></div>
                <div class="who">${esc(name)}</div>
                <div class="count" title="${esc(i.local)}">${esc(countdown(i.resetsAt, now))}</div>
              </div>`,
            )
            .join("")}</div>`
        : `<div class="rows">${items
            .map(
              ({ name, i }) => `<div class="row">
                <div class="head"><span class="who">${esc(name)}</span><span class="pct ${i.lvl}">${esc(i.shown)}</span></div>
                ${barHtml(i, colors)}
                <div class="foot"><span class="pace ${i.pace.warning ? "warning" : ""}">${esc(i.pace.text)}</span>
                  <span class="count" title="${esc(i.local)}">${esc(countdown(i.resetsAt, now))}</span></div>
              </div>`,
            )
            .join("")}</div>`;
    return `<div class="tile wide">
      <div><div class="eyebrow">${esc(head.eyebrow)}</div><div class="title">${esc(head.title)}</div></div>
      ${body}
    </div>`;
  }

  _content(t, locale, colors, now) {
    const hass = this._hass;
    const limits = this._limits();
    if (!limits.length) return `<ha-card><div class="empty">${esc(t.noData)}</div></ha-card>`;

    const accounts = accountList([...new Set(limits.map((l) => l.entry.device_id))], hass.devices);
    const names = Object.fromEntries(accounts.map((a) => [a.id, a.name]));
    const multi = accounts.length > 1;
    const layout = this._config.layout === "auto" ? (multi ? "compare" : "accounts") : this._config.layout;

    let body;
    if (layout === "compare") {
      const order = Object.fromEntries(accounts.map((a, n) => [a.id, n]));
      const groups = new Map();
      for (const l of limits) groups.set(l.slug, [...(groups.get(l.slug) || []), l]);
      body = [...groups.values()]
        .map((g) => g.sort((a, b) => order[a.entry.device_id] - order[b.entry.device_id]))
        .map((g) => this._compareTile(g, names, t, locale, colors, now))
        .join("");
    } else {
      body = accounts
        .map(({ id, name }) => {
          const heading = multi ? `<div class="account">${esc(name)}</div>` : "";
          const tiles = limits
            .filter((l) => l.entry.device_id === id)
            .map((l) => this._tile(l, t, locale, colors, now))
            .join("");
          return heading + tiles;
        })
        .join("");
    }
    return `<div class="wrap ${this._view}">${body}</div>`;
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.innerHTML = `<style>${STYLE}</style><div class="root"><div class="toolbar"></div><div class="content"></div></div>`;
      this.shadowRoot.addEventListener("click", (ev) => {
        const button = ev.target.closest?.("[data-view]");
        if (button) this._setView(button.dataset.view);
        if (ev.target.closest?.("[data-action=refresh]")) this._refresh();
      });
    }

    const hass = this._hass;
    const locale = hass.locale?.language || hass.language || "da";
    const t = textFor(hass);
    const colors = hass.themes?.darkMode ? PALETTE.dark : PALETTE.light;
    const root = this.shadowRoot.querySelector(".root");
    const toolbar = this.shadowRoot.querySelector(".toolbar");
    const content = this.shadowRoot.querySelector(".content");

    const vars = Object.entries(colors).map(([k, v]) => `--ct-${k}:${v}`).join(";");
    if (root.getAttribute("style") !== vars) root.setAttribute("style", vars);

    // Værktøjslinjen tegnes kun om, når den ændrer sig, så fokus og hover bevares.
    const now = Date.now();
    const status = this._status(t, locale, now);
    const statusHtml = status.text ? `<span class="status ${status.limited ? "limited" : ""}">${esc(status.text)}</span>` : "";
    const refreshHtml = `<button type="button" class="icon-btn ${this._busy ? "busy" : ""}" data-action="refresh"
      title="${esc(t.refresh)}" aria-label="${esc(t.refresh)}" ${this._busy ? "disabled" : ""}><ha-icon icon="mdi:refresh"></ha-icon></button>`;
    const segHtml = this._config.toggle
      ? `<div class="seg" role="group">${[
          ["cards", "mdi:card-text-outline", t.cards],
          ["gauges", "mdi:gauge", t.gauges],
        ]
          .map(
            ([v, icon, label]) =>
              `<button type="button" data-view="${v}" aria-pressed="${this._view === v}"><ha-icon icon="${icon}"></ha-icon>${esc(label)}</button>`,
          )
          .join("")}</div>`
      : "";
    const toolbarHtml = this._config.refresh === false ? statusHtml + segHtml : statusHtml + refreshHtml + segHtml;
    if (toolbarHtml !== this._lastToolbar) {
      toolbar.innerHTML = toolbarHtml;
      toolbar.hidden = !toolbarHtml;
      this._lastToolbar = toolbarHtml;
    }

    const html = this._content(t, locale, colors, now);
    if (html !== this._lastHtml) {
      content.innerHTML = html;
      this._lastHtml = html;
    }
  }
}

// ---------- Dashboard: én fane per konto plus en oversigt ----------

/** Dashboard-konfiguration til strategy: type: custom:claude-timer. */
export function generateDashboard(hass, options = {}) {
  const t = textFor(hass);
  const entries = usageEntries(hass);
  const accounts = accountList([...new Set(entries.map((e) => e.device_id))], hass.devices);
  const history = (entities) => ({
    type: "history-graph",
    title: t.history,
    hours_to_show: options.hours_to_show ?? 168,
    entities: entities.map((entity) => ({ entity })),
  });
  const page = (title, path, card, entities) => ({
    title,
    path,
    type: "panel",
    cards: [{ type: "vertical-stack", cards: entities.length ? [card, history(entities)] : [card] }],
  });
  const card = (extra) => ({ type: "custom:claude-timer-card", view: options.view ?? "cards", ...extra });
  const sorted = (list) => list.map((e) => e.entity_id).sort();

  const views = [];
  if (accounts.length !== 1) {
    // Oversigten: hver grænse med alle konti; historikken viser ugeforbruget per konto.
    const weekly = entries.filter((e) => slugOf(e.entity_id) === "weekly");
    views.push(page(t.overview, "oversigt", card({ layout: "compare" }), sorted(weekly)));
  }
  const used = new Set(["oversigt"]);
  for (const { id, name } of accounts) {
    let path = viewPath(name);
    for (let n = 2; used.has(path); n++) path = `${viewPath(name)}-${n}`;
    used.add(path);
    views.push(page(name, path, card({ device_id: id }), sorted(entries.filter((e) => e.device_id === id))));
  }
  return { title: "Claude", views };
}

class ClaudeTimerStrategy extends Base {
  static async generate(config, hass) {
    return generateDashboard(hass, config);
  }
}

if (typeof customElements !== "undefined") {
  if (!customElements.get(STRATEGY_TAG)) customElements.define(STRATEGY_TAG, ClaudeTimerStrategy);
  if (!customElements.get(CARD_TAG)) {
    customElements.define(CARD_TAG, ClaudeTimerCard);
    window.customCards = window.customCards || [];
    window.customCards.push({
      type: CARD_TAG,
      name: "Claude Timer",
      description: "Claude-forbrug som kort eller målere, med nedtælling og prognose – som i ClaudeTimer-appen.",
      preview: true,
      documentationURL: "https://github.com/TimeWinder-dk/ClaudeTimer-HA",
    });
  }
}
