"use strict";
const $ = (id) => document.getElementById(id);
const els = {
  form: $("form"), target: $("target"), ra: $("ra"), dec: $("dec"), fov: $("fov"),
  detector: $("detector"), mode: $("mode"), max: $("max"), load: $("load"), status: $("status"),
  screen: $("screen"), play: $("play"), slider: $("slider"), speed: $("speed"), meta: $("meta"),
  gaia: $("gaia"), mp4: $("mp4"), mp4fps: $("mp4fps"), spec: $("spec"), specnote: $("specnote"),
};
const ctx = els.screen.getContext("2d");
ctx.imageSmoothingEnabled = false;

let frames = [];      // [{img: HTMLImageElement, meta}]
let timer = null;
let loadId = 0;       // descarta respuestas de cargas anteriores

const mjdToDate = (mjd) => new Date((mjd - 40587) * 86400000).toISOString().slice(0, 10);

function setStatus(msg, error = false) {
  els.status.textContent = msg;
  els.status.className = error ? "error" : "";
}

async function api(path, params) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") q.set(k, v);
  const r = await fetch(`${path}?${q}`);
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch (_) { /* sin cuerpo JSON */ }
    throw new Error(`${r.status}: ${detail}`);
  }
  return r.json();
}

function coordParams() {
  // Si hay objetivo se usa su id (con movimiento propio); si no, las coordenadas escritas.
  if (els.target.value) return { target: els.target.value };
  return { ra: els.ra.value, dec: els.dec.value };
}

function loadImage(b64) {
  return new Promise((ok, fail) => {
    const im = new Image();
    im.onload = () => ok(im);
    im.onerror = fail;
    im.src = "data:image/png;base64," + b64;
  });
}

function show(i) {
  if (!frames.length) return;
  const f = frames[i];
  ctx.clearRect(0, 0, els.screen.width, els.screen.height);
  ctx.drawImage(f.img, 0, 0, els.screen.width, els.screen.height);
  els.slider.value = i;
  const m = f.meta;
  const parts = [`${i + 1}/${frames.length}`, mjdToDate(m.mjd)];
  if (m.wavelength !== null && m.wavelength !== undefined) parts.push(`${m.wavelength.toFixed(3)} um`);
  if (m.mjd_vieja) parts[1] = `${mjdToDate(m.mjd_vieja)} -> ${mjdToDate(m.mjd)}`;
  if (m.n_apilados) parts.push(`${m.n_apilados} imagenes apiladas`);
  if (m.wavelength_min !== undefined && m.wavelength_min !== null)
    parts.push(`lambda ${m.wavelength_min.toFixed(2)}-${m.wavelength_max.toFixed(2)} um`);
  if (m.flag_bits) {
    const parcial = Object.entries(m.flag_bits).filter(([, v]) => v < 1).map(([b, v]) => `b${b}:${Math.round(v * 100)}%`);
    parts.push(`banderas: ${parcial.length ? parcial.join(" ") : "sin parciales"}`);
  }
  els.meta.textContent = parts.join("  |  ");
}

function stop() {
  clearInterval(timer);
  timer = null;
  els.play.textContent = "Reproducir";
}

function play() {
  stop();
  let i = Number(els.slider.value);
  els.play.textContent = "Pausa";
  timer = setInterval(() => { i = (i + 1) % frames.length; show(i); }, Number(els.speed.value));
}

function updateUrl() {
  const p = new URLSearchParams();
  if (els.target.value) p.set("target", els.target.value);
  else { p.set("ra", els.ra.value); p.set("dec", els.dec.value); }
  p.set("fov", els.fov.value); p.set("detector", els.detector.value); p.set("mode", els.mode.value);
  history.replaceState(null, "", "?" + p);
}

function updateMp4() {
  const mode = els.mode.value === "diff" ? "diff" : "normal";
  const q = new URLSearchParams({ ...coordParams(), fov: els.fov.value, detector: els.detector.value, mode, fps: els.mp4fps.value, max: els.max.value });
  els.mp4.href = `/export-mp4?${q}`;
  els.mp4.classList.toggle("disabled", els.mode.value === "stack");
}

async function loadGaia() {
  els.gaia.className = "badge";
  els.gaia.textContent = "Gaia: consultando...";
  try {
    const g = await api("/gaia-check", { ...coordParams(), radius: 10 });
    els.gaia.className = "badge " + (g.known ? "known" : "anomaly");
    els.gaia.textContent = g.known ? `Gaia: conocida (${g.n} fuentes)` : "Gaia: sin fuente (posible anomalia)";
  } catch (e) {
    els.gaia.textContent = "Gaia: no disponible";
  }
}

