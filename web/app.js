/* 古籍补纸配片前端：录入草稿 → POST /api/solve → 渲染配片结果。 */
"use strict";

const state = {
  damageCount: 3,
  remnantCount: 4,
};

const $ = (id) => document.getElementById(id);

/* ---------------- 草稿卡片 ---------------- */

function damageCard(i) {
  return `
  <div class="card" data-kind="damage" data-i="${i}">
    <div class="row">
      <span class="title">破损 ${i + 1}</span>
      <label>宽<input type="number" min="1" step="1" data-f="width" value="3"></label>
      <label>高<input type="number" min="1" step="1" data-f="height" value="3"></label>
      <label>相位≥<input type="number" min="0" step="1" data-f="plo" value="" placeholder="不限" class="wide"></label>
      <label>相位≤<input type="number" min="0" step="1" data-f="phi" value="" placeholder="不限" class="wide"></label>
    </div>
  </div>`;
}

function remnantCard(i) {
  const period = 4;
  return `
  <div class="card" data-kind="remnant" data-i="${i}">
    <div class="row">
      <span class="title">边料 ${i + 1}</span>
      <label>宽<input type="number" min="1" step="1" data-f="width" value="10"></label>
      <label>高<input type="number" min="1" step="1" data-f="height" value="8"></label>
      <label>周期<input type="number" min="1" step="1" data-f="period" value="${period}"></label>
      <label>原点<input type="number" step="1" data-f="origin" value="0"></label>
      <label>可用次数<input type="number" min="1" step="1" data-f="uses" value="1"></label>
    </div>
  </div>`;
}

function renderCards() {
  $("damages").innerHTML =
    Array.from({ length: state.damageCount }, (_, i) => damageCard(i)).join("");
  $("remnants").innerHTML =
    Array.from({ length: state.remnantCount }, (_, i) => remnantCard(i)).join("");
  $("dmg-count").textContent = state.damageCount;
  $("rem-count").textContent = state.remnantCount;
}

function intVal(input, fallback = null) {
  if (input.value.trim() === "") return fallback;
  const v = Number(input.value);
  return Number.isInteger(v) ? v : fallback;
}

function collectPayload() {
  const damages = [...document.querySelectorAll('.card[data-kind="damage"]')]
    .map((card) => {
      const get = (f) => card.querySelector(`[data-f="${f}"]`);
      const d = {
        width: intVal(get("width")),
        height: intVal(get("height")),
      };
      // 两个相位输入都留空表示不限制；只填上限时下限按 0
      const hasLo = get("plo").value.trim() !== "";
      const hasHi = get("phi").value.trim() !== "";
      if (hasLo || hasHi) {
        const lo = intVal(get("plo"), 0);
        const hi = intVal(get("phi"), lo);
        d.phaseRange = { lo, hi: Math.max(lo, hi) };
      }
      return d;
    });

  const remnants = [...document.querySelectorAll('.card[data-kind="remnant"]')]
    .map((card) => {
      const get = (f) => card.querySelector(`[data-f="${f}"]`);
      return {
        width: intVal(get("width")),
        height: intVal(get("height")),
        period: intVal(get("period")),
        origin: intVal(get("origin"), 0),
        uses: intVal(get("uses"), 1),
      };
    });

  return { damages, remnants };
}

/* ---------------- 结果渲染 ---------------- */

function setStatus(kind, text) {
  const el = $("status");
  el.className = `status ${kind}`;
  el.textContent = text;
}

