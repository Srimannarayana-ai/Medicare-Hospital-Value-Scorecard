"""
Build a small interactive HTML dashboard for GitHub Pages.
Uses the cleaned hospital table (no raw CMS files needed).
"""

from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "02_clean" / "hospital_value_master.csv"
OUT = ROOT / "docs" / "live-dashboard" / "index.html"


def main() -> None:
    df = pd.read_csv(CSV)
    cols = [
        "Facility Name",
        "State",
        "Hospital Ownership",
        "Hospital Type",
        "Experience_Star",
        "Readmission_Rate",
        "HAI_SIR_Avg",
        "MSPB",
        "Quality",
        "Value_Score",
        "Focus_Flag",
    ]
    table = df[cols].copy()
    for c in ["Experience_Star", "Readmission_Rate", "HAI_SIR_Avg", "MSPB", "Quality", "Value_Score"]:
        table[c] = table[c].round(3)

    scored = table[table["Value_Score"].notna()]
    kpis = {
        "hospitals": int(table.shape[0]),
        "scored": int(scored.shape[0]),
        "avg_exp": round(float(scored["Experience_Star"].mean()), 2),
        "avg_mspb": round(float(scored["MSPB"].mean()), 3),
        "avg_value": round(float(scored["Value_Score"].mean()), 1),
        "focus": int((table["Focus_Flag"] != "Ok / review later").sum()),
    }

    records = json.loads(table.to_json(orient="records"))
    states = sorted(table["State"].dropna().unique().tolist())
    ownerships = sorted(table["Hospital Ownership"].dropna().unique().tolist())
    types = sorted(table["Hospital Type"].dropna().unique().tolist())

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Medicare Hospital Value Scorecard</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    body {{ margin: 0; font-family: Segoe UI, Tahoma, sans-serif; background: #f7f5f1; color: #1f1f1f; }}
    header {{ padding: 24px 28px; background: #efeae2; border-bottom: 1px solid #d9d4cb; }}
    h1 {{ margin: 0 0 6px; font-size: 26px; color: #1f4e5f; }}
    header p {{ margin: 0; color: #5c5c5c; max-width: 820px; line-height: 1.4; }}
    .wrap {{ padding: 18px 28px 36px; }}
    .filters {{ display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 14px; align-items: end; }}
    label {{ display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: #5c5c5c; }}
    select, input, button {{ padding: 8px 10px; border: 1px solid #d9d4cb; border-radius: 4px; background: #fff; font-size: 14px; }}
    button {{ background: #1f4e5f; color: #fff; border-color: #1f4e5f; cursor: pointer; }}
    .kpis {{ display: grid; grid-template-columns: repeat(5, minmax(110px, 1fr)); gap: 10px; margin-bottom: 14px; }}
    .kpi {{ background: #fff; border: 1px solid #d9d4cb; padding: 12px 14px; }}
    .kpi .lbl {{ font-size: 12px; color: #5c5c5c; }}
    .kpi .val {{ font-size: 22px; margin-top: 4px; color: #1f4e5f; font-weight: 650; }}
    .grid {{ display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 12px; margin-bottom: 12px; }}
    .panel {{ background: #fff; border: 1px solid #d9d4cb; padding: 6px; }}
    .table-wrap {{ max-height: 420px; overflow: auto; border: 1px solid #d9d4cb; background: #fff; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #d9d4cb; padding: 7px 9px; text-align: left; white-space: nowrap; }}
    th {{ position: sticky; top: 0; background: #f3efe8; }}
    .note {{ margin-top: 10px; color: #5c5c5c; font-size: 12px; }}
    @media (max-width: 980px) {{ .grid, .kpis {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <header>
    <h1>Medicare Hospital Value Scorecard</h1>
    <p>Patient experience and quality versus Medicare spending (MSPB). Value = quality composite (0-100) / MSPB.</p>
  </header>
  <div class="wrap">
    <div class="filters">
      <label>State<select id="state"><option value="">All states</option></select></label>
      <label>Ownership<select id="own"><option value="">All ownership</option></select></label>
      <label>Hospital type<select id="type"><option value="">All types</option></select></label>
      <label>Search<input id="q" type="text" placeholder="Hospital name" /></label>
      <button id="reset" type="button">Reset</button>
    </div>
    <div class="kpis">
      <div class="kpi"><div class="lbl">Hospitals</div><div class="val" id="kH">-</div></div>
      <div class="kpi"><div class="lbl">With value score</div><div class="val" id="kS">-</div></div>
      <div class="kpi"><div class="lbl">Avg experience</div><div class="val" id="kE">-</div></div>
      <div class="kpi"><div class="lbl">Avg MSPB</div><div class="val" id="kM">-</div></div>
      <div class="kpi"><div class="lbl">Avg value</div><div class="val" id="kV">-</div></div>
    </div>
    <div class="grid">
      <div class="panel"><div id="scatter"></div></div>
      <div class="panel"><div id="bars"></div></div>
    </div>
    <div class="panel">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Facility</th><th>State</th><th>Ownership</th><th>Type</th>
              <th>Exp</th><th>MSPB</th><th>Quality</th><th>Value</th><th>Flag</th>
            </tr>
          </thead>
          <tbody id="tbody"></tbody>
        </table>
      </div>
      <p class="note">Baseline: {kpis['hospitals']} hospitals, {kpis['scored']} with value scores, {kpis['focus']} on the focus list. Source: CMS Provider Data Catalog.</p>
    </div>
  </div>
  <script>
    const DATA = {json.dumps(records)};
    const STATES = {json.dumps(states)};
    const OWNS = {json.dumps(ownerships)};
    const TYPES = {json.dumps(types)};
    const state = document.getElementById('state');
    const own = document.getElementById('own');
    const type = document.getElementById('type');
    const q = document.getElementById('q');
    STATES.forEach(s => {{ const o=document.createElement('option'); o.value=s; o.textContent=s; state.appendChild(o); }});
    OWNS.forEach(s => {{ const o=document.createElement('option'); o.value=s; o.textContent=s; own.appendChild(o); }});
    TYPES.forEach(s => {{ const o=document.createElement('option'); o.value=s; o.textContent=s; type.appendChild(o); }});
    const num = v => (v===null || v===undefined || v==='') ? null : Number(v);
    const avg = arr => {{ const a=arr.filter(v => v!==null && !Number.isNaN(v)); return a.length ? a.reduce((x,y)=>x+y,0)/a.length : null; }};
    const fmt = (v,d=1) => (v===null || Number.isNaN(v)) ? '-' : Number(v).toFixed(d);
    function filtered() {{
      const st=state.value, ow=own.value, tp=type.value, qq=q.value.trim().toLowerCase();
      return DATA.filter(r => {{
        if (st && r.State !== st) return false;
        if (ow && r['Hospital Ownership'] !== ow) return false;
        if (tp && r['Hospital Type'] !== tp) return false;
        if (qq && !((r['Facility Name']||'').toLowerCase().includes(qq))) return false;
        return true;
      }});
    }}
    function refresh() {{
      const rows = filtered();
      const scored = rows.filter(r => num(r.Value_Score) !== null);
      document.getElementById('kH').textContent = rows.length;
      document.getElementById('kS').textContent = scored.length;
      document.getElementById('kE').textContent = fmt(avg(scored.map(r => num(r.Experience_Star))), 2);
      document.getElementById('kM').textContent = fmt(avg(scored.map(r => num(r.MSPB))), 3);
      document.getElementById('kV').textContent = fmt(avg(scored.map(r => num(r.Value_Score))), 1);
      const body = document.getElementById('tbody');
      body.innerHTML = '';
      rows.slice(0, 400).forEach(r => {{
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${{r['Facility Name']||''}}</td><td>${{r.State||''}}</td><td>${{r['Hospital Ownership']||''}}</td><td>${{r['Hospital Type']||''}}</td><td>${{fmt(num(r.Experience_Star),1)}}</td><td>${{fmt(num(r.MSPB),3)}}</td><td>${{fmt(num(r.Quality),1)}}</td><td>${{fmt(num(r.Value_Score),1)}}</td><td>${{r.Focus_Flag||''}}</td>`;
        body.appendChild(tr);
      }});
      Plotly.newPlot('scatter', [{{
        x: scored.map(r => num(r.MSPB)),
        y: scored.map(r => num(r.Quality)),
        text: scored.map(r => r['Facility Name']),
        type: 'scattergl', mode: 'markers',
        marker: {{ size: 7, opacity: 0.65, color: '#1f4e5f' }},
        hovertemplate: '%{{text}}<br>MSPB: %{{x:.3f}}<br>Quality: %{{y:.1f}}<extra></extra>'
      }}], {{
        title: 'Quality vs Medicare spending (MSPB)',
        xaxis: {{ title: 'MSPB (1.0 = national average)' }},
        yaxis: {{ title: 'Quality (0-100)' }},
        height: 400, margin: {{ t: 40, r: 20, b: 50, l: 50 }},
        paper_bgcolor: '#fff', plot_bgcolor: '#fff'
      }}, {{responsive: true}});
      const by = {{}};
      scored.forEach(r => {{
        if (!r.State) return;
        if (!by[r.State]) by[r.State] = [];
        by[r.State].push(num(r.Value_Score));
      }});
      const top = Object.keys(by).map(s => ({{ State: s, v: avg(by[s]) }}))
        .filter(x => x.v !== null).sort((a,b) => b.v - a.v).slice(0, 15).reverse();
      Plotly.newPlot('bars', [{{
        type: 'bar', orientation: 'h',
        x: top.map(r => r.v), y: top.map(r => r.State),
        marker: {{ color: '#2a6f97' }},
        hovertemplate: '%{{y}}: %{{x:.1f}}<extra></extra>'
      }}], {{
        title: 'Top states by average value score',
        xaxis: {{ title: 'Avg value score' }}, yaxis: {{ title: 'State' }},
        height: 400, margin: {{ t: 40, r: 20, b: 50, l: 50 }}
      }}, {{responsive: true}});
    }}
    state.onchange = own.onchange = type.onchange = q.oninput = refresh;
    document.getElementById('reset').onclick = () => {{ state.value=''; own.value=''; type.value=''; q.value=''; refresh(); }};
    refresh();
  </script>
</body>
</html>
""",
        encoding="utf-8",
    )
    print("Wrote", OUT, "bytes", OUT.stat().st_size)


if __name__ == "__main__":
    main()
