import { useCallback, useEffect, useMemo, useState } from "react";
import { AssetContext, get, hasRole, kc, Live, liveSocket, post, TagDef } from "./api";
import { EqProps, Scene, contextTitle } from "./Scene";

type Row = Record<string, string | number | null>;
const fmt = (v: number | null | undefined, d = 2) => (v === null || v === undefined || Number.isNaN(v) ? "--" : v.toFixed(d));

function Panel({ title, children, wide }: { title: string; children: React.ReactNode; wide?: boolean }) {
  return <section className={`panel${wide ? " wide" : ""}`}><h2>{title}</h2>{children}</section>;
}

function Bar({ v, lo, hi, nominal }: { v: number | null; lo: number; hi: number; nominal: number }) {
  const pct = (x: number) => `${Math.max(0, Math.min(100, ((x - lo) / (hi - lo)) * 100))}%`;
  return (
    <div className="bar">
      <div className="normal" style={{ left: pct(nominal - (hi - lo) * 0.1), width: `${20}%` }} />
      {v !== null && <div className="pv" style={{ left: pct(v) }} />}
    </div>
  );
}

function LiveTable({ live, tags, filter }: { live: Map<string, Live>; tags: TagDef[]; filter: string | null }) {
  const rows = tags.filter((t) => (t.class === "instrument" || t.class === "calculated") && (!filter || t.equipment === filter));
  return (
    <table><thead><tr><th>Tag</th><th>Description</th><th>Value</th><th>Unit</th><th>Range</th><th>Quality</th></tr></thead>
      <tbody>{rows.map((t) => { const l = live.get(t.tag); const bad = l && !l.quality.startsWith("Good");
        return (<tr key={t.tag} className={bad ? "abn" : ""}><td>{t.tag}</td><td>{t.desc}</td>
          <td className="num">{fmt(l?.value)}</td><td>{t.unit}</td>
          <td><Bar v={l?.value ?? null} lo={t.range[0]} hi={t.range[1]} nominal={t.nominal} /></td>
          <td>{l?.quality ?? "no data"}</td></tr>); })}</tbody></table>
  );
}

function SurgeMap() {
  const [m, setM] = useState<any>(null);
  useEffect(() => { const f = () => get("/surge-map").then(setM).catch(() => {}); f(); const i = setInterval(f, 10000); return () => clearInterval(i); }, []);
  if (!m) return <p>loading</p>;
  const all = m.speed_lines.flatMap((l: any) => l.points);
  const qmax = Math.max(...all.map((p: any) => p.q)) * 1.05, hmax = Math.max(...all.map((p: any) => p.head_kj)) * 1.1;
  const X = (q: number) => 40 + (q / qmax) * 330, Y = (h: number) => 210 - (h / hmax) * 190;
  const surge = m.speed_lines.map((l: any) => `${X(l.surge.q)},${Y(l.surge.head_kj)}`).join(" ");
  return (
    <svg viewBox="0 0 380 240" className="chart">
      <line x1="40" y1="210" x2="370" y2="210" className="axis" /><line x1="40" y1="10" x2="40" y2="210" className="axis" />
      <text x="200" y="235" className="ax">Suction flow, m3/s</text><text x="5" y="15" className="ax">kJ/kg</text>
      {m.speed_lines.map((l: any) => (
        <g key={l.speed}><polyline className="speed" points={l.points.map((p: any) => `${X(p.q)},${Y(p.head_kj)}`).join(" ")} />
          <text x={X(l.points[l.points.length - 1].q) - 20} y={Y(l.points[l.points.length - 1].head_kj) - 4} className="ax">{Math.round(l.speed * 100)}%</text></g>))}
      <polyline className="surge" points={surge} /><text x={X(m.speed_lines[0].surge.q)} y="200" className="ax">surge limit</text>
      {m.operating_point && <circle cx={X(m.operating_point.q)} cy={Y(m.operating_point.head_kj)} r="5" className="op" />}
    </svg>
  );
}

