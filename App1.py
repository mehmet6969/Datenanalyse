# App1.py — Single File: Flask + sqlite3 + Chart.js + Tailwind
import os, sqlite3
from datetime import datetime, timedelta, date
from flask import Flask, request, make_response, abort, g

DB_PATH = os.path.join(os.path.dirname(__file__), "klicks.sqlite")
app = Flask(__name__)

# ---------------------- DB Helpers (sqlite3) ----------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS clicks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            box TEXT NOT NULL CHECK(length(box)=1),
            ip TEXT,
            user_agent TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.commit()

# ---------------------- API ----------------------
@app.post("/api/click")
def api_click():
    data = request.get_json(silent=True) or {}
    box = (data.get("box") or "").upper()
    if box not in {"A","B","C","D"}:
        return {"error":"box must be A|B|C|D"}, 400
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    ua = request.headers.get("User-Agent", "")[:512]
    db = get_db()
    db.execute("INSERT INTO clicks(box, ip, user_agent) VALUES(?,?,?)", (box, ip, ua))
    db.commit()
    return {"status":"saved"}

@app.get("/api/day")
def api_day():
    """Ein Tag (YYYY-MM-DD): stündlich A/B/C/D + Totals + KPIs"""
    qd = request.args.get("date")
    try:
        day = datetime.strptime(qd, "%Y-%m-%d").date() if qd else date.today()
    except Exception:
        return {"error":"invalid date"}, 400

    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)
    db = get_db()

    rows = db.execute("""
        SELECT CAST(STRFTIME('%H', created_at) AS INTEGER) as h,
               SUM(CASE WHEN box='A' THEN 1 ELSE 0 END) as A,
               SUM(CASE WHEN box='B' THEN 1 ELSE 0 END) as B,
               SUM(CASE WHEN box='C' THEN 1 ELSE 0 END) as C,
               SUM(CASE WHEN box='D' THEN 1 ELSE 0 END) as D
        FROM clicks
        WHERE created_at >= ? AND created_at < ?
        GROUP BY h
        ORDER BY h
    """, (start, end)).fetchall()
    by_hour = {r["h"]: {"A": r["A"] or 0, "B": r["B"] or 0, "C": r["C"] or 0, "D": r["D"] or 0} for r in rows}

    hourly = []
    for h in range(24):
        vals = by_hour.get(h, {"A":0,"B":0,"C":0,"D":0})
        hourly.append({"hour": h, **vals})

    totals = {"A":0,"B":0,"C":0,"D":0}
    for r in hourly:
        for k in "ABCD": totals[k] += r[k]

    sums = [r["A"]+r["B"]+r["C"]+r["D"] for r in hourly]
    peak_total = max(sums) if sums else 0
    peak_hour = sums.index(peak_total) if peak_total>0 else 0
    top_box = max(totals, key=lambda k: totals[k]) if sum(totals.values())>0 else None
    srt = sorted(sums)
    mid = len(srt)//2
    median = (srt[mid] if len(srt)%2==1 else (srt[mid-1]+srt[mid])/2) if srt else 0

    return {
        "date": str(day),
        "hourly": hourly,
        "totals": totals,
        "kpis": {"peak_hour": int(peak_hour), "peak_total": int(peak_total), "top_box": top_box, "median_per_hour": median}
    }

@app.get("/api/series")
def api_series():
    """Letzte 30 Tage, pro Tag Summe A/B/C/D (Kontext-Chart)"""
    db = get_db()
    rows = db.execute("""
        SELECT DATE(created_at) as d,
               SUM(CASE WHEN box='A' THEN 1 ELSE 0 END) as A,
               SUM(CASE WHEN box='B' THEN 1 ELSE 0 END) as B,
               SUM(CASE WHEN box='C' THEN 1 ELSE 0 END) as C,
               SUM(CASE WHEN box='D' THEN 1 ELSE 0 END) as D
        FROM clicks
        WHERE created_at >= DATETIME('now', '-30 day')
        GROUP BY d
        ORDER BY d ASC
    """).fetchall()
    series = [{"date": r["d"], "A": r["A"] or 0, "B": r["B"] or 0, "C": r["C"] or 0, "D": r["D"] or 0} for r in rows]
    return {"series": series}

