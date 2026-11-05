// Tests af kortets rene logik: node --test tests/
import assert from "node:assert/strict";
import test from "node:test";

import {
  countdown,
  labels,
  level,
  pace,
  projected,
  slugOf,
  gaugeSvg,
} from "../custom_components/claude_timer/frontend/claude-timer-card.js";

const H = 3600e3;
const NOW = Date.parse("2026-11-05T12:00:00Z");
const da = {
  reached: "Grænsen er nået",
  forecast: (p) => `Prognose ved nulstilling: ${p} %`,
  hitsAt: (w) => `Med dette tempo: 100 % ${w}`,
  at: "kl.",
};

test("prognose matcher appen og integrationen", () => {
  assert.equal(projected(20, NOW + 2.5 * H, 5 * H, NOW), 40);
  assert.equal(projected(50, NOW + 4 * H, 5 * H, NOW), 250);
  assert.equal(projected(30, NOW + 4.92 * H, 5 * H, NOW), null); // for tidligt
  assert.equal(projected(30, NOW + 2 * H, null, NOW), null);
  assert.equal(pace(20, NOW + 2.5 * H, 5 * H, NOW, da, "da-DK").text, "Prognose ved nulstilling: 40 %");
  assert.match(pace(50, NOW + 4 * H, 5 * H, NOW, da, "da-DK").text, /^Med dette tempo: 100 % kl\. /);
  assert.equal(pace(100, NOW + H, 5 * H, NOW, da, "da-DK").text, "Grænsen er nået");
});

test("nedtælling som i appen", () => {
  assert.equal(countdown(NOW + 3 * 86400e3 + 4 * H + 5 * 60e3 + 6e3, NOW), "3d 04:05:06");
  assert.equal(countdown(NOW + 2 * H + 59e3, NOW), "02:00:59");
  assert.equal(countdown(NOW - 1, NOW), "00:00:00");
  assert.equal(countdown(null, NOW), "—");
});

test("overskrifter som UsageWindowLabels", () => {
  const t = {
    session: "AKTUEL SESSION", weekly: "UGENTLIG GRÆNSE", weeklyModel: (m) => `UGENTLIG · ${m.toUpperCase()}`,
    title5h: "5 timer", title7d: "7 døgn", titleModel: (m) => `${m} · 7 døgn`, titleScoped: "7 døgn (afgrænset)",
  };
  assert.deepEqual(labels({ kind: "session", group: "session" }, t), { eyebrow: "AKTUEL SESSION", title: "5 timer" });
  assert.deepEqual(labels({ kind: "weekly_all", group: "weekly" }, t), { eyebrow: "UGENTLIG GRÆNSE", title: "7 døgn" });
  assert.deepEqual(labels({ kind: "weekly_scoped", group: "weekly", model: "Fable" }, t), {
    eyebrow: "UGENTLIG · FABLE",
    title: "Fable · 7 døgn",
  });
});

test("entity-id'er og niveauer", () => {
  assert.equal(slugOf("sensor.claude_timer_session_usage"), "session");
  assert.equal(slugOf("sensor.claude_timer_weekly_fable_usage_2"), "weekly_fable");
  assert.equal(slugOf("sensor.claude_timer_session_forecast"), null);
  assert.deepEqual([49, 50, 80].map(level), ["good", "warning", "critical"]);
  assert.match(gaugeSvg(62, 120, { track: "t", muted: "m", warning: "w" }), /stroke="w"/);
});
