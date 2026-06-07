"""The live web app for substackgraph.com.

Dynamic, not static: every request reads the SQLite cache and runs the identity-resolution
harness on the fly (resolution is deterministic and cheap), then renders the force-directed
map. The before/after is a live toggle, and the decision log is exposed as an API — the
observability surface is the product.

Crawling is the one expensive, ToS-sensitive step. It is OFF by default in production: the
public site serves whatever neighborhoods are already cached. Set ALLOW_LIVE_CRAWL=1 to allow
on-demand crawls (rate-limited, background) for trusted deployments.
"""

from __future__ import annotations

import os
import threading

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from . import config
from .auditlog import AuditLog
from .cache import Cache
from .client import SubstackClient, normalize_url
from .crawl import crawl, load_raw_graph
from .naive_graph import build_naive
from .ratelimit import RateLimiter
from .render import graph_to_html  # noqa: F401 — kept for CLI render commands
from .resolve import resolve

ALLOW_LIVE_CRAWL = os.getenv("ALLOW_LIVE_CRAWL", "0") == "1"
DEFAULT_SEED = normalize_url(os.getenv("SUBSTACKGRAPH_SEED", "https://theairuntime.substack.com"))

app = FastAPI(title="substackgraph", description="Map and resolve the Substack recommendation network.")