function Trend({ tags }: { tags: TagDef[] }) {
  const [tag, setTag] = useState("100-TT-2005");
  const [minutes, setMinutes] = useState(60);
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ ts: string; value: number }[]>([]);
  const [end, setEnd] = useState<string | undefined>();
  useEffect(() => {
    get<Live[]>("/live").then((l) => { const t = l.map((x) => Date.parse(x.ts)).reduce((a, b) => Math.max(a, b), 0);
      setEnd(t ? new Date(t - offset * 60000).toISOString() : undefined); });
  }, [offset]);
  useEffect(() => {
    const q = `/history?tag=${encodeURIComponent(tag)}&minutes=${minutes}${end ? `&end=${encodeURIComponent(end)}` : ""}`;
    get<{ ts: string; value: number }[]>(q).then(setData).catch(() => setData([]));
  }, [tag, minutes, end]);
  const vals = data.map((d) => d.value).filter((x) => x !== null);
  const lo = Math.min(...vals), hi = Math.max(...vals), t0 = data.length ? Date.parse(data[0].ts) : 0, t1 = data.length ? Date.parse(data[data.length - 1].ts) : 1;
  const pts = data.map((d) => `${10 + ((Date.parse(d.ts) - t0) / Math.max(t1 - t0, 1)) * 360},${190 - ((d.value - lo) / Math.max(hi - lo, 1e-9)) * 170}`).join(" ");
  return (<div>
    <select value={tag} onChange={(e) => setTag(e.target.value)}>{tags.map((t) => <option key={t.tag}>{t.tag}</option>)}
      {["TWIN.eta_p", "TWIN.f_eta_rel", "TWIN.f_head_rel", "TWIN.cooler_approach", "TWIN.scrubber_load"].map((t) => <option key={t}>{t}</option>)}</select>
    <select value={minutes} onChange={(e) => setMinutes(+e.target.value)}>{[10, 60, 360, 1440].map((m) => <option key={m} value={m}>{m} min</option>)}</select>
    <label> Replay: {offset} min ago <input type="range" min={0} max={1440} step={10} value={offset} onChange={(e) => setOffset(+e.target.value)} /></label>
    <svg viewBox="0 0 380 200" className="chart"><polyline points={pts} className="trend" />
      <text x="12" y="14" className="ax">{fmt(hi)}</text><text x="12" y="196" className="ax">{fmt(lo)}</text>
      <text x="250" y="196" className="ax">{data.length} archived points</text></svg>
  </div>);
}

function WhatIf() {
  const [f, setF] = useState({ flow_factor: 1.0, ambient_c: 48, p_suction_bar: 29, p_discharge_bar: 76, use_estimated_degradation: true, fans: 4 });
  const [r, setR] = useState<any>(null);
  const [err, setErr] = useState("");
  const field = (k: keyof typeof f, step = 0.1) => (
    <label key={k}>{k} <input type="number" step={step} value={f[k] as number} onChange={(e) => setF({ ...f, [k]: +e.target.value })} /></label>);
  if (!hasRole("process_engineer")) return <p>Requires the process engineer role.</p>;
  return (<div className="form">
    {field("flow_factor", 0.05)}{field("ambient_c", 1)}{field("p_suction_bar", 0.5)}{field("p_discharge_bar", 0.5)}{field("fans", 1)}
    <label><input type="checkbox" checked={f.use_estimated_degradation} onChange={(e) => setF({ ...f, use_estimated_degradation: e.target.checked })} /> use estimated degradation</label>
    <button onClick={() => post("/whatif", f).then(setR).catch((e) => setErr(String(e)))}>Run (computed at L4, nothing sent to the plant)</button>
    {err && <p className="abn">{err}</p>}
    {r && <table><tbody>
      <tr><td>Speed</td><td className="num">{fmt(r.speed_rpm, 0)} rpm</td></tr>
      <tr><td>Discharge temperature</td><td className="num">{fmt(r.discharge_temp_c, 1)} degC</td></tr>
      <tr><td>Motor power</td><td className="num">{fmt(r.power_mw)} MW</td></tr>
      <tr><td>Surge margin</td><td className="num">{fmt(r.surge_margin_pct, 0)} %</td></tr>
      <tr><td>Specific energy</td><td className="num">{fmt(r.specific_energy_kwh_per_t, 1)} kWh/t</td></tr>
      <tr><td>Violations</td><td className={r.violations.length ? "abn" : ""}>{r.violations.join("; ") || "none"}</td></tr>
    </tbody></table>}
  </div>);
}