function renderFeasible(res) {
  setStatus("ok", "✓ 已求得最优配片方案");
  const s = $("summary");
  s.classList.remove("hidden");
  s.innerHTML = `
    使用边料 <b>${res.distinctRemnantCount}</b> 张
    （序号：${res.usedRemnants.map((i) => i + 1).join("、")}）；
    实际补入面积 <b>${res.cutArea}</b>；
    占用边料可裁面积 <b>${res.occupiedRemnantArea}</b>；
    裁切废料总面积 <b>${res.wasteArea}</b>。`;

  const box = $("placements");
  box.innerHTML = res.placements.map((p, i) => {
    const seam = i > 0
      ? `<div class="seam">↔ 与破损${i}接缝：左缘相位 ${p.phaseLeft} ＝ 前片右缘相位 ${res.placements[i - 1].phaseRight}（周期折算相等）</div>`
      : `<div class="seam">起始破损，左缘相位 ${p.phaseLeft}</div>`;
    return `
    <div class="p-item">
      <b>破损 ${p.damage + 1}</b>：选用
      <b>边料 ${p.remnant + 1}</b>，裁切起点
      (<b>x=${p.x}, y=${p.y}</b>)，裁片 ${p.width}×${p.height}
      → 右缘 x=${p.x + p.width}（不越界）。
      <div>左缘水印相位 <span class="ph">${p.phaseLeft}</span>，
           右缘水印相位 <span class="ph">${p.phaseRight}</span></div>
      ${seam}
    </div>`;
  }).join("");

  $("evidence").classList.add("hidden");
  drawLayout(res);
}

function renderInfeasible(res) {
  setStatus("err", "✗ 无可行配片方案");
  $("summary").classList.add("hidden");
  $("placements").innerHTML = "";
  $("canvas-wrap").classList.add("hidden");
  const ev = $("evidence");
  ev.classList.remove("hidden");
  const where = [];
  if (res.evidence.damage !== undefined && res.evidence.damage !== null)
    where.push(`破损 ${res.evidence.damage + 1}`);
  if (res.evidence.remnant !== undefined && res.evidence.remnant !== null)
    where.push(`边料 ${res.evidence.remnant + 1}`);
  ev.innerHTML = `
    <div><b>首条约束证据</b>${where.length ? "（" + where.join(" / ") + "）" : ""}</div>
    <div>约束代码：<code>${res.evidence.code}</code></div>
    <div>${res.evidence.message}</div>
    ${res.evidence.detail ? `<div><code>${JSON.stringify(res.evidence.detail)}</code></div>` : ""}`;
}

/* ---------------- 排料示意 ---------------- */

function drawLayout(res) {
  const wrap = $("canvas-wrap");
  wrap.classList.remove("hidden");
  const cv = $("canvas");
  const ctx = cv.getContext("2d");
  const W = cv.width, H = cv.height;
  ctx.clearRect(0, 0, W, H);

  // 收集使用到的边料矩形（从裁片位置反推边料尺寸）
  const byRemnant = new Map();
  for (const p of res.placements) {
    if (!byRemnant.has(p.remnant)) byRemnant.set(p.remnant, []);
    byRemnant.get(p.remnant).push(p);
  }
  const remnantDims = collectRemnantDims();
  const remIds = [...byRemnant.keys()].sort((a, b) => a - b);

  const pad = 18, gap = 24;
  const totalW = W - pad * 2 - gap * (remIds.length - 1);
  const scale = Math.min(
    ...remIds.map((id) => {
      const [w, h] = remnantDims[id];
      return Math.min(totalW / remIds.length / w, (H - pad * 2 - 30) / h);
    })
  );

  let cx = pad;
  remIds.forEach((id) => {
    const [w, h] = remnantDims[id];
    const rw = w * scale, rh = h * scale;
    ctx.fillStyle = "#efe3cd";
    ctx.strokeStyle = "#8a5a2b";
    ctx.lineWidth = 1.5;
    ctx.fillRect(cx, pad, rw, rh);
    ctx.strokeRect(cx, pad, rw, rh);
    ctx.fillStyle = "#6f4520";
    ctx.font = "12px serif";
    ctx.fillText(`边料${id + 1} (${w}×${h})`, cx + 4, pad - 5);

    const palette = ["#c75b39", "#39745e", "#3f5fa5", "#9a6a1c", "#7a3f7a"];
    byRemnant.get(id).forEach((p) => {
      ctx.fillStyle = palette[p.damage % palette.length] + "cc";
      ctx.fillRect(cx + p.x * scale, pad + p.y * scale,
                   p.width * scale, p.height * scale);
      ctx.strokeStyle = "#fff";
      ctx.strokeRect(cx + p.x * scale, pad + p.y * scale,
                     p.width * scale, p.height * scale);
      ctx.fillStyle = "#fff";
      ctx.font = "bold 11px serif";
      ctx.fillText(`${p.damage + 1}`,
                   cx + p.x * scale + 3, pad + p.y * scale + 13);
    });
    cx += rw + gap;
  });
  $("canvas-note").textContent =
    "数字为破损序号；矩形位置即整数裁切起点，不同破损互不重叠且不越出边料边界。";
}