@app.middleware("http")
async def security_headers(request, call_next):
    """Baseline hardening for a public site. HSTS assumes TLS is terminated upstream."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


_crawl_lock = threading.Lock()
_crawling: set[str] = set()


def _open_cache() -> Cache:
    config.ensure_dirs()
    return Cache(config.DB_PATH)


# ---------------------------------------------------------------------------
# Full-page SPA — vis-network force-directed graph, dark design
# ---------------------------------------------------------------------------

_MAIN_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>substackgraph</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/vis-network@9/standalone/umd/vis-network.min.js"></script>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:          #06070a;
  --surface:     #0d0e14;
  --surface2:    #111218;
  --border:      #1a1c26;
  --border2:     #22263a;
  --text:        #e2e8f0;
  --text2:       #8892a4;
  --text3:       #4a5568;
  --indigo:      #6366f1;
  --indigo2:     #818cf8;
  --rose:        #f43f5e;
  --cyan:        #22d3ee;
  --amber:       #f59e0b;
  --blue:        #3b82f6;
  --green:       #10b981;
  --header-h:    58px;
}

html, body { height: 100%; font-family: "Inter", -apple-system, "Segoe UI", Roboto, sans-serif;
  font-size: 14px; background: var(--bg); color: var(--text); overflow: hidden; }

/* ─── Header ─────────────────────────────────── */
#header {
  position: fixed; top: 0; left: 0; right: 0; z-index: 100;
  height: var(--header-h);
  background: rgba(13,14,20,.94);
  backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 16px;
  padding: 0 22px;
}

.logo {
  display: flex; align-items: center; gap: 9px;
  font-size: 15px; font-weight: 600; letter-spacing: -.2px;
  color: var(--text); text-decoration: none; white-space: nowrap; flex-shrink: 0;
}
.logo-badge {
  font-size: 11px; font-weight: 400; color: var(--text3);
  background: var(--surface2); border: 1px solid var(--border2);
  padding: 2px 7px; border-radius: 999px; margin-left: 2px;
}

/* mode toggle */
.toggle-wrap {
  display: flex; align-items: center;
  background: var(--bg); border: 1px solid var(--border2);
  border-radius: 9px; padding: 3px; gap: 2px;
  margin: 0 auto;
}
.toggle-btn {
  padding: 5px 18px; border: none; border-radius: 7px;
  font: 500 13px "Inter", sans-serif; cursor: pointer;
  transition: all .18s ease; background: transparent; color: var(--text2);
  white-space: nowrap;
}
.toggle-btn:hover:not(.active-resolved):not(.active-naive) {
  background: var(--surface2); color: var(--text);
}
.toggle-btn.active-resolved { background: var(--indigo); color: #fff; box-shadow: 0 0 0 1px rgba(99,102,241,.4); }
.toggle-btn.active-naive    { background: var(--rose);   color: #fff; box-shadow: 0 0 0 1px rgba(244,63,94,.4); }

/* header stats */
#hstats {
  display: flex; align-items: center; gap: 8px; margin-left: auto; flex-shrink: 0;
}
.hchip {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 4px 11px; border: 1px solid var(--border2); border-radius: 999px;
  font-size: 12px; color: var(--text2); background: var(--surface2);
  white-space: nowrap;
}
.hchip .dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.hc-nodes   .dot { background: var(--indigo); }
.hc-edges   .dot { background: var(--cyan); }
.hc-dec     .dot { background: var(--amber); cursor: pointer; }
.hc-dec     { cursor: pointer; }
.hc-dec:hover { border-color: var(--amber); color: var(--text); }

/* ─── Mode accent stripe ─────────────────────── */
#stripe { position: fixed; top: var(--header-h); left: 0; right: 0; height: 2px; z-index: 99; transition: background .3s; }

/* ─── Graph canvas ───────────────────────────── */
#gwrap { position: fixed; top: var(--header-h); left: 0; right: 0; bottom: 0; }
#gc    { width: 100%; height: 100%; background: var(--bg); }

/* ─── Loading overlay ────────────────────────── */
#loading {
  position: fixed; inset: 0; z-index: 200;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 18px;
  background: var(--bg); transition: opacity .4s;
}
#loading.gone { opacity: 0; pointer-events: none; }
.spinner {
  width: 38px; height: 38px; border: 3px solid var(--border2);
  border-top-color: var(--indigo); border-radius: 50%; animation: spin .75s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
#loading p { color: var(--text2); font-size: 13px; }

/* ─── Empty state ────────────────────────────── */
#empty {
  position: fixed; inset: var(--header-h) 0 0 0; z-index: 50;
  display: none; flex-direction: column; align-items: center; justify-content: center; gap: 14px;
}
#empty.show { display: flex; }
#empty h2   { font-size: 20px; font-weight: 600; }
#empty p    { color: var(--text2); font-size: 13px; max-width: 440px; text-align: center; line-height: 1.65; }
#empty code {
  background: var(--surface2); border: 1px solid var(--border2); border-radius: 8px;
  padding: 10px 18px; font-family: "SF Mono","Cascadia Code","Fira Code",monospace;
  font-size: 12px; color: var(--cyan); display: block; max-width: 500px; width: 90%;
}

/* ─── Search ─────────────────────────────────── */
#swrap {
  position: fixed; top: calc(var(--header-h) + 14px); left: 50%;
  transform: translateX(-50%); z-index: 30; width: min(300px, 90vw);
}
#search {
  width: 100%; background: rgba(13,14,20,.88); backdrop-filter: blur(10px);
  border: 1px solid var(--border2); border-radius: 9px;
  color: var(--text); font: 13px "Inter",sans-serif;
  padding: 8px 12px 8px 34px; outline: none; transition: border-color .18s;
}
#search:focus { border-color: var(--indigo); }
#search::placeholder { color: var(--text3); }
.sicon { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: var(--text3); pointer-events: none; }

/* ─── Legend ─────────────────────────────────── */
#legend {
  position: fixed; bottom: 20px; left: 20px; z-index: 30;
  background: rgba(13,14,20,.88); backdrop-filter: blur(10px);
  border: 1px solid var(--border2); border-radius: 10px; padding: 12px 14px;
  display: flex; flex-direction: column; gap: 7px;
}
.leg { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text2); }
.ldot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
#legend-hint { font-size: 11px; color: var(--text3); margin-top: 4px; border-top: 1px solid var(--border); padding-top: 8px; line-height: 1.6; }

/* ─── Decision bar ───────────────────────────── */
#decbar {
  position: fixed; bottom: 20px; right: 20px; z-index: 30;
  display: flex; flex-direction: column; align-items: flex-end; gap: 5px;
}
.dc {
  display: flex; align-items: center; gap: 6px;
  padding: 4px 11px; background: rgba(13,14,20,.88); backdrop-filter: blur(10px);
  border: 1px solid var(--border2); border-radius: 999px;
  font-size: 12px; color: var(--text2);
}
.dc .dd { width: 6px; height: 6px; border-radius: 50%; }
.dc-merge .dd { background: var(--green); }
.dc-refuse .dd { background: var(--rose); }
.dc-alias .dd { background: var(--cyan); }
.dc-drop .dd { background: var(--text3); }

/* ─── Side panel ─────────────────────────────── */
#panel {
  position: fixed; top: var(--header-h); right: 0; bottom: 0; width: 340px;
  background: var(--surface2); border-left: 1px solid var(--border);
  transform: translateX(100%); transition: transform .22s cubic-bezier(.4,0,.2,1);
  z-index: 40; overflow-y: auto; display: flex; flex-direction: column;
}
#panel.open { transform: translateX(0); }

.ph {
  padding: 16px 16px 13px; border-bottom: 1px solid var(--border);
  display: flex; align-items: flex-start; gap: 11px; flex-shrink: 0;
}
.ph-icon {
  width: 38px; height: 38px; border-radius: 9px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center; font-size: 18px;
}
.ph-text { flex: 1; min-width: 0; }
.ph-title { font-size: 15px; font-weight: 600; line-height: 1.3; word-break: break-all; }
.ph-sub   { font-size: 12px; color: var(--text2); margin-top: 3px; word-break: break-all; }
.ph-close {
  background: none; border: none; cursor: pointer; color: var(--text3);
  font-size: 18px; padding: 2px 5px; border-radius: 5px; transition: color .15s; flex-shrink: 0;
}
.ph-close:hover { color: var(--text); }

.pb { padding: 15px 16px; flex: 1; display: flex; flex-direction: column; gap: 16px; }

.ps h3 {
  font-size: 11px; font-weight: 600; letter-spacing: .06em;
  text-transform: uppercase; color: var(--text3); margin-bottom: 9px;
}
.srow {
  display: flex; justify-content: space-between; align-items: center;
  padding: 5px 0; border-bottom: 1px solid var(--border);
  font-size: 13px;
}
.srow:last-child { border-bottom: none; }
.srow .sl { color: var(--text2); }
.srow .sv { font-weight: 500; }

.dlist { display: flex; flex-direction: column; gap: 4px; }
.ditem {
  display: flex; align-items: center; gap: 7px; padding: 7px 9px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 7px;
  font-size: 12px; color: var(--text2); word-break: break-all;
  text-decoration: none; transition: border-color .15s, color .15s;
}
.ditem:hover { border-color: var(--indigo); color: var(--text); }
.ditem svg { flex-shrink: 0; color: var(--text3); }

.badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 500; margin-right: 4px; }
.b-merged  { background: rgba(245,158,11,.14); color: var(--amber); border: 1px solid rgba(245,158,11,.28); }
.b-hub     { background: rgba(99,102,241,.14); color: var(--indigo2); border: 1px solid rgba(99,102,241,.28); }
.b-conflict{ background: rgba(244,63,94,.14);  color: var(--rose);   border: 1px solid rgba(244,63,94,.28); }

/* ─── Scrollbar ──────────────────────────────── */
#panel::-webkit-scrollbar { width: 4px; }
#panel::-webkit-scrollbar-track { background: transparent; }
#panel::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 2px; }

/* ─── Responsive ─────────────────────────────── */
@media (max-width: 640px) {
  #hstats { display: none; }
  .logo-badge { display: none; }
  #panel { width: 100%; }
  #legend { display: none; }
}
</style>
</head>
<body>

<!-- ── Header ── -->
<header id="header">
  <a href="/" class="logo">
    <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
      <circle cx="11" cy="4"  r="3"   fill="#6366f1"/>
      <circle cx="18" cy="16" r="3"   fill="#22d3ee"/>
      <circle cx="4"  cy="16" r="3"   fill="#f59e0b"/>
      <line x1="11" y1="7"   x2="16.3" y2="13.3" stroke="#3a3f56" stroke-width="1.5"/>
      <line x1="11" y1="7"   x2="5.7"  y2="13.3" stroke="#3a3f56" stroke-width="1.5"/>
      <line x1="7"  y1="16"  x2="15"   y2="16"   stroke="#3a3f56" stroke-width="1.5"/>
    </svg>
    substackgraph
    <span class="logo-badge">Episode 1</span>
  </a>

  <div class="toggle-wrap">
    <button class="toggle-btn active-resolved" id="btn-resolved" onclick="setMode('resolved')">&#10022; Resolved</button>
    <button class="toggle-btn" id="btn-naive" onclick="setMode('naive')">&#9888; Naive</button>
  </div>

  <div id="hstats">
    <div class="hchip hc-nodes"  id="sc-nodes"><span class="dot"></span>&mdash;</div>
    <div class="hchip hc-edges"  id="sc-edges"><span class="dot"></span>&mdash;</div>
    <div class="hchip hc-dec"    id="sc-dec"   onclick="window.open('/api/decisions','_blank')" title="View full decision log"><span class="dot"></span>&mdash;</div>
  </div>
</header>

<!-- mode accent stripe -->
<div id="stripe"></div>

<!-- graph canvas -->
<div id="gwrap"><div id="gc"></div></div>

<!-- loading -->
<div id="loading">
  <div class="spinner"></div>
  <p id="loading-msg">Loading recommendation network&hellip;</p>
</div>

<!-- empty state -->
<div id="empty">
  <svg width="52" height="52" viewBox="0 0 52 52" fill="none" style="color:#4a5568">
    <circle cx="26" cy="26" r="24" stroke="currentColor" stroke-width="2"/>
    <path d="M18 26h16M26 18v16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
  </svg>
  <h2>No data yet</h2>
  <p>The cache is empty. Run a crawl with the CLI, then redeploy.</p>
  <code>substackgraph crawl --seed https://theairuntime.substack.com</code>
</div>

<!-- search -->
<div id="swrap">
  <svg class="sicon" width="14" height="14" viewBox="0 0 14 14" fill="none">
    <circle cx="6" cy="6" r="4.5" stroke="currentColor" stroke-width="1.5"/>
    <line x1="9.5" y1="9.5" x2="13" y2="13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
  </svg>
  <input id="search" placeholder="Filter publications&hellip;" oninput="onSearch(this.value)" autocomplete="off">
</div>

<!-- legend -->
<div id="legend">
  <div class="leg"><div class="ldot" style="background:#4f46e5"></div>Hub (&ge;3 in-links)</div>
  <div class="leg"><div class="ldot" style="background:#1e3a5f;border:1.5px solid #3b82f6"></div>Publication</div>
  <div class="leg"><div class="ldot" style="background:#b45309;border:1.5px solid #f59e0b"></div>Merged (multi-surface)</div>
  <div id="legend-hint">/ search &nbsp;&bull;&nbsp; r fit &nbsp;&bull;&nbsp; esc close<br>1 resolved &nbsp;&bull;&nbsp; 2 naive</div>
</div>

<!-- decision chips -->
<div id="decbar"></div>

<!-- side panel -->
<div id="panel">
  <div class="ph">
    <div class="ph-icon" id="pi">&#128240;</div>
    <div class="ph-text">
      <div class="ph-title" id="pt">Publication</div>
      <div class="ph-sub"   id="ps"></div>
    </div>
    <button class="ph-close" onclick="closePanel()">&#10005;</button>
  </div>
  <div class="pb" id="pb"></div>
</div>

<script>
// ── Constants ──────────────────────────────────────────────────────────────
var COLORS = {
  hub:      {background:'#312e81',border:'#6366f1',hover:{background:'#4338ca',border:'#818cf8'},highlight:{background:'#6366f1',border:'#a5b4fc'}},
  merged:   {background:'#78350f',border:'#f59e0b',hover:{background:'#92400e',border:'#fbbf24'},highlight:{background:'#b45309',border:'#fcd34d'}},
  single:   {background:'#0f2744',border:'#2563eb',hover:{background:'#1e3a5f',border:'#60a5fa'},highlight:{background:'#1d4ed8',border:'#93c5fd'}},
  conflict: {background:'#4c0519',border:'#f43f5e',hover:{background:'#881337',border:'#fb7185'},highlight:{background:'#be123c',border:'#fda4af'}},
  naive:    {background:'#0f172a',border:'#334155',hover:{background:'#1e293b',border:'#64748b'},highlight:{background:'#334155',border:'#94a3b8'}}
};

var VIS_OPTIONS = {
  nodes: {
    shape: 'dot',
    scaling: {min:10, max:42, label:{enabled:true,min:11,max:15,maxVisible:16,drawThreshold:6}},
    font: {color:'#c4cdd8',size:12,face:'Inter,-apple-system,sans-serif',strokeWidth:3,strokeColor:'#06070a'},
    borderWidth: 1.5,
    shadow: {enabled:true,color:'rgba(0,0,0,.5)',size:10,x:0,y:4},
  },
  edges: {
    color: {color:'#1a1e30',hover:'#6366f1',highlight:'#818cf8',opacity:.9},
    arrows: {to:{enabled:true,scaleFactor:.45,type:'arrow'}},
    width: 1.2, selectionWidth: 2.5,
    smooth: {type:'curvedCW',roundness:.07},
  },
  physics: {
    solver: 'barnesHut',
    barnesHut: {gravitationalConstant:-13000,centralGravity:.28,springLength:130,springConstant:.034,damping:.1,avoidOverlap:.25},
    stabilization: {enabled:true,iterations:300,updateInterval:25,fit:true},
    minVelocity: .5,
  },
  interaction: {
    hover:true, hoverConnectedEdges:true, tooltipDelay:80,
    zoomView:true, dragView:true, dragNodes:true,
    navigationButtons:false,
    keyboard:{enabled:true,speed:{x:10,y:10,zoom:.02}},
  },
  layout: {improvedLayout:true},
};

// ── State ──────────────────────────────────────────────────────────────────
var network=null, dsNodes=null, dsEdges=null, curMode='resolved', curData=null;

// ── Mode switch ────────────────────────────────────────────────────────────
function setMode(m) {
  if (m===curMode && curData) return;
  curMode = m;
  var br=document.getElementById('btn-resolved'), bn=document.getElementById('btn-naive');
  br.className='toggle-btn'+(m==='resolved'?' active-resolved':'');
  bn.className='toggle-btn'+(m==='naive'?' active-naive':'');
  document.getElementById('stripe').style.background = m==='resolved' ? '#6366f1' : '#f43f5e';
  document.getElementById('search').value='';
  closePanel();
  loadGraph(m);
}

// ── Load & render ──────────────────────────────────────────────────────────
function loadGraph(m) {
  showLoading(true,'Loading '+m+' graph…');
  fetch('/api/graph?mode='+m)
    .then(function(r){ return r.json(); })
    .then(function(d){
      curData=d;
      if (!d.nodes||!d.nodes.length){ showLoading(false); showEmpty(true); return; }
      showEmpty(false);
      renderNetwork(d,m);
      updateStats(d);
      updateDecBar(d);
    })
    .catch(function(e){ console.error(e); showLoading(false); });
}

function nodeColor(n, m) {
  if (m==='naive') return (n.ids_seen&&n.ids_seen.length>1) ? COLORS.conflict : COLORS.naive;
  if ((n.surfaces||1)>1) return COLORS.merged;
  if ((n.value||0)>=3)   return COLORS.hub;
  return COLORS.single;
}

function tooltip(n, m) {
  var lines=[], ds=(n.domains||[]).slice(0,4);
  if (m==='resolved') {
    if ((n.surfaces||1)>1) lines.push('<span style="color:#f59e0b">&#8853; '+n.surfaces+' surfaces merged</span>');
  } else {
    if (n.ids_seen&&n.ids_seen.length>1) lines.push('<span style="color:#f43f5e">&#9888; '+n.ids_seen.length+' pub IDs collapsed</span>');
  }
  if (ds.length) lines.push('<span style="color:#8892a4;font-size:11px">'+ds.map(esc).join('<br>')+'</span>');
  return '<div style="font:12px Inter,sans-serif;padding:9px 11px;max-width:240px;background:#111218;border:1px solid #22263a;border-radius:9px;color:#c4cdd8;line-height:1.6">'
    +'<b style="color:#e2e8f0">'+esc(n.label)+'</b>'
    +(lines.length?'<br>'+lines.join('<br>'):'')
    +'</div>';
}

function renderNetwork(d, m) {
  var vis_nodes = d.nodes.map(function(n){
    var s=n.surfaces||1;
    return {
      id:n.id,
      label: s>1 ? n.label+'\n('+s+'×)' : n.label,
      title: tooltip(n,m),
      value: Math.max(1,n.value||0),
      color: nodeColor(n,m),
      _raw:n
    };
  });
  var vis_edges = d.edges.map(function(e,i){ return {id:i,from:e.from,to:e.to}; });

  if (network) { network.destroy(); network=null; }

  dsNodes = new vis.DataSet(vis_nodes);
  dsEdges = new vis.DataSet(vis_edges);

  network = new vis.Network(document.getElementById('gc'),{nodes:dsNodes,edges:dsEdges},VIS_OPTIONS);

  network.on('stabilizationIterationsDone',function(){
    showLoading(false);
    network.setOptions({physics:{enabled:false}});
    network.fit({animation:{duration:700,easingFunction:'easeInOutQuad'}});
  });

  // fallback hide loading if no stabilization event fires
  setTimeout(function(){ showLoading(false); },10000);

  network.on('click',function(p){
    if (!p.nodes.length){ closePanel(); return; }
    var n=dsNodes.get(p.nodes[0]);
    if (n&&n._raw) openPanel(n._raw,m);
  });
  network.on('doubleClick',function(p){
    if (p.nodes.length) network.focus(p.nodes[0],{scale:1.5,animation:{duration:450}});
  });
}

// ── Side panel ─────────────────────────────────────────────────────────────
function openPanel(n,m) {
  // icon + color
  var iconBg='rgba(99,102,241,.14)', iconCh='&#128240;';
  if (m==='resolved'&&(n.surfaces||1)>1){ iconBg='rgba(245,158,11,.14)'; iconCh='&#8853;'; }
  else if (m==='naive'&&n.ids_seen&&n.ids_seen.length>1){ iconBg='rgba(244,63,94,.14)'; iconCh='&#9888;'; }
  else if ((n.value||0)>=3){ iconBg='rgba(99,102,241,.2)'; iconCh='&#9711;'; }

  document.getElementById('pi').style.background=iconBg;
  document.getElementById('pi').innerHTML=iconCh;
  document.getElementById('pt').textContent=n.label||String(n.id);
  document.getElementById('ps').textContent=(n.domains||[])[0]||'';

  var inDeg=network?network.getConnectedNodes(n.id,'from').length:'?';
  var outDeg=network?network.getConnectedNodes(n.id,'to').length:'?';

  var h='';

  // badges
  var bb='';
  if (m==='resolved'&&(n.surfaces||1)>1) bb+='<span class="badge b-merged">&#8853; merged '+(n.surfaces)+'&times;</span>';
  if ((n.value||0)>=3) bb+='<span class="badge b-hub">hub</span>';
  if (m==='naive'&&n.ids_seen&&n.ids_seen.length>1) bb+='<span class="badge b-conflict">&#9888; identity conflict</span>';
  if (bb) h+='<div style="margin-bottom:2px">'+bb+'</div>';

  // metrics
  h+='<div class="ps"><h3>Metrics</h3>';
  h+=srow('Recommendations received','<b>'+inDeg+'</b>');
  h+=srow('Recommendations given','<b>'+outDeg+'</b>');
  if (m==='resolved'){
    h+=srow('URL surfaces','<b>'+(n.surfaces||1)+'</b>');
    if (n.author_ids&&n.author_ids.length) h+=srow('Author IDs',esc(n.author_ids.join(', ')));
    if (n.subdomain) h+=srow('Subdomain',esc(n.subdomain));
  } else {
    if (n.ids_seen&&n.ids_seen.length) h+=srow('Pub IDs seen','<span style="color:'+(n.ids_seen.length>1?'#f43f5e':'inherit')+'">'+esc(n.ids_seen.join(', '))+'</span>');
  }
  h+='</div>';

  // domains
  var ds=n.domains||[];
  if (ds.length){
    h+='<div class="ps"><h3>Surfaces / URLs</h3><div class="dlist">';
    ds.forEach(function(d){
      var url=d.startsWith('http')?d:'https://'+d;
      h+='<a href="'+esc(url)+'" target="_blank" rel="noopener" class="ditem">';
      h+='<svg width="12" height="12" viewBox="0 0 12 12" fill="none"><circle cx="6" cy="6" r="5" stroke="currentColor" stroke-width="1.3"/><line x1="6" y1="1" x2="6" y2="11" stroke="currentColor" stroke-width="1.3"/><path d="M1.5 4.5h9M1.5 7.5h9" stroke="currentColor" stroke-width="1.3"/></svg>';
      h+=esc(d)+'</a>';
    });
    h+='</div></div>';
  }

  // substack link
  if (m==='resolved'&&n.subdomain){
    var sl='https://'+n.subdomain+'.substack.com';
    h+='<a href="'+esc(sl)+'" target="_blank" rel="noopener" class="ditem" style="justify-content:center;color:var(--indigo2);border-color:rgba(99,102,241,.3);margin-top:4px">&#8599; Open on Substack</a>';
  }

  document.getElementById('pb').innerHTML=h;
  document.getElementById('panel').classList.add('open');

  // highlight connected nodes
  if (network) {
    var conn=network.getConnectedNodes(n.id);
    conn.push(n.id);
    network.selectNodes(conn,false);
  }
}

function srow(l,v){ return '<div class="srow"><span class="sl">'+esc(l)+'</span><span class="sv">'+v+'</span></div>'; }

function closePanel() {
  document.getElementById('panel').classList.remove('open');
  if (network) network.unselectAll();
}

// ── Search / filter ────────────────────────────────────────────────────────
function onSearch(q) {
  if (!dsNodes||!dsEdges) return;
  q=q.trim().toLowerCase();
  if (!q) {
    dsNodes.update(dsNodes.get().map(function(n){ return {id:n.id,hidden:false}; }));
    dsEdges.update(dsEdges.get().map(function(e){ return {id:e.id,hidden:false}; }));
    return;
  }
  var hits=new Set();
  dsNodes.get().forEach(function(n){
    var r=n._raw||{}, txt=[n.label||''].concat(r.domains||[]).join(' ').toLowerCase();
    if (txt.indexOf(q)>=0) hits.add(n.id);
  });
  dsNodes.update(dsNodes.get().map(function(n){ return {id:n.id,hidden:!hits.has(n.id)}; }));
  dsEdges.update(dsEdges.get().map(function(e){ return {id:e.id,hidden:!hits.has(e.from)||!hits.has(e.to)}; }));
  if (hits.size) network.fit({nodes:Array.from(hits),animation:{duration:450}});
}

// ── Stats & decisions ──────────────────────────────────────────────────────
function updateStats(d) {
  var m=d.meta||{};
  setChip('sc-nodes',m.node_count||0,' nodes','hc-nodes');
  setChip('sc-edges',m.edge_count||0,' edges','hc-edges');
  var tot=m.decisions?Object.values(m.decisions).reduce(function(a,b){return a+b;},0):(m.dropped_edges||0)+(m.self_loops||0);
  setChip('sc-dec',tot,' decisions','hc-dec');
}

function setChip(id,val,suf,cls){
  var el=document.getElementById(id);
  el.className='hchip '+cls;
  el.innerHTML='<span class="dot"></span>'+val+suf;
}

function updateDecBar(d) {
  var bar=document.getElementById('decbar'); bar.innerHTML='';
  var m=d.meta||{};
  if (curMode==='resolved'&&m.decisions){
    var labels={merge:['dc-merge','merged'],refuse:['dc-refuse','refused'],alias:['dc-alias','aliased'],drop_404:['dc-drop','404 dropped'],drop_self_loop:['dc-drop','self-loops removed']};
    Object.entries(m.decisions).forEach(function(kv){
      var k=kv[0],v=kv[1], info=labels[k]||['dc-drop',k];
      bar.innerHTML+='<div class="dc '+info[0]+'"><span class="dd"></span>'+v+' '+info[1]+'</div>';
    });
  } else if (curMode==='naive') {
    if (m.dropped_edges) bar.innerHTML+='<div class="dc dc-drop"><span class="dd"></span>'+m.dropped_edges+' edges dropped</div>';
    if (m.self_loops)    bar.innerHTML+='<div class="dc dc-drop"><span class="dd"></span>'+m.self_loops+' self-loops</div>';
  }
}

// ── UI helpers ─────────────────────────────────────────────────────────────
function showLoading(v,msg){
  var el=document.getElementById('loading');
  el.style.display=v?'flex':'none';
  if (msg) document.getElementById('loading-msg').textContent=msg;
}
function showEmpty(v){ document.getElementById('empty').className=v?'show':''; }
function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

// ── Keyboard shortcuts ─────────────────────────────────────────────────────
document.addEventListener('keydown',function(e){
  var tag=document.activeElement.tagName;
  if (e.key==='Escape'){ closePanel(); var s=document.getElementById('search'); s.value=''; onSearch(''); }
  if (e.key==='/'&&tag!=='INPUT'){ e.preventDefault(); document.getElementById('search').focus(); }
  if (e.key==='r'&&tag!=='INPUT'&&network) network.fit({animation:{duration:600}});
  if (e.key==='1'&&tag!=='INPUT') setMode('resolved');
  if (e.key==='2'&&tag!=='INPUT') setMode('naive');
});

// ── Boot ───────────────────────────────────────────────────────────────────
document.getElementById('stripe').style.background='#6366f1';
setMode('resolved');
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/healthz")
def healthz():
    return {"status": "ok", "live_crawl": ALLOW_LIVE_CRAWL, "default_seed": DEFAULT_SEED}


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(_MAIN_PAGE)


@app.get("/api/graph")
def api_graph(mode: str = Query("resolved", pattern="^(resolved|naive)$")):
    cache = _open_cache()
    try:
        nodes, edges = load_raw_graph(cache)
    finally:
        cache.close()

    if mode == "naive":
        g, stats = build_naive(nodes, edges)
        vn_nodes = []
        for node_id, data in g.nodes(data=True):
            in_deg = g.in_degree(node_id)
            ids_seen = data.get("ids_seen", [])
            vn_nodes.append({
                "id": node_id,
                "label": data.get("label", str(node_id)),
                "value": max(1, in_deg),
                "domains": data.get("member_urls", []),
                "ids_seen": ids_seen,
                "group": "conflict" if len(ids_seen) > 1 else "naive",
            })
        vn_edges = [{"from": s, "to": d} for s, d in g.edges()]
        return JSONResponse({
            "nodes": vn_nodes,
            "edges": vn_edges,
            "meta": {
                "mode": "naive",
                "node_count": stats.node_count,
                "edge_count": stats.edge_count,
                "dropped_edges": stats.dropped_edges,
                "self_loops": stats.self_loops,
            },
        })

    # resolved
    audit = AuditLog()
    result = resolve(nodes, edges, audit=audit)
    vn_nodes = []
    for node in result.nodes:
        in_deg = result.graph.in_degree(node.canonical_id)
        surfaces = len(node.member_urls)
        label = node.display_name or node.subdomain or str(node.canonical_id)
        vn_nodes.append({
            "id": node.canonical_id,
            "label": label,
            "value": max(1, in_deg),
            "surfaces": surfaces,
            "domains": node.member_urls,
            "author_ids": node.author_ids,
            "subdomain": node.subdomain,
            "custom_domain": node.custom_domain,
            "group": "merged" if surfaces > 1 else ("hub" if in_deg >= 3 else "single"),
        })
    vn_edges = [{"from": s, "to": d} for s, d in result.edges]
    actions: dict[str, int] = {}
    for rec in audit.records:
        actions[rec["action"]] = actions.get(rec["action"], 0) + 1
    return JSONResponse({
        "nodes": vn_nodes,
        "edges": vn_edges,
        "meta": {
            "mode": "resolved",
            "node_count": len(result.nodes),
            "edge_count": len(result.edges),
            "decisions": actions,
        },
    })


@app.get("/api/decisions")
def api_decisions():
    cache = _open_cache()
    try:
        nodes, edges = load_raw_graph(cache)
    finally:
        cache.close()
    audit = AuditLog()
    resolve(nodes, edges, audit=audit)
    return JSONResponse({"count": len(audit.records), "decisions": audit.records})


def _run_crawl(seed: str) -> None:
    try:
        cache = _open_cache()
        try:
            crawl(seed, 2, cache, RateLimiter(), SubstackClient())
        finally:
            cache.close()
    finally:
        with _crawl_lock:
            _crawling.discard(seed)


@app.post("/crawl")
def trigger_crawl(seed: str = Query(...)):
    if not ALLOW_LIVE_CRAWL:
        return JSONResponse(
            {"error": "live crawling is disabled (set ALLOW_LIVE_CRAWL=1 to enable)"}, status_code=403
        )
    nseed = normalize_url(seed)
    with _crawl_lock:
        if nseed in _crawling:
            return JSONResponse({"status": "already_crawling", "seed": nseed}, status_code=202)
        _crawling.add(nseed)
    threading.Thread(target=_run_crawl, args=(nseed,), daemon=True).start()
    return JSONResponse({"status": "crawling", "seed": nseed}, status_code=202)


@app.get("/api/status")
def api_status():
    """Debug endpoint: DB row counts and last crawl log lines."""
    import sqlite3
    from pathlib import Path

    db = str(config.DB_PATH)
    rows: dict = {}
    try:
        conn = sqlite3.connect(db)
        total = conn.execute("SELECT COUNT(*) FROM http_cache").fetchone()[0]
        by_status = dict(conn.execute(
            "SELECT status, COUNT(*) FROM http_cache GROUP BY status"
        ).fetchall())
        marker = conn.execute(
            "SELECT payload_json FROM http_cache WHERE cache_key LIKE '_crawl_marker:%'"
        ).fetchone()
        conn.close()
        rows = {"total": total, "by_status": by_status, "crawl_marker": marker[0] if marker else None}
    except Exception as e:
        rows = {"error": str(e)}

    log_tail: list[str] = []
    log_path = Path("/tmp/crawl.log")
    if log_path.exists():
        lines = log_path.read_text().splitlines()
        log_tail = lines[-30:]

    return JSONResponse({
        "db_path": db,
        "db": rows,
        "crawl_log_tail": log_tail,
        "allow_live_crawl": ALLOW_LIVE_CRAWL,
        "seed_url": DEFAULT_SEED,
    })


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return "User-agent: *\nDisallow: /crawl\n"
