"""Servidor HTTP e dashboard web integrado ao ingestor do ONS."""
from __future__ import annotations

import json
import logging
import math
import os
from collections import defaultdict
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import Config

log = logging.getLogger("ons_ingest.web")

SUBSISTEMAS_VALIDOS = ("N", "NE", "S", "SE")

_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SIN em Tempo Real — ONS</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
  <style>
    :root {
      --bg: #0f1419;
      --card: #161b22;
      --border: #262e38;
      --text: #e6edf3;
      --muted: #8b949e;
      --blue: #58a6ff;
      --orange: #f0883e;
      --green: #3fb950;
      --yellow: #d29922;
      --red: #f85149;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 20px;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 14px;
    }
    header {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
      padding-bottom: 14px;
      border-bottom: 1px solid var(--border);
    }
    h1 { margin: 0; font-size: 20px; font-weight: 600; }
    .subtitle { color: var(--muted); font-size: 12px; margin-top: 2px; }
    .controls {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
    }
    .toolbar {
      display: flex;
      flex-direction: column;
      gap: 8px;
      margin-bottom: 14px;
    }
    .control-group {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 6px 10px;
    }
    .group-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
      margin-right: 4px;
    }
    select, button {
      background: var(--bg);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 5px 10px;
      font-size: 13px;
      cursor: pointer;
    }
    button:hover { border-color: var(--blue); }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: var(--bg);
      color: var(--muted);
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 500;
      transition: all 0.15s ease;
    }
    .pill:hover { color: var(--text); border-color: var(--blue); }
    .pill.active {
      color: var(--text);
      background: rgba(88, 166, 255, 0.14);
      border-color: var(--blue);
    }
    .pill.isolated {
      box-shadow: 0 0 0 1px var(--blue);
      font-weight: 700;
    }
    .swatch {
      width: 10px;
      height: 10px;
      border-radius: 3px;
      display: inline-block;
      flex-shrink: 0;
    }
    .kpis {
      display: grid;
      grid-template-columns: repeat(6, minmax(150px, 1fr));
      gap: 12px;
      margin-bottom: 14px;
    }
    .kpi {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px 14px;
    }
    .kpi-label { color: var(--muted); font-size: 12px; margin-bottom: 6px; }
    .kpi-value { font-size: 22px; font-weight: 700; }
    .grid {
      display: grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 14px;
    }
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 14px;
      display: flex;
      flex-direction: column;
    }
    .card.hidden { display: none; }
    .card-head {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 8px;
    }
    .card h2 {
      margin: 0;
      font-size: 14px;
      font-weight: 600;
      color: var(--text);
    }
    .chart-legend {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-bottom: 8px;
    }
    .legend-item {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 3px 8px;
      border-radius: 6px;
      border: 1px solid var(--border);
      background: rgba(255, 255, 255, 0.02);
      color: var(--text);
      font-size: 12px;
      cursor: pointer;
      user-select: none;
      transition: opacity 0.15s ease, border-color 0.15s ease;
    }
    .legend-item:hover { border-color: var(--blue); }
    .legend-item.off { opacity: 0.35; text-decoration: line-through; }
    .span-8 { grid-column: span 8; }
    .span-4 { grid-column: span 4; }
    .span-6 { grid-column: span 6; }
    .span-12 { grid-column: span 12; }
    .chart-box { position: relative; height: 290px; width: 100%; }
    .chart-box.tall { height: 320px; }
    .table-wrap { overflow-x: auto; max-height: 360px; overflow-y: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td {
      text-align: left;
      padding: 8px 10px;
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }
    th { position: sticky; top: 0; background: var(--card); color: var(--muted); font-weight: 600; }
    .badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 700;
    }
    .badge-CRITICO { background: rgba(248, 81, 73, 0.18); color: var(--red); }
    .badge-ALTO { background: rgba(240, 136, 62, 0.18); color: var(--orange); }
    .banner {
      display: none;
      margin-bottom: 14px;
      padding: 10px 14px;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: var(--card);
      color: var(--orange);
    }
    .hint { color: var(--muted); font-size: 11px; }
    .c-blue { color: var(--blue); }
    .c-green { color: var(--green); }
    .c-orange { color: var(--orange); }
    .c-red { color: var(--red); }
    @media (max-width: 1100px) {
      .kpis { grid-template-columns: repeat(3, 1fr); }
      .span-8, .span-4, .span-6 { grid-column: span 12; }
    }
    @media (max-width: 640px) {
      .kpis { grid-template-columns: repeat(2, 1fr); }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>SIN em Tempo Real — ONS</h1>
      <div class="subtitle" id="status-line">Carregando dados...</div>
    </div>
    <div class="controls">
      <div class="control-group">
        <span class="group-label">Período:</span>
        <select id="days-select">
          <option value="1">24 horas</option>
          <option value="3" selected>3 dias</option>
          <option value="7">7 dias</option>
          <option value="14">14 dias</option>
          <option value="30">30 dias</option>
        </select>
      </div>
      <button id="refresh-btn" type="button">Atualizar</button>
    </div>
  </header>

  <section class="toolbar">
    <div class="control-group" id="panel-controls">
      <span class="group-label">Gráficos ativos:</span>
      <button type="button" class="pill active" data-panel-all="true">Todos os Gráficos</button>
      <button type="button" class="pill active" data-panel="matriz">Matriz × Carga</button>
      <button type="button" class="pill active" data-panel="pizza">Rosca Atual</button>
      <button type="button" class="pill active" data-panel="fc-eolica">FC Eólica</button>
      <button type="button" class="pill active" data-panel="fc-solar">FC Solar</button>
      <button type="button" class="pill active" data-panel="termica">Térmica Regional</button>
      <button type="button" class="pill active" data-panel="intercambio">Intercâmbio</button>
      <button type="button" class="pill active" data-panel="alertas">Alertas</button>
    </div>

    <div class="control-group" id="sub-controls">
      <span class="group-label">Região:</span>
      <button type="button" class="pill active" data-sub-all="true">Todas (SIN)</button>
      <button type="button" class="pill active" data-sub="N"><span class="swatch" style="background:#58a6ff"></span>N</button>
      <button type="button" class="pill active" data-sub="NE"><span class="swatch" style="background:#3fb950"></span>NE</button>
      <button type="button" class="pill active" data-sub="S"><span class="swatch" style="background:#d29922"></span>S</button>
      <button type="button" class="pill active" data-sub="SE"><span class="swatch" style="background:#f0883e"></span>SE</button>
      <span class="hint">Clique para isolar • Ctrl+Clique para múltipla seleção</span>
    </div>

    <div class="control-group" id="energy-controls">
      <span class="group-label">Tipo de energia:</span>
      <button type="button" class="pill active" data-energy-all="true">Todas as Fontes</button>
      <button type="button" class="pill active" data-energy="Hidráulica"><span class="swatch" style="background:#58a6ff"></span>Hidráulica</button>
      <button type="button" class="pill active" data-energy="Térmica"><span class="swatch" style="background:#f0883e"></span>Térmica</button>
      <button type="button" class="pill active" data-energy="Eólica"><span class="swatch" style="background:#3fb950"></span>Eólica</button>
      <button type="button" class="pill active" data-energy="Solar"><span class="swatch" style="background:#d29922"></span>Solar</button>
      <button type="button" class="pill active" data-energy="Carga"><span class="swatch" style="background:#e6edf3"></span>Carga</button>
      <span class="hint">Clique na fonte ou na cor da legenda do gráfico para isolar</span>
    </div>
  </section>

  <div id="banner" class="banner"></div>

  <section class="kpis">
    <div class="kpi"><div class="kpi-label" id="lbl-carga">Carga SIN (MWmed)</div><div class="kpi-value c-blue" id="kpi-carga">—</div></div>
    <div class="kpi"><div class="kpi-label">Geração total (MWmed)</div><div class="kpi-value c-blue" id="kpi-geracao">—</div></div>
    <div class="kpi"><div class="kpi-label">Renovável (hidr+eól+sol)</div><div class="kpi-value" id="kpi-renovavel">—</div></div>
    <div class="kpi"><div class="kpi-label">Térmica (MWmed)</div><div class="kpi-value" id="kpi-termica">—</div></div>
    <div class="kpi"><div class="kpi-label">Dado mais recente (Brasília)</div><div class="kpi-value c-blue" id="kpi-instante">—</div></div>
    <div class="kpi"><div class="kpi-label">Defasagem (min)</div><div class="kpi-value" id="kpi-defasagem">—</div></div>
  </section>

  <main class="grid">
    <section class="card span-8" data-card="matriz">
      <div class="card-head">
        <h2>Matriz energética × carga (MWmed)</h2>
        <span class="hint">Clique na cor para isolar tipo</span>
      </div>
      <div class="chart-legend" id="legend-matriz"></div>
      <div class="chart-box tall"><canvas id="chart-matriz"></canvas></div>
    </section>

    <section class="card span-4" data-card="pizza">
      <div class="card-head">
        <h2>Matriz no instante mais recente</h2>
        <span class="hint">Clique na cor ou fatia</span>
      </div>
      <div class="chart-legend" id="legend-pizza"></div>
      <div class="chart-box tall"><canvas id="chart-pizza"></canvas></div>
    </section>

    <section class="card span-6" data-card="fc-eolica">
      <div class="card-head">
        <h2>Fator de capacidade — eólica (proxy: máx. 365d)</h2>
        <span class="hint">Clique na cor para isolar região</span>
      </div>
      <div class="chart-legend" id="legend-fc-eolica"></div>
      <div class="chart-box"><canvas id="chart-fc-eolica"></canvas></div>
    </section>

    <section class="card span-6" data-card="fc-solar">
      <div class="card-head">
        <h2>Fator de capacidade — solar (proxy: máx. 365d)</h2>
        <span class="hint">Clique na cor para isolar região</span>
      </div>
      <div class="chart-legend" id="legend-fc-solar"></div>
      <div class="chart-box"><canvas id="chart-fc-solar"></canvas></div>
    </section>

    <section class="card span-6" data-card="termica">
      <div class="card-head">
        <h2>Geração térmica por subsistema (MWmed)</h2>
        <span class="hint">Clique na cor para isolar região</span>
      </div>
      <div class="chart-legend" id="legend-termica"></div>
      <div class="chart-box"><canvas id="chart-termica"></canvas></div>
    </section>

    <section class="card span-6" data-card="intercambio">
      <div class="card-head">
        <h2>Intercâmbio por subsistema (MWmed, + = importa)</h2>
        <span class="hint">Clique na cor para isolar região</span>
      </div>
      <div class="chart-legend" id="legend-intercambio"></div>
      <div class="chart-box"><canvas id="chart-intercambio"></canvas></div>
    </section>

    <section class="card span-12" data-card="alertas">
      <div class="card-head">
        <h2>Alertas de despacho térmico (z-score vs. 336h anteriores e rampa em 3h)</h2>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Instante (BRT)</th>
              <th>Subsistema</th>
              <th>Nível</th>
              <th>Térmica (MW)</th>
              <th>Média 14d (MW)</th>
              <th>Z-score</th>
              <th>Rampa 3h (MW)</th>
              <th>% da carga</th>
            </tr>
          </thead>
          <tbody id="alertas-body"></tbody>
        </table>
      </div>
    </section>
  </main>

  <script>
    const ALL_SUBS = ['N', 'NE', 'S', 'SE'];
    const ALL_ENERGIES = ['Hidráulica', 'Térmica', 'Eólica', 'Solar', 'Carga'];
    const ALL_PANELS = ['matriz', 'pizza', 'fc-eolica', 'fc-solar', 'termica', 'intercambio', 'alertas'];

    const SUB_COLORS = { N: '#58a6ff', NE: '#3fb950', S: '#d29922', SE: '#f0883e' };
    const ENERGY_COLORS = {
      'Hidráulica': '#58a6ff',
      'Térmica': '#f0883e',
      'Eólica': '#3fb950',
      'Solar': '#d29922',
      'Carga': '#e6edf3',
    };

    const state = {
      days: '3',
      subs: new Set(ALL_SUBS),
      energies: new Set(ALL_ENERGIES),
      panels: new Set(ALL_PANELS),
      lastData: null,
    };
    const charts = {};

    const fmtNum = (v, dec = 0) => v == null ? '—' : Number(v).toLocaleString('pt-BR', {
      minimumFractionDigits: dec, maximumFractionDigits: dec
    });

    const fmtLabel = (iso) => {
      const d = new Date(iso);
      return d.toLocaleString('pt-BR', {
        timeZone: 'America/Sao_Paulo', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'
      });
    };

    const baseLineOptions = (yOpts = {}) => ({
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: '#8b949e', maxTicksLimit: 10 }, grid: { color: '#21262d' } },
        y: { ticks: { color: '#8b949e' }, grid: { color: '#21262d' }, ...yOpts },
      },
    });

    function upsertChart(id, config) {
      if (charts[id]) charts[id].destroy();
      charts[id] = new Chart(document.getElementById(id), config);
    }

    function setKpi(id, text, cls) {
      const el = document.getElementById(id);
      el.textContent = text;
      el.className = 'kpi-value ' + (cls || '');
    }

    function toggleIsolateSet(setObj, allItems, item, multi) {
      if (multi) {
        if (setObj.has(item)) setObj.delete(item);
        else setObj.add(item);
        return;
      }
      if (setObj.size === 1 && setObj.has(item)) {
        allItems.forEach(x => setObj.add(x));
      } else {
        setObj.clear();
        setObj.add(item);
      }
    }

    function syncControlButtons() {
      document.querySelector('[data-panel-all]').classList.toggle('active', state.panels.size === ALL_PANELS.length);
      document.querySelectorAll('[data-panel]').forEach(btn => {
        btn.classList.toggle('active', state.panels.has(btn.dataset.panel));
      });
      document.querySelectorAll('[data-card]').forEach(card => {
        const on = state.panels.has(card.dataset.card);
        card.classList.toggle('hidden', !on);
      });

      document.querySelector('[data-sub-all]').classList.toggle('active', state.subs.size === ALL_SUBS.length);
      document.querySelectorAll('[data-sub]').forEach(btn => {
        const s = btn.dataset.sub;
        btn.classList.toggle('active', state.subs.has(s));
        btn.classList.toggle('isolated', state.subs.size === 1 && state.subs.has(s));
      });

      document.querySelector('[data-energy-all]').classList.toggle('active', state.energies.size === ALL_ENERGIES.length);
      document.querySelectorAll('[data-energy]').forEach(btn => {
        const e = btn.dataset.energy;
        btn.classList.toggle('active', state.energies.has(e));
        btn.classList.toggle('isolated', state.energies.size === 1 && state.energies.has(e));
      });

      const subLabel = state.subs.size === ALL_SUBS.length
        ? 'Carga SIN (MWmed)'
        : `Carga (${Array.from(state.subs).join(', ') || 'nenhuma'})`;
      document.getElementById('lbl-carga').textContent = subLabel;
    }

    function buildInteractiveLegend(containerId, items, activeSet, onSelect) {
      const box = document.getElementById(containerId);
      box.innerHTML = '';
      items.forEach(({ key, color, label }) => {
        const el = document.createElement('button');
        el.type = 'button';
        el.className = 'legend-item' + (activeSet.has(key) ? '' : ' off');
        el.title = 'Clique para isolar • Ctrl+Clique para alternar';
        el.innerHTML = `<span class="swatch" style="background:${color}"></span><span>${label || key}</span>`;
        el.addEventListener('click', (ev) => onSelect(key, ev.ctrlKey || ev.metaKey || ev.shiftKey));
        box.appendChild(el);
      });
    }

    function selectEnergy(name, multi) {
      toggleIsolateSet(state.energies, ALL_ENERGIES, name, multi);
      syncControlButtons();
      if (state.lastData) render(state.lastData);
    }

    function selectSub(sub, multi) {
      toggleIsolateSet(state.subs, ALL_SUBS, sub, multi);
      syncControlButtons();
      load();
    }

    function renderSubLines(canvasId, legendId, data, isPct = false) {
      const labels = (data.timestamps || []).map(fmtLabel);
      const seriesEntries = Object.entries(data.series || {});
      const datasets = seriesEntries.map(([sub, values]) => ({
        label: sub,
        data: isPct ? values.map(v => v == null ? null : v * 100) : values,
        borderColor: SUB_COLORS[sub] || '#58a6ff',
        backgroundColor: SUB_COLORS[sub] || '#58a6ff',
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.15,
      }));
      const yOpts = isPct ? { min: 0, max: 100, ticks: { color: '#8b949e', callback: v => v + '%' } } : {};
      upsertChart(canvasId, { type: 'line', data: { labels, datasets }, options: baseLineOptions(yOpts) });

      buildInteractiveLegend(
        legendId,
        ALL_SUBS.map(s => ({ key: s, color: SUB_COLORS[s], label: s })),
        state.subs,
        selectSub
      );
    }

    function render(data) {
      state.lastData = data;
      const banner = document.getElementById('banner');
      const k = data.kpis || {};
      if (state.subs.size === 0) {
        banner.style.display = 'block';
        banner.textContent = 'Nenhuma região selecionada. Clique em "Todas (SIN)" ou escolha uma região.';
      } else if (!k.ultimo_instante) {
        banner.style.display = 'block';
        banner.textContent = 'Aguardando conclusão da carga inicial no banco de dados...';
      } else {
        banner.style.display = 'none';
      }

      setKpi('kpi-carga', fmtNum(k.carga_sin), 'c-blue');
      setKpi('kpi-geracao', fmtNum(k.geracao_total), 'c-blue');
      setKpi('kpi-renovavel', k.pct_renovavel == null ? '—' : fmtNum(k.pct_renovavel, 1) + '%',
        k.pct_renovavel >= 85 ? 'c-green' : 'c-orange');
      setKpi('kpi-termica', fmtNum(k.termica_sin),
        k.termica_sin >= 15000 ? 'c-red' : (k.termica_sin >= 8000 ? 'c-orange' : 'c-green'));
      setKpi('kpi-instante', k.ultimo_instante || '—', 'c-blue');
      const def = k.defasagem_min;
      setKpi('kpi-defasagem', def == null ? '—' : fmtNum(def) + ' min',
        def >= 720 ? 'c-red' : (def >= 180 ? 'c-orange' : 'c-green'));

      const mh = data.matriz_horaria || [];
      const labelsM = mh.map(r => fmtLabel(r.ts));
      const matrixDefs = [
        { key: 'Carga', field: 'carga', color: '#e6edf3', bg: '#e6edf3', fill: false, stack: 'carga', order: 0, width: 2 },
        { key: 'Hidráulica', field: 'hidraulica', color: '#58a6ff', bg: 'rgba(88,166,255,0.65)', fill: true, stack: 'm', order: 1, width: 1 },
        { key: 'Térmica', field: 'termica', color: '#f0883e', bg: 'rgba(240,136,62,0.70)', fill: true, stack: 'm', order: 2, width: 1 },
        { key: 'Eólica', field: 'eolica', color: '#3fb950', bg: 'rgba(63,185,80,0.70)', fill: true, stack: 'm', order: 3, width: 1 },
        { key: 'Solar', field: 'solar', color: '#d29922', bg: 'rgba(210,153,34,0.75)', fill: true, stack: 'm', order: 4, width: 1 },
      ];
      upsertChart('chart-matriz', {
        type: 'line',
        data: {
          labels: labelsM,
          datasets: matrixDefs.map(d => ({
            label: d.key,
            data: mh.map(r => r[d.field]),
            borderColor: d.color,
            backgroundColor: d.bg,
            fill: d.fill,
            stack: d.stack,
            borderWidth: d.width,
            pointRadius: 0,
            order: d.order,
            hidden: !state.energies.has(d.key),
          })),
        },
        options: baseLineOptions({ stacked: true }),
      });
      buildInteractiveLegend(
        'legend-matriz',
        ALL_ENERGIES.map(e => ({ key: e, color: ENERGY_COLORS[e], label: e })),
        state.energies,
        selectEnergy
      );

      const mi = data.matriz_instante || {};
      const pieSources = [
        { key: 'Hidráulica', val: mi.hidraulica || 0 },
        { key: 'Térmica', val: mi.termica || 0 },
        { key: 'Eólica', val: mi.eolica || 0 },
        { key: 'Solar', val: mi.solar || 0 },
      ];
      const activePie = pieSources.filter(s => state.energies.has(s.key));
      const pieDisplay = activePie.length ? activePie : pieSources;
      const pieTotal = pieDisplay.reduce((a, b) => a + b.val, 0) || 1;
      upsertChart('chart-pizza', {
        type: 'doughnut',
        data: {
          labels: pieDisplay.map(s => s.key),
          datasets: [{
            data: pieDisplay.map(s => s.val),
            backgroundColor: pieDisplay.map(s => ENERGY_COLORS[s.key]),
            borderColor: '#161b22',
            borderWidth: 2,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          onClick: (_evt, elements) => {
            if (elements.length > 0) {
              const label = pieDisplay[elements[0].index].key;
              selectEnergy(label, false);
            }
          },
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: (ctx) => {
                  const pct = ((ctx.parsed / pieTotal) * 100).toFixed(1);
                  return `${ctx.label}: ${fmtNum(ctx.parsed)} MW (${pct}%)`;
                },
              },
            },
          },
        },
      });
      buildInteractiveLegend(
        'legend-pizza',
        pieSources.map(s => ({
          key: s.key,
          color: ENERGY_COLORS[s.key],
          label: `${s.key} (${fmtNum(s.val)} MW)`,
        })),
        state.energies,
        selectEnergy
      );

      renderSubLines('chart-fc-eolica', 'legend-fc-eolica', data.fc_eolica || {}, true);
      renderSubLines('chart-fc-solar', 'legend-fc-solar', data.fc_solar || {}, true);
      renderSubLines('chart-termica', 'legend-termica', data.termica_sub || {}, false);
      renderSubLines('chart-intercambio', 'legend-intercambio', data.intercambio_sub || {}, false);

      const tbody = document.getElementById('alertas-body');
      const alertas = data.alertas || [];
      if (!alertas.length) {
        tbody.innerHTML = '<tr><td colspan="8" style="color:#8b949e">Nenhum alerta no período/regiões selecionadas.</td></tr>';
      } else {
        tbody.innerHTML = alertas.map(a => `
          <tr>
            <td>${a.instante}</td>
            <td>${a.subsistema}</td>
            <td><span class="badge badge-${a.nivel}">${a.nivel}</span></td>
            <td>${fmtNum(a.ger_termica)}</td>
            <td>${fmtNum(a.media_14d)}</td>
            <td>${fmtNum(a.zscore, 2)}</td>
            <td>${fmtNum(a.rampa_3h)}</td>
            <td>${fmtNum(a.pct_carga, 1)}%</td>
          </tr>
        `).join('');
      }

      document.getElementById('status-line').textContent =
        'Atualizado em ' + new Date().toLocaleTimeString('pt-BR') + ' · Atualização automática a cada 60s';
    }

    async function load() {
      const days = document.getElementById('days-select').value;
      const subs = Array.from(state.subs);
      try {
        const res = await fetch(`/api/dashboard?days=${encodeURIComponent(days)}&subsistemas=${encodeURIComponent(subs.join(','))}`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        render(data);
      } catch (err) {
        const banner = document.getElementById('banner');
        banner.style.display = 'block';
        banner.textContent = 'Erro ao carregar dados: ' + err.message;
      }
    }

    document.querySelector('[data-panel-all]').addEventListener('click', () => {
      ALL_PANELS.forEach(p => state.panels.add(p));
      syncControlButtons();
      Object.values(charts).forEach(c => c.resize());
    });
    document.querySelectorAll('[data-panel]').forEach(btn => {
      btn.addEventListener('click', () => {
        const p = btn.dataset.panel;
        if (state.panels.has(p)) state.panels.delete(p);
        else state.panels.add(p);
        syncControlButtons();
        Object.values(charts).forEach(c => c.resize());
      });
    });

    document.querySelector('[data-sub-all]').addEventListener('click', () => {
      ALL_SUBS.forEach(s => state.subs.add(s));
      syncControlButtons();
      load();
    });
    document.querySelectorAll('[data-sub]').forEach(btn => {
      btn.addEventListener('click', (ev) => selectSub(btn.dataset.sub, ev.ctrlKey || ev.metaKey || ev.shiftKey));
    });

    document.querySelector('[data-energy-all]').addEventListener('click', () => {
      ALL_ENERGIES.forEach(e => state.energies.add(e));
      syncControlButtons();
      if (state.lastData) render(state.lastData);
    });
    document.querySelectorAll('[data-energy]').forEach(btn => {
      btn.addEventListener('click', (ev) => selectEnergy(btn.dataset.energy, ev.ctrlKey || ev.metaKey || ev.shiftKey));
    });

    document.getElementById('days-select').addEventListener('change', load);
    document.getElementById('refresh-btn').addEventListener('click', load);

    syncControlButtons();
    load();
    setInterval(load, 60000);
  </script>
</body>
</html>
"""


def _num(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, Decimal):
        val = float(val)
    if isinstance(val, (int, float)):
        return None if math.isnan(val) else float(val)
    return val


def _pivot_series(
    rows: list[tuple[Any, str, Any]],
    subsistemas: list[str],
) -> dict[str, Any]:
    """Alinha séries temporais por subsistema num eixo de timestamps compartilhado."""
    by_ts: dict[str, dict[str, float | None]] = defaultdict(dict)
    present_subs: set[str] = set()
    for ts, sub, val in rows:
        iso = ts.isoformat()
        by_ts[iso][sub] = _num(val)
        present_subs.add(sub)
    timestamps = sorted(by_ts.keys())
    ordered_subs = [s for s in subsistemas if s in present_subs]
    series = {sub: [by_ts[t].get(sub) for t in timestamps] for sub in ordered_subs}
    return {"timestamps": timestamps, "series": series}


def _parse_params(query: str) -> tuple[int, list[str]]:
    qs = parse_qs(query, keep_blank_values=True)
    try:
        days = int(qs.get("days", ["3"])[0])
    except ValueError:
        days = 3
    days = max(1, min(days, 365))

    if "subsistemas" not in qs:
        return days, list(SUBSISTEMAS_VALIDOS)
    raw = qs["subsistemas"][0]
    subs = [s.strip().upper() for s in raw.split(",") if s.strip().upper() in SUBSISTEMAS_VALIDOS]
    return days, subs


def query_dashboard(database_url: str, days: int, subsistemas: list[str]) -> dict[str, Any]:
    """Consulta o PostgreSQL e monta o payload JSON do dashboard."""
    import psycopg

    with psycopg.connect(database_url, connect_timeout=10) as conn:
        kpi_row = conn.execute(
            """
            WITH u AS (SELECT ts FROM v_ultimo_instante)
            SELECT
                sum(b.carga),
                sum(b.ger_hidraulica + b.ger_termica + b.ger_eolica + b.ger_solar),
                100.0 * sum(b.ger_hidraulica + b.ger_eolica + b.ger_solar)
                    / NULLIF(sum(b.ger_hidraulica + b.ger_termica + b.ger_eolica + b.ger_solar), 0),
                sum(b.ger_termica),
                to_char(u.ts AT TIME ZONE 'America/Sao_Paulo', 'DD/MM HH24:MI'),
                round(extract(epoch FROM now() - u.ts) / 60.0)
            FROM u
            LEFT JOIN balanco_subsistema b
              ON b.ts = u.ts AND b.subsistema = ANY(%s)
            GROUP BY u.ts
            """,
            (subsistemas,),
        ).fetchone()

        kpis = {
            "carga_sin": _num(kpi_row[0]) if kpi_row else None,
            "geracao_total": _num(kpi_row[1]) if kpi_row else None,
            "pct_renovavel": _num(kpi_row[2]) if kpi_row else None,
            "termica_sin": _num(kpi_row[3]) if kpi_row else None,
            "ultimo_instante": kpi_row[4] if kpi_row else None,
            "defasagem_min": _num(kpi_row[5]) if kpi_row else None,
        }

        matriz_rows = conn.execute(
            """
            WITH u AS (SELECT ts FROM v_ultimo_instante)
            SELECT b.ts,
                   sum(b.ger_hidraulica),
                   sum(b.ger_termica),
                   sum(b.ger_eolica),
                   sum(b.ger_solar),
                   sum(b.carga)
            FROM balanco_subsistema b, u
            WHERE u.ts IS NOT NULL
              AND b.ts > u.ts - make_interval(days => %s)
              AND b.subsistema = ANY(%s)
            GROUP BY b.ts
            ORDER BY b.ts
            """,
            (days, subsistemas),
        ).fetchall()

        inst_row = conn.execute(
            """
            WITH u AS (SELECT ts FROM v_ultimo_instante)
            SELECT
                COALESCE(sum(b.ger_hidraulica), 0),
                COALESCE(sum(b.ger_termica), 0),
                COALESCE(sum(b.ger_eolica), 0),
                COALESCE(sum(b.ger_solar), 0)
            FROM balanco_subsistema b, u
            WHERE u.ts IS NOT NULL
              AND b.ts = u.ts
              AND b.subsistema = ANY(%s)
            """,
            (subsistemas,),
        ).fetchone()

        fc_rows = conn.execute(
            """
            WITH u AS (SELECT ts FROM v_ultimo_instante)
            SELECT f.ts, f.subsistema, f.fonte, f.fator_capacidade
            FROM v_fator_capacidade f, u
            WHERE u.ts IS NOT NULL
              AND f.ts > u.ts - make_interval(days => %s)
              AND f.fonte IN ('eolica', 'solar')
              AND f.subsistema = ANY(%s)
            ORDER BY f.ts, f.subsistema
            """,
            (days, subsistemas),
        ).fetchall()

        sub_rows = conn.execute(
            """
            WITH u AS (SELECT ts FROM v_ultimo_instante)
            SELECT b.ts, b.subsistema, b.ger_termica, b.intercambio
            FROM balanco_subsistema b, u
            WHERE u.ts IS NOT NULL
              AND b.ts > u.ts - make_interval(days => %s)
              AND b.subsistema = ANY(%s)
            ORDER BY b.ts, b.subsistema
            """,
            (days, subsistemas),
        ).fetchall()

        alert_rows = conn.execute(
            """
            WITH u AS (SELECT ts FROM v_ultimo_instante)
            SELECT to_char(a.ts AT TIME ZONE 'America/Sao_Paulo', 'DD/MM/YYYY HH24:MI'),
                   a.subsistema,
                   a.nivel,
                   a.ger_termica,
                   a.media_14d,
                   a.zscore,
                   a.rampa_3h,
                   a.pct_carga
            FROM v_alertas_termico a, u
            WHERE u.ts IS NOT NULL
              AND a.ts > u.ts - make_interval(days => %s)
              AND a.subsistema = ANY(%s)
            ORDER BY a.ts DESC
            LIMIT 200
            """,
            (days, subsistemas),
        ).fetchall()

    return {
        "kpis": kpis,
        "matriz_horaria": [
            {
                "ts": r[0].isoformat(),
                "hidraulica": _num(r[1]),
                "termica": _num(r[2]),
                "eolica": _num(r[3]),
                "solar": _num(r[4]),
                "carga": _num(r[5]),
            }
            for r in matriz_rows
        ],
        "matriz_instante": {
            "hidraulica": _num(inst_row[0]) if inst_row else 0,
            "termica": _num(inst_row[1]) if inst_row else 0,
            "eolica": _num(inst_row[2]) if inst_row else 0,
            "solar": _num(inst_row[3]) if inst_row else 0,
        },
        "fc_eolica": _pivot_series(
            [(ts, sub, val) for ts, sub, fonte, val in fc_rows if fonte == "eolica"], subsistemas
        ),
        "fc_solar": _pivot_series(
            [(ts, sub, val) for ts, sub, fonte, val in fc_rows if fonte == "solar"], subsistemas
        ),
        "termica_sub": _pivot_series([(ts, sub, gt) for ts, sub, gt, _ in sub_rows], subsistemas),
        "intercambio_sub": _pivot_series(
            [(ts, sub, ic) for ts, sub, _, ic in sub_rows], subsistemas
        ),
        "alertas": [
            {
                "instante": r[0],
                "subsistema": r[1],
                "nivel": r[2],
                "ger_termica": _num(r[3]),
                "media_14d": _num(r[4]),
                "zscore": _num(r[5]),
                "rampa_3h": _num(r[6]),
                "pct_carga": _num(r[7]),
            }
            for r in alert_rows
        ],
    }


def _make_handler(cfg: Config) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._send(HTTPStatus.OK, "application/json; charset=utf-8", b'{"status":"ok"}')
                return
            if parsed.path == "/api/dashboard":
                try:
                    days, subs = _parse_params(parsed.query)
                    payload = query_dashboard(cfg.database_url, days, subs)
                    self._send(
                        HTTPStatus.OK,
                        "application/json; charset=utf-8",
                        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    )
                except Exception as exc:
                    log.exception("erro em /api/dashboard")
                    err = json.dumps({"error": str(exc)}).encode("utf-8")
                    self._send(HTTPStatus.INTERNAL_SERVER_ERROR, "application/json; charset=utf-8", err)
                return
            if parsed.path in ("/", "/index.html"):
                self._send(HTTPStatus.OK, "text/html; charset=utf-8", _HTML.encode("utf-8"))
                return
            self._send(HTTPStatus.NOT_FOUND, "application/json; charset=utf-8", b'{"error":"not found"}')

        def log_message(self, format: str, *args: Any) -> None:
            log.debug("http: " + format, *args)

    return Handler


def make_server(cfg: Config, port: int | None = None) -> ThreadingHTTPServer:
    """Cria o servidor HTTP do dashboard sem iniciar o loop de eventos."""
    bind_port = int(os.getenv("PORT", "8000")) if port is None else port
    ThreadingHTTPServer.allow_reuse_address = True
    return ThreadingHTTPServer(("0.0.0.0", bind_port), _make_handler(cfg))


def serve(cfg: Config, port: int | None = None) -> None:
    """Inicia o servidor HTTP do dashboard na porta configurada."""
    server = make_server(cfg, port)
    log.info("dashboard web escutando em http://0.0.0.0:%d", server.server_address[1])
    server.serve_forever()
