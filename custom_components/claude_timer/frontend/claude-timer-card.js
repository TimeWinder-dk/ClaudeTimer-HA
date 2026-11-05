/*
 * Claude Timer-kort til Home Assistant.
 *
 * Viser Claude-grænserne som i Windows-appen ClaudeTimer: ét kort per grænse med
 * stor procent, bjælke, prognose og nedtælling med sekunder – eller som målere.
 *
 *   type: custom:claude-timer-card
 *   view: cards          # cards | gauges
 *   limits: [session]    # valgfri: kun disse grænser (session, weekly, weekly_fable …)
 *   device_id: …         # valgfri: kun én konto
 *
 * Indlæses automatisk af integrationen; der skal ikke tilføjes en resource.
 */

const CARD_TAG = "claude-timer-card";

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
  },
  en: {
    session: "CURRENT SESSION", weekly: "WEEKLY LIMIT", weeklyModel: (m) => `WEEKLY · ${m.toUpperCase()}`,
    title5h: "5 hours", title7d: "7 days", titleModel: (m) => `${m} · 7 days`, titleScoped: "7 days (scoped)",
    used: "used", resetsIn: "RESETS IN", noReset: "No reset time",
    reached: "Limit reached", forecast: (p) => `Forecast at reset: ${p} %`,
    hitsAt: (w) => `At this pace: 100 % ${w}`, at: "at", noData: "No Claude Timer data yet.",
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

/** Del af entity_id mellem "sensor.claude_timer_" og "_usage", fx "weekly_fable". */
export function slugOf(entityId) {
  const m = /^sensor\.claude_timer_(.+)_usage(?:_\d+)?$/.exec(entityId);
  return m ? m[1] : null;
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
  .wrap { display: flex; flex-wrap: wrap; gap: 14px; }
  .account { width: 100%; font-size: 13px; font-weight: 600; color: var(--ct-muted); margin: 4px 2px -4px; }
  .tile {
    box-sizing: border-box; flex: 1 1 224px; max-width: 320px; min-height: 340px; padding: 26px;
    display: flex; flex-direction: column; background: var(--ct-surface); color: var(--ct-text);
    border: 1px solid var(--ct-stroke); border-radius: 14px; box-shadow: 0 3px 22px rgba(0,0,0,.07);
    font-family: "Segoe UI Variable", "Segoe UI", var(--ha-font-family-body, Roboto), sans-serif;
  }
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
  .empty { padding: 16px; color: var(--secondary-text-color); }
`;

// HTMLElement findes ikke uden browser (fx når logikken testes i node).
const Base = typeof HTMLElement !== "undefined" ? HTMLElement : class {};

class ClaudeTimerCard extends Base {
  setConfig(config) {
    if (config.view && !["cards", "gauges"].includes(config.view)) {
      throw new Error("view skal være 'cards' eller 'gauges'");
    }
    this._config = { view: "cards", ...config };
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

  _limits() {
    const hass = this._hass;
    const wanted = this._config.limits ? new Set([].concat(this._config.limits)) : null;
    return Object.values(hass.entities || {})
      .filter((e) => e.platform === "claude_timer" && slugOf(e.entity_id) && slugOf(e.entity_id) !== "extra")
      .filter((e) => !this._config.device_id || e.device_id === this._config.device_id)
      .filter((e) => !wanted || wanted.has(slugOf(e.entity_id)))
      .map((e) => ({ entry: e, state: hass.states[e.entity_id] }))
      .filter(({ state }) => state && !["unavailable", "unknown"].includes(state.state))
      .sort((a, b) => {
        const ka = KIND_ORDER[a.state.attributes.kind] ?? 9;
        const kb = KIND_ORDER[b.state.attributes.kind] ?? 9;
        return ka - kb || String(a.state.attributes.model || "").localeCompare(b.state.attributes.model || "");
      });
  }

  _tile({ state }, t, locale, colors, now) {
    const a = state.attributes;
    const percent = Number(state.state);
    const resetsAt = a.resets_at ? Date.parse(a.resets_at) : null;
    const windowMs = WINDOW_MS[a.kind] ?? (a.window_hours ? a.window_hours * 3600e3 : null);
    const lvl = level(percent);
    const { eyebrow, title } = labels(a, t);
    const p = pace(percent, resetsAt, windowMs, now, t, locale);
    const shown = `${percent.toLocaleString(locale, { maximumFractionDigits: 1 })} %`;
    const local = resetsAt
      ? `${new Date(resetsAt).toLocaleDateString(locale, { weekday: "long", day: "numeric", month: "long" })} · ${new Date(resetsAt).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`
      : t.noReset;
    const paceHtml = p.text ? `<div class="pace ${p.warning ? "warning" : ""}">${esc(p.text)}</div>` : "";

    const middle =
      this._config.view === "gauges"
        ? `<div class="gaugebox">${gaugeSvg(percent, projected(percent, resetsAt, windowMs, now), colors)}
             <div class="gaugetext"><div class="pct">${esc(shown)}</div><div class="used">${esc(t.used)}</div></div>
           </div>${paceHtml}`
        : `<div class="pct ${lvl}">${esc(shown)}</div><div class="used">${esc(t.used)}</div>
           <div class="bar"><div style="width:${Math.max(0, Math.min(100, percent))}%;background:${colors[lvl]}"></div></div>
           ${paceHtml}`;

    return `<div class="tile">
      <div><div class="eyebrow">${esc(eyebrow)}</div><div class="title">${esc(title)}</div></div>
      <div class="middle">${middle}</div>
      <div><div class="label">${esc(t.resetsIn)}</div>
        <div class="count">${esc(countdown(resetsAt, now))}</div>
        <div class="local">${esc(local)}</div></div>
    </div>`;
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });

    const hass = this._hass;
    const locale = hass.locale?.language || hass.language || "da";
    const t = locale.startsWith("da") ? TEXT.da : TEXT.en;
    const colors = hass.themes?.darkMode ? PALETTE.dark : PALETTE.light;
    const now = Date.now();
    const limits = this._limits();

    const vars = Object.entries(colors).map(([k, v]) => `--ct-${k}:${v}`).join(";");
    let body;
    if (!limits.length) {
      body = `<ha-card><div class="empty">${esc(t.noData)}</div></ha-card>`;
    } else {
      const devices = [...new Set(limits.map((l) => l.entry.device_id))];
      body = devices
        .map((id) => {
          const heading =
            devices.length > 1 ? `<div class="account">${esc(hass.devices?.[id]?.name || "")}</div>` : "";
          const tiles = limits
            .filter((l) => l.entry.device_id === id)
            .map((l) => this._tile(l, t, locale, colors, now))
            .join("");
          return heading + tiles;
        })
        .join("");
      body = `<div class="wrap ${this._config.view}" style="${vars}">${body}</div>`;
    }

    const html = `<style>${STYLE}</style>${body}`;
    if (html !== this._lastHtml) {
      this.shadowRoot.innerHTML = html;
      this._lastHtml = html;
    }
  }
}

if (typeof customElements !== "undefined" && !customElements.get(CARD_TAG)) {
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