// Espectro: 6 bloques de 17 puntos (uno por detector), cada uno de un color.
const COLORS = ["#5aa9ff", "#3ddc97", "#ffd166", "#ff9f5a", "#ff6b9d", "#b28dff"];
function drawSpectrum(wl, fl) {
  const c = els.spec, g = c.getContext("2d");
  const W = c.width, H = c.height, L = 58, R = 12, T = 12, B = 36;
  g.clearRect(0, 0, W, H);
  const pts = wl.map((w, i) => ({ w, f: fl[i], d: Math.floor(i / 17) })).filter((p) => p.f !== null && p.w !== null);
  if (!pts.length) { g.fillStyle = "#8b97c4"; g.fillText("Sin datos", 20, 30); return; }
  const x0 = Math.min(...pts.map((p) => p.w)), x1 = Math.max(...pts.map((p) => p.w));
  let y0 = Math.min(...pts.map((p) => p.f)), y1 = Math.max(...pts.map((p) => p.f));
  if (y0 === y1) { y0 -= 1; y1 += 1; }
  const pad = (y1 - y0) * 0.08; y0 -= pad; y1 += pad;
  const X = (v) => L + ((v - x0) / (x1 - x0)) * (W - L - R);
  const Y = (v) => H - B - ((v - y0) / (y1 - y0)) * (H - T - B);
  g.strokeStyle = "#2b3566"; g.fillStyle = "#8b97c4"; g.font = "12px sans-serif"; g.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const yv = y0 + ((y1 - y0) * i) / 4, y = Y(yv);
    g.beginPath(); g.moveTo(L, y); g.lineTo(W - R, y); g.stroke();
    g.fillText(yv.toPrecision(3), 4, y + 4);
    const xv = x0 + ((x1 - x0) * i) / 4;
    g.fillText(xv.toFixed(2), X(xv) - 12, H - 18);
  }
  g.fillText("longitud de onda (um)", W / 2 - 60, H - 3);
  for (let d = 0; d < 6; d++) {
    const s = pts.filter((p) => p.d === d);
    g.strokeStyle = g.fillStyle = COLORS[d]; g.lineWidth = 2;
    g.beginPath();
    s.forEach((p, i) => (i ? g.lineTo(X(p.w), Y(p.f)) : g.moveTo(X(p.w), Y(p.f))));
    g.stroke();
    s.forEach((p) => { g.beginPath(); g.arc(X(p.w), Y(p.f), 2.5, 0, 6.3); g.fill(); });
  }
}

async function loadSpectrum(id) {
  els.specnote.textContent = "Calculando espectro...";
  try {
    const s = await api("/spectrum", { ...coordParams(), fov: els.fov.value, max: els.max.value });
    if (id !== loadId) return;
    drawSpectrum(s.wavelengths, s.flux);
    els.specnote.textContent = "Un color por detector (6 x 17 canales, apertura 3x3, sin resta de fondo).";
  } catch (e) {
    if (id !== loadId) return;
    drawSpectrum([], []);
    els.specnote.textContent = "Espectro no disponible: " + e.message;
  }
}

async function loadFrames(id) {
  const data = await api("/cutouts", {
    ...coordParams(), fov: els.fov.value, detector: els.detector.value, mode: els.mode.value, max: els.max.value,
  });
  const imgs = await Promise.all(data.frames.map((f) => loadImage(f.png_base64)));
  if (id !== loadId) return;
  frames = data.frames.map((f, i) => ({ img: imgs[i], meta: f }));
  els.slider.max = frames.length - 1;
  els.slider.disabled = els.play.disabled = frames.length < 2;
  show(0);
  setStatus(`${frames.length} cuadros (${data.origen === "local" ? "datos locales" : "descargados de IRSA"}).`);
  if (frames.length > 1) play();
}

els.form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  if (!els.target.value && (els.ra.value === "" || els.dec.value === "")) {
    setStatus("Escribe RA y Dec, o elige un objetivo.", true);
    return;
  }
  const id = ++loadId;
  stop();
  els.load.disabled = true;
  setStatus("Cargando... las coordenadas nuevas pueden tardar un minuto en descargarse de IRSA.");
  updateUrl(); updateMp4();
  loadGaia();
  loadSpectrum(id);
  try {
    await loadFrames(id);
  } catch (e) {
    if (id === loadId) { frames = []; ctx.clearRect(0, 0, 480, 480); els.meta.textContent = ""; setStatus(e.message, true); }
  } finally {
    if (id === loadId) els.load.disabled = false;
  }
});

els.play.addEventListener("click", () => (timer ? stop() : play()));
els.slider.addEventListener("input", () => { stop(); show(Number(els.slider.value)); });
els.speed.addEventListener("change", () => { if (timer) play(); });
els.mp4fps.addEventListener("change", updateMp4);
els.mode.addEventListener("change", updateMp4);

els.target.addEventListener("change", () => {
  const t = targets.find((x) => x.id === els.target.value);
  if (t) { els.ra.value = t.ra; els.dec.value = t.dec; }
  els.ra.readOnly = els.dec.readOnly = Boolean(t);
});
[els.ra, els.dec].forEach((e) => e.addEventListener("input", () => { els.target.value = ""; els.ra.readOnly = els.dec.readOnly = false; }));

let targets = [];
(async function init() {
  try {
    targets = await (await fetch("/targets")).json();
    for (const t of targets) els.target.add(new Option(t.nombre, t.id));
  } catch (_) { setStatus("No se pudo contactar con el servidor.", true); }
  const p = new URLSearchParams(location.search);
  if (p.get("target")) { els.target.value = p.get("target"); els.target.dispatchEvent(new Event("change")); }
  if (p.get("ra")) els.ra.value = p.get("ra");
  if (p.get("dec")) els.dec.value = p.get("dec");
  if (p.get("fov")) els.fov.value = p.get("fov");
  if (p.get("detector")) els.detector.value = p.get("detector");
  if (p.get("mode")) els.mode.value = p.get("mode");
  updateMp4();
  if (p.get("target") || (p.get("ra") && p.get("dec"))) els.form.requestSubmit();
})();
