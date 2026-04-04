const SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "NVDA", "AAPL", "TSLA", "AMZN", "MSFT"];
const BASE_PRICES = { "BTC-USD": 87420, "ETH-USD": 3280, "SOL-USD": 178, NVDA: 142, AAPL: 214, TSLA: 185, AMZN: 192, MSFT: 422 };

const rand = (min, max) => Math.random() * (max - min) + min;

function fmtK(n) {
  if (Math.abs(n) >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(2)}K`;
  return `${n.toFixed(0)}`;
}

function genGEXStrikes(spot, count = 25) {
  const step = spot > 1000 ? 500 : spot > 100 ? 5 : spot > 10 ? 1 : 0.5;
  const base = Math.round(spot / step) * step - step * Math.floor(count / 2);
  return Array.from({ length: count }).map((_, i) => {
    const strike = base + i * step;
    const dist = (strike - spot) / spot;
    const gex = (Math.exp(-dist * dist * 80) * rand(0.6, 1.4) - 0.35) * 1e6;
    return { strike: strike.toFixed(0), gex };
  });
}

function findFlipStrike(gexData) {
  for (let i = 1; i < gexData.length; i += 1) {
    if (Math.sign(gexData[i - 1].gex) !== Math.sign(gexData[i].gex)) return gexData[i];
  }
  return null;
}

function render(sym = "BTC-USD") {
  const spot = BASE_PRICES[sym];
  const gexData = genGEXStrikes(spot);
  const totalGEX = gexData.reduce((sum, row) => sum + row.gex, 0);
  const flipStrike = findFlipStrike(gexData);
  const regime = totalGEX >= 0 ? "POSITIVE GAMMA" : "NEGATIVE GAMMA";
  const maxAbs = Math.max(...gexData.map((r) => Math.abs(r.gex)));

  const app = document.getElementById("app");
  app.innerHTML = `
    <h2 style="margin:0 0 6px; letter-spacing:1px;">GAMMA SHOCK BUFFER</h2>
    <p style="margin:0 0 14px; color:#8b95a5; font-size:12px;">GEX strike distribution, regime detection, and first gamma flip strike.</p>
    <label style="font-size:11px; margin-right:8px; color:#6b7280">Symbol</label>
    <select id="symbolSelect" style="background:#111520;color:#e2e5ea;border:1px solid #1a1f2e;padding:6px 10px;">
      ${SYMBOLS.map((s) => `<option value="${s}" ${s === sym ? "selected" : ""}>${s}</option>`).join("")}
    </select>
    <div class="row">
      <div class="card"><div class="label">Regime</div><div style="font-weight:700; color:${totalGEX >= 0 ? "#00e5a0" : "#ef4444"}">${regime}</div></div>
      <div class="card"><div class="label">Net GEX</div><div class="mono" style="font-weight:700">${fmtK(totalGEX)}</div></div>
      <div class="card"><div class="label">Flip Strike</div><div class="mono" style="font-weight:700">${flipStrike ? flipStrike.strike : "No flip in sampled strikes"}</div></div>
    </div>
    <div class="bars">
      ${gexData.map((r) => {
        const w = Math.max(2, Math.round((Math.abs(r.gex) / maxAbs) * 100));
        const bar = r.gex >= 0
          ? `<div class="bar-pos" style="width:${w}%"></div><div style="width:${100 - w}%"></div>`
          : `<div style="width:${100 - w}%"></div><div class="bar-neg" style="width:${w}%"></div>`;
        return `<div class="bar-row"><div class="strike mono">${r.strike}</div><div class="bar-track">${bar}</div><div class="mono" style="width:88px; text-align:right; color:${r.gex >= 0 ? "#00e5a0" : "#ef4444"}">${fmtK(r.gex)}</div></div>`;
      }).join("")}
    </div>
  `;

  document.getElementById("symbolSelect").addEventListener("change", (e) => render(e.target.value));
}

render();