function collectRemnantDims() {
  const dims = {};
  document.querySelectorAll('.card[data-kind="remnant"]').forEach((card) => {
    const i = Number(card.dataset.i);
    dims[i] = [intVal(card.querySelector('[data-f="width"]')),
               intVal(card.querySelector('[data-f="height"]'))];
  });
  return dims;
}

/* ---------------- 交互 ---------------- */

async function solve() {
  const payload = collectPayload();
  let res;
  try {
    const resp = await fetch("/api/solve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    res = await resp.json();
  } catch (e) {
    setStatus("err", "请求失败：" + e.message);
    return;
  }
  if (res.feasible) renderFeasible(res);
  else renderInfeasible(res);
}

function loadSample() {
  // 3 处破损、4 张边料：演示接缝相位约束与"不为单片最省而耗尽纹样"
  const sample = {
    damages: [
      { width: 2, height: 2, phaseRange: { lo: 0, hi: 3 } },
      { width: 3, height: 2, phaseRange: { lo: 0, hi: 3 } },
      { width: 2, height: 2, phaseRange: { lo: 0, hi: 3 } },
    ],
    remnants: [
      { width: 6, height: 5, period: 4, origin: 0, uses: 3 },
      { width: 5, height: 4, period: 4, origin: 1, uses: 1 },
      { width: 7, height: 6, period: 4, origin: 2, uses: 1 },
      { width: 4, height: 3, period: 4, origin: 0, uses: 1 },
    ],
  };
  state.damageCount = sample.damages.length;
  state.remnantCount = sample.remnants.length;
  renderCards();
  document.querySelectorAll('.card[data-kind="damage"]').forEach((card, i) => {
    const d = sample.damages[i];
    card.querySelector('[data-f="width"]').value = d.width;
    card.querySelector('[data-f="height"]').value = d.height;
    card.querySelector('[data-f="plo"]').value = d.phaseRange.lo;
    card.querySelector('[data-f="phi"]').value = d.phaseRange.hi;
  });
  document.querySelectorAll('.card[data-kind="remnant"]').forEach((card, i) => {
    const r = sample.remnants[i];
    card.querySelector('[data-f="width"]').value = r.width;
    card.querySelector('[data-f="height"]').value = r.height;
    card.querySelector('[data-f="period"]').value = r.period;
    card.querySelector('[data-f="origin"]').value = r.origin;
    card.querySelector('[data-f="uses"]').value = r.uses;
  });
}

function bind() {
  $("dmg-plus").onclick = () => {
    if (state.damageCount < 5) { state.damageCount++; renderCards(); }
  };
  $("dmg-minus").onclick = () => {
    if (state.damageCount > 3) { state.damageCount--; renderCards(); }
  };
  $("rem-plus").onclick = () => {
    if (state.remnantCount < 8) { state.remnantCount++; renderCards(); }
  };
  $("rem-minus").onclick = () => {
    if (state.remnantCount > 4) { state.remnantCount--; renderCards(); }
  };
  $("btn-solve").onclick = solve;
  $("btn-sample").onclick = loadSample;
  $("btn-clear").onclick = () => {
    setStatus("idle", "尚未发起配片");
    $("summary").classList.add("hidden");
    $("placements").innerHTML = "";
    $("evidence").classList.add("hidden");
    $("canvas-wrap").classList.add("hidden");
  };
}

renderCards();
bind();
