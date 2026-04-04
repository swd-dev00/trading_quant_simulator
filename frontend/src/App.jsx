import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "NVDA", "AAPL", "TSLA", "AMZN", "MSFT"];
const BASE_PRICES = {
  "BTC-USD": 87420,
  "ETH-USD": 3280,
  "SOL-USD": 178,
  NVDA: 142,
  AAPL: 214,
  TSLA: 185,
  AMZN: 192,
  MSFT: 422,
};

const rand = (min, max) => Math.random() * (max - min) + min;
const fmtK = (n) => {
  if (Math.abs(n) >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(2)}K`;
  return `${n.toFixed(0)}`;
};

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
    const prevSign = Math.sign(gexData[i - 1].gex);
    const currSign = Math.sign(gexData[i].gex);
    if (prevSign !== currSign) {
      return gexData[i];
    }
  }
  return null;
}

export default function App() {
  const [sym, setSym] = useState("BTC-USD");
  const spot = BASE_PRICES[sym];

  const gexData = useMemo(() => genGEXStrikes(spot), [spot]);
  const totalGEX = useMemo(() => gexData.reduce((sum, row) => sum + row.gex, 0), [gexData]);
  const flipStrike = useMemo(() => findFlipStrike(gexData), [gexData]);
  const regime = totalGEX >= 0 ? "POSITIVE GAMMA" : "NEGATIVE GAMMA";

  return (
    <div
      style={{
        color: "#e2e5ea",
        fontFamily: "'IBM Plex Mono', monospace",
        minHeight: "100vh",
        padding: 16,
      }}
    >
      <h2 style={{ margin: "0 0 6px", letterSpacing: 1 }}>GAMMA SHOCK BUFFER</h2>
      <p style={{ margin: "0 0 14px", color: "#8b95a5", fontSize: 12 }}>
        GEX strike distribution, regime detection, and first gamma flip strike.
      </p>

      <label style={{ fontSize: 11, marginRight: 8, color: "#6b7280" }}>Symbol</label>
      <select
        value={sym}
        onChange={(e) => setSym(e.target.value)}
        style={{ background: "#111520", color: "#e2e5ea", border: "1px solid #1a1f2e", padding: "6px 10px" }}
      >
        {SYMBOLS.map((s) => (
          <option key={s}>{s}</option>
        ))}
      </select>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10, margin: "12px 0" }}>
        <div style={{ background: "#111520", border: "1px solid #1a1f2e", borderRadius: 6, padding: 10 }}>
          <div style={{ color: "#6b7280", fontSize: 10 }}>Regime</div>
          <div style={{ color: totalGEX >= 0 ? "#00e5a0" : "#ef4444", fontWeight: 700 }}>{regime}</div>
        </div>
        <div style={{ background: "#111520", border: "1px solid #1a1f2e", borderRadius: 6, padding: 10 }}>
          <div style={{ color: "#6b7280", fontSize: 10 }}>Net GEX</div>
          <div style={{ fontWeight: 700 }}>{fmtK(totalGEX)}</div>
        </div>
        <div style={{ background: "#111520", border: "1px solid #1a1f2e", borderRadius: 6, padding: 10 }}>
          <div style={{ color: "#6b7280", fontSize: 10 }}>Flip Strike</div>
          <div style={{ fontWeight: 700 }}>{flipStrike ? flipStrike.strike : "No flip in sampled strikes"}</div>
        </div>
      </div>

      <div style={{ background: "#0f1219", border: "1px solid #1a1f2e", borderRadius: 6, padding: 8 }}>
        <ResponsiveContainer width="100%" height={420}>
          <BarChart data={gexData} layout="vertical" margin={{ left: 10, right: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1a1f2e" />
            <XAxis type="number" tick={{ fill: "#6b7280", fontSize: 10 }} tickFormatter={fmtK} />
            <YAxis type="category" dataKey="strike" tick={{ fill: "#6b7280", fontSize: 10 }} width={65} />
            <Tooltip
              formatter={(v) => [`${fmtK(Number(v))}`, "GEX"]}
              contentStyle={{ background: "#111520", border: "1px solid #1a1f2e" }}
              labelStyle={{ color: "#e2e5ea" }}
            />
            <ReferenceLine x={0} stroke="#6b728060" />
            <Bar dataKey="gex">
              {gexData.map((row, i) => (
                <Cell key={`${row.strike}-${i}`} fill={row.gex >= 0 ? "#00e5a0" : "#ef4444"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