# ---------------------- UI (eine Seite, ohne React) ----------------------
HTML = """<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Klick-Tracker</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>body{ background:#FAFAFA; }</style>
</head>
<body>
  <header class="sticky top-0 z-30 bg-white/90 backdrop-blur border-b">
    <div class="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
      <button id="nav-home" class="font-semibold text-violet-700">Klick-Tracker</button>
      <nav class="text-sm space-x-4">
        <button id="nav-start" class="hover:text-violet-700">Start</button>
        <button id="nav-dash" class="hover:text-violet-700">Dashboard</button>
      </nav>
    </div>
  </header>

  <!-- Sticky Date Toolbar -->
  <div class="sticky top-[52px] z-20 bg-violet-50/95 backdrop-blur border border-violet-200">
    <div class="max-w-6xl mx-auto px-4 py-3 flex flex-wrap items-center gap-3 justify-between">
      <div>
        <div class="text-xs font-semibold text-violet-700">ANALYSE-DATUM</div>
        <div id="currentDate" class="text-lg font-semibold text-violet-900">—</div>
      </div>
      <div class="flex items-center gap-2">
        <label class="text-sm text-zinc-700 font-medium">Tag:</label>
        <input id="dateInput" type="date" class="border rounded-md px-3 py-2 text-sm w-44 focus:outline-none focus:ring-2 focus:ring-violet-400 bg-white">
        <div class="flex items-center gap-2">
          <button id="btnToday" class="text-sm border rounded-md px-2 py-1 hover:bg-white">Heute</button>
          <button id="btnYesterday" class="text-sm border rounded-md px-2 py-1 hover:bg-white">Gestern</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Preset 3 Tage -->
  <div class="bg-white border-b">
    <div class="max-w-6xl mx-auto px-4 py-2 flex items-center gap-2 text-sm">
      <span class="text-zinc-600">Schnellauswahl (3 Tage):</span>
      <div id="presetContainer" class="flex gap-2"></div>
      <label class="ml-auto inline-flex items-center gap-2 cursor-pointer">
        <input id="toggleContext" type="checkbox" class="accent-violet-600">
        <span class="text-zinc-700">30-Tage-Kontext anzeigen</span>
      </label>
    </div>
  </div>

  <main class="max-w-6xl mx-auto px-4 py-6">
    <!-- Home -->
    <section id="view-home" class="space-y-6">
      <h1 class="text-3xl font-semibold">Luca Übersicht</h1>
      <p class="text-zinc-600">Klicke auf ein Kästchen. Der Klick wird gezählt und du landest im Dashboard.</p>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-6">
        <button data-box="A" class="boxBtn group relative aspect-[3/4] rounded-2xl border shadow-sm w-full bg-white hover:shadow-lg hover:border-violet-300 transition flex items-center justify-center">
          <span class="absolute inset-0 rounded-2xl" style="background:#8B5CF622"></span>
          <span class="relative text-6xl font-semibold" style="color:#8B5CF6">A</span>
        </button>
        <button data-box="B" class="boxBtn group relative aspect-[3/4] rounded-2xl border shadow-sm w-full bg-white hover:shadow-lg hover:border-violet-300 transition flex items-center justify-center">
          <span class="absolute inset-0 rounded-2xl" style="background:#EF444422"></span>
          <span class="relative text-6xl font-semibold" style="color:#EF4444">B</span>
        </button>
        <button data-box="C" class="boxBtn group relative aspect-[3/4] rounded-2xl border shadow-sm w-full bg-white hover:shadow-lg hover:border-violet-300 transition flex items-center justify-center">
          <span class="absolute inset-0 rounded-2xl" style="background:#10B98122"></span>
          <span class="relative text-6xl font-semibold" style="color:#10B981">C</span>
        </button>
        <button data-box="D" class="boxBtn group relative aspect-[3/4] rounded-2xl border shadow-sm w-full bg-white hover:shadow-lg hover:border-violet-300 transition flex items-center justify-center">
          <span class="absolute inset-0 rounded-2xl" style="background:#F59E0B22"></span>
          <span class="relative text-6xl font-semibold" style="color:#F59E0B">D</span>
        </button>
      </div>
    </section>

    <!-- Dashboard (alles taggefiltert) -->
    <section id="view-dash" class="space-y-8 hidden">
      <!-- KPIs -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div class="rounded-2xl border bg-white shadow-sm p-4">
          <div class="text-sm text-zinc-500">Gesamt (gewählter Tag)</div>
          <div id="kpi-totalDay" class="mt-2 text-3xl font-semibold">0</div>
        </div>
        <div class="rounded-2xl border bg-white shadow-sm p-4">
          <div class="text-sm text-zinc-500">Peak-Stunde (Tag)</div>
          <div id="kpi-peakHour" class="mt-2 text-3xl font-semibold">–</div>
          <div id="kpi-peakTotal" class="text-xs text-zinc-500">Spitze: –</div>
        </div>
        <div class="rounded-2xl border bg-white shadow-sm p-4">
          <div class="text-sm text-zinc-500">Top-Box (Tag)</div>
          <div id="kpi-topBox" class="mt-2 text-3xl font-semibold">–</div>
        </div>
        <div class="rounded-2xl border bg-white shadow-sm p-4">
          <div class="text-sm text-zinc-500">Median/Std (Tag)</div>
          <div id="kpi-median" class="mt-2 text-3xl font-semibold">0</div>
        </div>
      </div>

      <!-- Tag: Klicks pro Kästchen & Donut -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div class="rounded-2xl border bg-white shadow-sm p-4">
          <h3 class="mb-2 font-medium">Klicks pro Kästchen (Tag)</h3>
          <canvas id="chartBarDay" height="240"></canvas>
        </div>
        <div class="rounded-2xl border bg-white shadow-sm p-4">
          <h3 class="mb-2 font-medium">Verteilung (Tag)</h3>
          <canvas id="chartDonutDay" height="240"></canvas>
        </div>
      </div>

      <!-- Tag: Stundenverlauf -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div class="rounded-2xl border bg-white shadow-sm p-4">
          <h3 class="mb-2 font-medium">Tagesverlauf (0–23, gestapelt)</h3>
          <canvas id="chartHourly" height="260"></canvas>
        </div>
        <div class="rounded-2xl border bg-white shadow-sm p-4">
          <h3 class="mb-2 font-medium">Kumulierte Klicks (Tag)</h3>
          <canvas id="chartCum" height="260"></canvas>
        </div>
      </div>

      <!-- Optional: 30-Tage-Kontext -->
      <div id="contextBlock" class="grid grid-cols-1 lg:grid-cols-2 gap-6 hidden">
        <div class="rounded-2xl border bg-white shadow-sm p-4">
          <h3 class="mb-2 font-medium">Zeitreihe (letzte 30 Tage)</h3>
          <canvas id="chartSeries" height="280"></canvas>
        </div>
        <div class="rounded-2xl border bg-white shadow-sm p-4">
          <h3 class="mb-2 font-medium">Hinweis</h3>
          <p class="text-sm text-zinc-600">Diese Ansicht zeigt die Summen je Tag über 30 Tage (nicht gefiltert).</p>
        </div>
      </div>
    </section>
  </main>

  <footer class="border-t py-6 text-center text-zinc-500">© <span id="year"></span> Klick-Tracker</footer>

  <script>
  // ---------- Config ----------
  const COLORS = { A:'#8B5CF6', B:'#EF4444', C:'#10B981', D:'#F59E0B' };
  // Trage hier DEINE drei Tage ein (YYYY-MM-DD):
  const PRESET_DATES = [
    // Beispiel:
    // '2025-09-28','2025-09-29','2025-09-30'
  ];

  // ---------- Helpers ----------
  const $ = sel => document.querySelector(sel);
  const show = id => { $('#view-home').classList.add('hidden'); $('#view-dash').classList.add('hidden'); $(id).classList.remove('hidden'); }
  const fmt = n => (n<10? '0'+n : ''+n);
  function fmtDateInput(d=new Date()){ return `${d.getFullYear()}-${fmt(d.getMonth()+1)}-${fmt(d.getDate())}`; }
  function sumObj(o){ return Object.values(o).reduce((a,b)=>a+(b||0),0); }
  function setToolbarDate(v){ $('#dateInput').value = v; $('#currentDate').textContent = v; }

  // ---------- Charts (refs) ----------
  let chBarDay, chDonutDay, chHourly, chCum, chSeries;

  function createOrUpdate(ref, ctx, cfg){
    if (ref && ref.destroy) ref.destroy();
    return new Chart(ctx, cfg);
  }

  async function fetchJSON(url){ const r = await fetch(url); return r.json(); }

  // ---------- Lade Funktionen ----------
  async function loadDay(dateStr){
    const d = await fetchJSON('/api/day?date='+encodeURIComponent(dateStr));
    $('#currentDate').textContent = d.date;

    // KPIs
    const totalDay = sumObj(d.totals);
    $('#kpi-totalDay').textContent = totalDay;
    $('#kpi-peakHour').textContent = (d.kpis.peak_hour||0)+':00';
    $('#kpi-peakTotal').textContent = 'Spitze: '+(d.kpis.peak_total||0);
    $('#kpi-topBox').textContent = d.kpis.top_box || '–';
    $('#kpi-median').textContent = d.kpis.median_per_hour || 0;

    // Bar (Tag) — Klicks pro Kästchen
    chBarDay = createOrUpdate(chBarDay, $('#chartBarDay'), {
      type:'bar',
      data:{ labels:['A','B','C','D'],
        datasets:[{ label:'Klicks (Tag)', data:['A','B','C','D'].map(k=>d.totals[k]||0),
                    backgroundColor:['A','B','C','D'].map(k=>COLORS[k]) }]},
      options:{ responsive:true, plugins:{legend:{display:false}}, scales:{ y:{beginAtZero:true} } }
    });

    // Donut (Tag)
    chDonutDay = createOrUpdate(chDonutDay, $('#chartDonutDay'), {
      type:'doughnut',
      data:{ labels:['A','B','C','D'],
             datasets:[{ data:['A','B','C','D'].map(k=>d.totals[k]||0),
                         backgroundColor:['A','B','C','D'].map(k=>COLORS[k]) }] },
      options:{ responsive:true, plugins:{legend:{position:'bottom'}} }
    });

    // Stunden stacked
    const hours = d.hourly.map(r=>r.hour);
    const mkBar = key => ({ label:key, data:d.hourly.map(r=>r[key]||0), backgroundColor:COLORS[key], stack:'x' });
    chHourly = createOrUpdate(chHourly, $('#chartHourly'), {
      type:'bar',
      data:{ labels: hours, datasets:[mkBar('A'),mkBar('B'),mkBar('C'),mkBar('D')] },
      options:{ responsive:true, plugins:{legend:{position:'bottom'}}, scales:{ x:{stacked:true}, y:{stacked:true, beginAtZero:true} } }
    });

    // Kumuliert (Tag)
    let accA=0,accB=0,accC=0,accD=0;
    const cum = d.hourly.map(r=>({hour:r.hour, A:(accA+=r.A), B:(accB+=r.B), C:(accC+=r.C), D:(accD+=r.D)}));
    const mkLine = key => ({ label:key, data:cum.map(x=>x[key]), borderColor:COLORS[key], backgroundColor:COLORS[key], fill:false, tension:0.2 });
    chCum = createOrUpdate(chCum, $('#chartCum'), {
      type:'line',
      data:{ labels: cum.map(x=>x.hour), datasets:[mkLine('A'),mkLine('B'),mkLine('C'),mkLine('D')] },
      options:{ responsive:true, plugins:{legend:{position:'bottom'}}, scales:{ y:{beginAtZero:true} } }
    });
  }

  async function loadSeries30d(){
    const s = await fetchJSON('/api/series');
    const labels = s.series.map(r=>r.date);
    const mk = key => ({ label:key, data:s.series.map(r=>r[key]||0), borderColor:COLORS[key], backgroundColor:COLORS[key], fill:false, tension:0.25 });
    chSeries = createOrUpdate(chSeries, $('#chartSeries'), {
      type:'line',
      data:{ labels, datasets:[mk('A'),mk('B'),mk('C'),mk('D')] },
      options:{ responsive:true, interaction:{mode:'index', intersect:false}, scales:{ y:{beginAtZero:true} } }
    });
  }

  // ---------- UI / Routing ----------
  function goHome(){ show('#view-home'); history.replaceState({},'', '/'); }
  function goDash(){ show('#view-dash'); history.replaceState({},'', '/dashboard'); }

  function renderPresetButtons(){
    const c = $('#presetContainer');
    c.innerHTML = '';
    if (PRESET_DATES.length === 0){
      const hint = document.createElement('span');
      hint.className='text-zinc-500';
      hint.textContent='(Trage deine 3 Tage in PRESET_DATES im Code ein)';
      c.appendChild(hint);
      return;
    }
    PRESET_DATES.forEach(d=>{
      const b = document.createElement('button');
      b.className = 'text-sm border rounded-md px-2 py-1 hover:bg-white';
      b.textContent = d;
      b.onclick = async ()=>{ setToolbarDate(d); await loadDay(d); };
      c.appendChild(b);
    });
  }

  window.addEventListener('DOMContentLoaded', async ()=>{
    document.getElementById('year').textContent = new Date().getFullYear();
    renderPresetButtons();

    // Date Toolbar
    const today = fmtDateInput(new Date());
    setToolbarDate(today);
    $('#btnToday').onclick = async ()=>{ const v=fmtDateInput(new Date()); setToolbarDate(v); await loadDay(v); };
    $('#btnYesterday').onclick = async ()=>{
      const d=new Date(); d.setDate(d.getDate()-1);
      const v=fmtDateInput(d); setToolbarDate(v); await loadDay(v);
    };
    $('#dateInput').addEventListener('change', async (e)=>{ const v=e.target.value; setToolbarDate(v); await loadDay(v); });

    // toggle 30d Kontext
    $('#toggleContext').addEventListener('change', async (e)=>{
      const on = e.target.checked;
      $('#contextBlock').classList.toggle('hidden', !on);
      if (on && !chSeries) await loadSeries30d();
    });

    // nav
    $('#nav-home').onclick = goHome;
    $('#nav-start').onclick = goHome;
    $('#nav-dash').onclick = async ()=>{ goDash(); await loadDay($('#dateInput').value); };

    // boxes
    document.querySelectorAll('.boxBtn').forEach(btn=>{
      btn.addEventListener('click', async ()=>{
        const box = btn.getAttribute('data-box');
        try{
          await fetch('/api/click', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({box})});
        }catch(e){}
        goDash();
        await loadDay($('#dateInput').value);
      });
    });

    // initial route
    if (location.pathname === '/dashboard'){
      goDash();
      await loadDay($('#dateInput').value);
    } else {
      goHome();
    }
  });
  </script>
</body>
</html>
"""

@app.get("/")
def ui_root():
    init_db()
    resp = make_response(HTML)
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.get("/dashboard")
def ui_dash():
    return ui_root()

@app.route("/<path:subpath>")
def ui_catch_all(subpath):
    if subpath.startswith("api/"): abort(404)
    return ui_root()

if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(host="0.0.0.0", port=8000, debug=True)