export default function App() {
  const [tags, setTags] = useState<TagDef[]>([]);
  const [live, setLive] = useState<Map<string, Live>>(new Map());
  const [scene, setScene] = useState<{ equipment: EqProps[]; lines: any[] } | null>(null);
  const [pid, setPid] = useState("");
  const [sel, setSel] = useState<string | null>(null);
  const [ctx, setCtx] = useState<AssetContext | null>(null);
  const [alarms, setAlarms] = useState<any>(null);
  const [kpis, setKpis] = useState<Map<string, number>>(new Map());
  const [adv, setAdv] = useState<Row[]>([]);
  const [wos, setWos] = useState<Row[]>([]);
  const [diode, setDiode] = useState<Row[]>([]);

  useEffect(() => {
    get<TagDef[]>("/tags").then(setTags);
    get<any>("/scene").then(setScene);
    get<string>("/pid.svg").then(setPid).catch(() => setPid(""));
    const ws = liveSocket((rows) => setLive(new Map(rows.map((r) => [r.tag, r]))));
    const slow = () => {
      get<any>("/alarms").then(setAlarms).catch(() => {});
      get<{ tag: string; value: number }[]>("/kpis").then((k) => setKpis(new Map(k.map((x) => [x.tag, x.value])))).catch(() => {});
      get<Row[]>("/advisories").then(setAdv).catch(() => {});
      get<Row[]>("/diode").then(setDiode).catch(() => {});
      if (hasRole("maintenance", "process_engineer")) get<Row[]>("/workorders").then(setWos).catch(() => {});
    };
    slow(); const i = setInterval(slow, 10000);
    return () => { ws.close(); clearInterval(i); };
  }, []);

  const pick = useCallback((id: string) => { setSel(id || null); }, []);
  useEffect(() => { if (sel) get<AssetContext>(`/assets/${encodeURIComponent(sel)}`).then(setCtx).catch(() => setCtx(null)); else setCtx(null); }, [sel]);

  const alarmedEq = useMemo(() => {
    const s = new Set<string>();
    (alarms?.standing ?? []).forEach((a: any) => { const t = tags.find((x) => x.tag === a.alarm.split(".")[0]); if (t?.equipment) s.add(t.equipment); });
    return s;
  }, [alarms, tags]);

  const pidHtml = useMemo(() => sel ? pid.replace(`data-id="${sel}"`, `data-id="${sel}" class="sel"`) : pid, [pid, sel]);
  const k = (t: string) => kpis.get(t);
  const tripped = live.get("TRIP")?.value === 1;

  return (<div>
    <header>
      <b>Unit 100 export gas compression</b> <span className="muted">Reference Gas Processing Facility (fictional, simulated data)</span>
      {tripped && <span className="alarm1">COMPRESSOR TRIPPED</span>}
      <span className="right">{kc.tokenParsed?.preferred_username} <button onClick={() => kc.logout()}>Log out</button></span>
    </header>
    <main>
      <Panel title="3D plant (procedural from datasheets)" wide>
        <div className="scene">{scene && <Scene equipment={scene.equipment} lines={scene.lines} selected={sel} alarmed={alarmedEq} onPick={pick} />}</div>
      </Panel>
      <Panel title={`Context: ${contextTitle(ctx)}`}>
        {ctx ? (<div>
          <p className="muted">{ctx.node.path ?? ""}</p>
          <table><tbody>{Object.entries((ctx.node.props as any).datasheet ?? ctx.node.props).slice(0, 12).map(([a, b]) => <tr key={a}><td>{a}</td><td>{JSON.stringify(b)}</td></tr>)}</tbody></table>
          <h3>Relations</h3><ul>{ctx.outgoing.filter((o) => o.kind !== "tag").map((o) => <li key={o.id}>{o.rel} {o.name}</li>)}</ul>
          <h3>Live tags</h3><ul>{ctx.live.map((l) => <li key={l.tag} className={l.quality.startsWith("Good") ? "" : "abn"}>{l.tag}: {fmt(l.value)} ({l.quality})</li>)}</ul>
          {ctx.work_orders && <><h3>Work orders</h3><ul>{ctx.work_orders.map((w) => <li key={String(w.id)}>{String(w.reported).slice(0, 10)} {w.failure_mode ?? w.wo_type}: {w.description}</li>)}</ul></>}
        </div>) : <p>Click equipment in the 3D view or on the P&ID.</p>}
      </Panel>
      <Panel title="P&ID (generated, DEXPI-style source)" wide>
        <div className="pid" onClick={(e) => { const g = (e.target as Element).closest("[data-id]"); if (g) pick(g.getAttribute("data-id")!); }}
          dangerouslySetInnerHTML={{ __html: pidHtml }} />
      </Panel>
      <Panel title="Alarms (ISA-18.2)">
        {alarms && <p className={alarms.flood ? "alarm1" : "muted"}>{alarms.rate_per_10min} annunciations in 10 min{alarms.flood ? " - ALARM FLOOD" : ""}</p>}
        <table><thead><tr><th>P</th><th>Alarm</th><th>State</th><th>Operator action</th></tr></thead><tbody>
          {(alarms?.standing ?? []).map((a: any) => <tr key={a.alarm} className={`p${a.priority}`}><td>{a.priority}</td><td>{a.alarm}</td><td>{a.state}</td><td>{a.action}</td></tr>)}
        </tbody></table>
        {!alarms?.standing?.length && <p className="muted">No standing alarms.</p>}
      </Panel>
      <Panel title="Performance (PTC 10-style, Level 3 calculation)">
        <table><tbody>
          <tr><td>Polytropic efficiency</td><td className="num">{fmt(k("TWIN.eta_p"), 1)} % +/- {fmt(k("TWIN.eta_p_u95"), 1)} (k=2)</td></tr>
          <tr><td>Polytropic head</td><td className="num">{fmt(k("TWIN.head_p"), 1)} kJ/kg</td></tr>
          <tr><td>Surge margin</td><td className="num">{fmt(live.get("100-UY-2042")?.value, 0)} %</td></tr>
          <tr><td>Cooler approach / duty</td><td className="num">{fmt(k("TWIN.cooler_approach"), 1)} K / {fmt(k("TWIN.cooler_duty"))} MW</td></tr>
          <tr><td>Scrubber load (K / K design)</td><td className="num">{fmt(k("TWIN.scrubber_load"))}</td></tr>
          <tr><td>Steady state</td><td>{k("TWIN.steady") === 1 ? "yes" : "no (KPIs indicative only)"}</td></tr>
        </tbody></table>
        <SurgeMap />
      </Panel>
      <Panel title="Degradation and RUL (UKF twin synchronization)">
        <table><tbody>
          <tr><td>Calibrated</td><td>{k("TWIN.calibrated") === 1 ? "yes" : "baseline in progress"}</td></tr>
          <tr><td>Head factor (vs commissioning)</td><td className="num">{fmt(k("TWIN.f_head_rel"), 3)}</td></tr>
          <tr><td>Efficiency factor</td><td className="num">{fmt(k("TWIN.f_eta_rel"), 3)} (1 sd {fmt(k("TWIN.sd_eta"), 3)})</td></tr>
          <tr><td>Cooler UA factor (weakly observable)</td><td className="num">{fmt(k("TWIN.f_ua_rel"), 2)}</td></tr>
          <tr><td>Days to wash limit (trend)</td><td className="num">{fmt(k("TWIN.rul_days"), 0)}</td></tr>
          <tr><td>Wash recommended (economics)</td><td className={k("TWIN.wash_recommended") === 1 ? "abn" : ""}>{k("TWIN.wash_recommended") === 1 ? "yes" : "no"}</td></tr>
        </tbody></table>
      </Panel>
      <Panel title="Trends and historical replay"><Trend tags={tags} /></Panel>
      <Panel title="What-if"><WhatIf /></Panel>
      <Panel title="Advisories (operator-in-the-loop)">
        <p className="muted">Read-only here (Level 4). The operator accepts or rejects at the DCS console (Level 2); the DCS verifies bounds before applying.</p>
        <table><thead><tr><th>Id</th><th>Target</th><th>Value</th><th>State</th><th>By</th></tr></thead><tbody>
          {adv.map((a) => <tr key={String(a.id)} title={String(a.rationale)}><td>{a.id}</td><td>{a.target}</td><td className="num">{fmt(a.value as number, 1)}</td><td>{a.state}</td><td>{a.decided_by ?? ""}</td></tr>)}
        </tbody></table>
      </Panel>
      <Panel title="Work orders (CMMS, ISO 14224 codes)" wide>
        {hasRole("maintenance", "process_engineer") ? <table><thead><tr><th>Id</th><th>Location</th><th>Type</th><th>Mode</th><th>Mechanism</th><th>Activity</th><th>Description</th><th>Downtime h</th></tr></thead><tbody>
          {wos.map((w) => <tr key={String(w.id)}><td>{w.id}</td><td>{w.functional_location}</td><td>{w.wo_type}</td><td>{w.failure_mode ?? ""}</td><td>{w.failure_mechanism ?? ""}</td><td>{w.maintenance_activity}</td><td>{w.description}</td><td className="num">{w.downtime_h}</td></tr>)}
        </tbody></table> : <p>Requires the maintenance or process engineer role.</p>}
      </Panel>
      <Panel title={`Live values${ctx?.node.kind === "equipment" ? `: ${ctx.node.name}` : ""}`} wide>
        <LiveTable live={live} tags={tags} filter={ctx?.node.kind === "equipment" ? ctx.node.name : null} />
        <p className="muted">Diode: {diode.map((d) => `seq ${d.last_seq}, received ${d.received}, gaps ${d.gaps}, duplicates ${d.duplicates}`).join("")}</p>
      </Panel>
    </main>
  </div>);
}
