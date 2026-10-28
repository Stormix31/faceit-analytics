/* ============ Faceit Analytics — фронтенд-логика ============ */
"use strict";

const API = "";  // базовый URL (тот же origin)
let TOKEN = localStorage.getItem("fa_token") || null;
let ME = null;
let CAPTCHA = null;   // {token, question} для формы входа
let QUOTA = null;

// ==================== Утилиты ====================

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return Array.from(document.querySelectorAll(sel)); }

function toast(msg, type = "ok", ms = 4000) {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  $("#toastZone").appendChild(el);
  setTimeout(() => el.remove(), ms);
}

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (TOKEN) headers["Authorization"] = `Bearer ${TOKEN}`;
  if (opts.body && !(opts.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
  const resp = await fetch(API + path, { ...opts, headers });
  let data = null;
  try { data = await resp.json(); } catch (_) {}
  if (!resp.ok) {
    const detail = data?.detail ?? data?.error ?? resp.statusText;
    const err = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    err.status = resp.status;
    err.data = detail;
    throw err;
  }
  return data;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function initials(name) {
  return (name || "?").split(/\s+/).map(w => w[0]).slice(0, 2).join("").toUpperCase();
}

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

// ==================== Навигация / шапка ====================

function initNav() {
  $("#burger").addEventListener("click", () => $(".site-header").classList.toggle("nav-open"));
  $$("[data-nav]").forEach(a => a.addEventListener("click", e => {
    $(".site-header").classList.remove("nav-open");
  }));
}

function renderAuthArea() {
  const loggedIn = !!TOKEN;
  $("#authArea").classList.toggle("hidden", loggedIn);
  $("#userArea").classList.toggle("hidden", !loggedIn);
  if (loggedIn && ME) {
    $("#userChip").textContent = `👤 ${ME.username} · ${ME.subscription_tier === "pro" ? "PRO" : "Free"}`;
  }
}

// ==================== Модалка авторизации ====================

function openAuthModal(tab = "login") {
  $("#authModal").classList.remove("hidden");
  switchTab(tab);
  if (tab === "login") loadCaptcha();
}
function closeAuthModal() { $("#authModal").classList.add("hidden"); }

function switchTab(tab) {
  $$(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === tab));
  $("#loginForm").classList.toggle("hidden", tab !== "login");
  $("#registerForm").classList.toggle("hidden", tab !== "register");
}

async function loadCaptcha() {
  try {
    CAPTCHA = await api("/api/auth/captcha");
    $("#loginCaptchaQ").textContent = `Проверка: ${CAPTCHA.question}`;
    $("#loginCaptchaAnswer").value = "";
  } catch (e) {
    $("#loginCaptchaQ").textContent = "Капча временно недоступна";
  }
}

function initAuthModal() {
  $("#btnLogin").addEventListener("click", () => openAuthModal("login"));
  $("#btnRegister").addEventListener("click", () => openAuthModal("register"));
  $("#btnLogout").addEventListener("click", logout);
  $("#authModalClose").addEventListener("click", closeAuthModal);
  $("#authModal").addEventListener("click", e => { if (e.target.id === "authModal") closeAuthModal(); });
  $$(".tab").forEach(t => t.addEventListener("click", () => {
    switchTab(t.dataset.tab);
    if (t.dataset.tab === "login") loadCaptcha();
  }));
  $("#captchaRefresh").addEventListener("click", loadCaptcha);

  // --- Логин ---
  $("#loginForm").addEventListener("submit", async e => {
    e.preventDefault();
    $("#loginError").textContent = "";
    const body = {
      email: $("#loginEmail").value.trim(),
      password: $("#loginPassword").value,
    };
    if (CAPTCHA) {
      body.captcha_token = CAPTCHA.token;
      body.captcha_answer = $("#loginCaptchaAnswer").value.trim();
    }
    try {
      const data = await api("/api/auth/login", { method: "POST", body });
      onLoggedIn(data);
      closeAuthModal();
      toast(`С возвращением, ${data.user.username}!`);
    } catch (err) {
      const d = err.data;
      if (d === "CAPTCHA_REQUIRED" || /капч/i.test(String(d))) {
        $("#loginError").textContent = "Введите ответ на проверку выше.";
        loadCaptcha();
      } else {
        $("#loginError").textContent = String(d);
      }
      // после неудачи обновляем капчу
      if (CAPTCHA) loadCaptcha();
    }
  });

  // --- Регистрация ---
  $("#registerForm").addEventListener("submit", async e => {
    e.preventDefault();
    $("#regError").textContent = "";
    try {
      const data = await api("/api/auth/register", {
        method: "POST",
        body: {
          email: $("#regEmail").value.trim(),
          username: $("#regUsername").value.trim(),
          password: $("#regPassword").value,
        },
      });
      onLoggedIn(data);
      closeAuthModal();
      toast("Аккаунт создан! Добро пожаловать 🎉");
    } catch (err) {
      $("#regError").textContent = String(err.data ?? err.message);
    }
  });
}

function onLoggedIn(data) {
  TOKEN = data.access_token;
  ME = data.user;
  localStorage.setItem("fa_token", TOKEN);
  renderAuthArea();
  refreshQuota();
  loadHistory();
  loadProgress();
  loadMissions();
}

async function logout() {
  TOKEN = null; ME = null;
  localStorage.removeItem("fa_token");
  renderAuthArea();
  $("#quotaText").textContent = "Войдите, чтобы увидеть остаток бесплатных анализов";
  $("#historyList").innerHTML = "";
  $("#historyTitle").style.display = "none";
  toast("Вы вышли из аккаунта");
}

async function tryRestoreSession() {
  if (!TOKEN) return;
  try {
    ME = await api("/api/auth/me");
    renderAuthArea();
    refreshQuota();
    loadHistory();
  } catch (_) {
    TOKEN = null; localStorage.removeItem("fa_token");
  }
}

// ==================== Профиль игрока ====================

const STAT_CARDS = [
  ["win_rate", "Win Rate", v => `${(v * 100).toFixed(1)}%`, v => v >= 0.5],
  ["kd", "K/D", v => v.toFixed(2), v => v >= 1.0],
  ["kpr", "KPR", v => v.toFixed(2), v => v >= 1.0],
  ["dpr", "DPR", v => v.toFixed(2), v => v <= 1.0],
  ["hs_pct", "Headshot %", v => `${v.toFixed(1)}%`, v => v >= 40],
  ["adr", "ADR", v => v.toFixed(1), v => v >= 80],
  ["matches", "Матчей", v => Math.round(v).toLocaleString("ru"), null],
  ["mvps", "MVP", v => Math.round(v).toLocaleString("ru"), null],
  ["first_kills_pct", "First Kill", v => `${(v * 100).toFixed(1)}%`, v => v >= 0.25],
  ["clutch_won", "Клатчи", v => Math.round(v).toLocaleString("ru"), null],
];

async function loadProfile(faceitId, game) {
  const res = $("#profileResult");
  res.classList.remove("hidden");
  $("#statsGrid").innerHTML = `<div class="loading-mini">Загрузка статистики…</div>`;
  $("#matchesTable").innerHTML = "";
  try {
    const [profile, stats, matches, weapons, anomaly] = await Promise.all([
      api(`/api/players/${encodeURIComponent(faceitId)}`),
      api(`/api/players/${encodeURIComponent(faceitId)}/stats?game=${game}`),
      api(`/api/players/${encodeURIComponent(faceitId)}/matches?game=${game}&limit=10`),
      api(`/api/players/${encodeURIComponent(faceitId)}/weapons?game=${game}`).catch(() => null),
      api(`/api/players/${encodeURIComponent(faceitId)}/anomaly?game=${game}`).catch(() => null),
    ]);

    // Карточка профиля
    $("#profileCard").innerHTML = `
      <div class="avatar">${esc(initials(profile.name))}</div>
      <div>
        <div class="profile-name">${esc(profile.name)}</div>
        <div class="profile-meta">
          🌍 ${esc(profile.country_code || "—")} · ID: <code>${esc(profile.id)}</code><br/>
          В сети: ${esc(fmtDate(profile.last_online))}
        </div>
      </div>
      ${profile.rank_tier ? `<div class="rank-pill">${esc(profile.rank_tier)}</div>` : ""}
      ${stats.rank_tier ? `<div class="rank-pill">${esc(stats.rank_tier)}</div>` : ""}
    `;

    // Сетка метрик
    $("#statsGrid").innerHTML = STAT_CARDS.map(([key, label, fmt, good]) => {
      const v = stats[key];
      if (v === undefined || v === null) return "";
      const cls = good ? (good(v) ? "good" : "bad") : "";
      return `<div class="stat-card"><div class="stat-label">${label}</div>
              <div class="stat-value ${cls}">${fmt(v)}</div></div>`;
    }).join("");

    // Таблица матчей
    const rows = matches.items.map(m => `
      <tr>
        <td class="${m.result === "won" ? "res-won" : "res-lost"}">${m.result === "won" ? "WIN" : "LOSS"}</td>
        <td>${esc(m.score || "—")}</td>
        <td>${esc(m.map || "—")}</td>
        <td>${m.kills ?? "—"}/${m.deaths ?? "—"}/${m.assists ?? "—"}</td>
        <td>${m.hs != null ? (m.hs > 1 ? m.hs.toFixed(0) + "%" : (m.hs * 100).toFixed(0) + "%") : "—"}</td>
        <td>${esc(m.mode || "—")}</td>
        <td>${esc(fmtDate(m.date))}</td>
      </tr>`).join("");
    $("#matchesTable").innerHTML = `
      <thead><tr><th>Результат</th><th>Счёт</th><th>Карта</th><th>K/D/A</th><th>HS%</th><th>Режим</th><th>Дата</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="7">Нет данных о матчах</td></tr>`}</tbody>`;

    // Аномалии
    const aStrip = $("#anomalyStrip");
    if (anomaly && anomaly.flags_count > 0) {
      const cls = anomaly.status === "suspicious" ? "anomaly-suspicious" : "anomaly-watch";
      aStrip.className = `anomaly-strip ${cls}`;
      aStrip.innerHTML = `<span class="anomaly-badge">🚩 ${anomaly.status === "suspicious" ? "Подозрительная статистика" : "Стоит присмотреться"} (${anomaly.flags_count})</span>
        <ul class="anomaly-list">${anomaly.flags.map(f => `<li>${esc(f.label)}</li>`).join("")}</ul>`;
    } else {
      aStrip.className = "anomaly-strip hidden";
    }

    // Оружие
    if (weapons && weapons.weapons) {
      $("#weaponsGrid").innerHTML = weapons.weapons.map(w => `
        <div class="weapon-card">
          <div class="weapon-name">${esc(w.name)}${w.name === weapons.main_weapon ? ' <span class="main-tag">основное</span>' : ""}</div>
          <div class="weapon-stats">
            <span>K/D <b>${w.kd.toFixed(2)}</b></span>
            <span>HS% <b>${w.hs_pct}%</b></span>
            <span>Киллы <b>${w.kills.toLocaleString("ru")}</b></span>
          </div>
          <div class="weapon-bar"><div style="width:${Math.round(w.share*100)}%"></div></div>
        </div>`).join("");
    } else {
      $("#weaponsGrid").innerHTML = `<p class="loading-mini">Нет данных по оружию</p>`;
    }

  } catch (err) {
    $("#statsGrid").innerHTML = `<div class="form-note error">Ошибка загрузки: ${esc(err.message)}</div>`;
  }
}

function initProfile() {
  $("#profileForm").addEventListener("submit", e => {
    e.preventDefault();
    const id = $("#playerIdInput").value.trim();
    const game = $("#gameSelect").value;
    if (!id) return;
    loadProfile(id, game);
    $("#profile").scrollIntoView({ behavior: "smooth" });
  });
}

// ==================== Демо-анализ ====================

async function refreshQuota() {
  if (!TOKEN) return;
  try {
    QUOTA = await api("/api/demos/quota");
    const left = QUOTA.free_remaining;
    $("#demoPrice").textContent = `${QUOTA.price.toFixed(0)} ₽`;
    $("#quotaText").innerHTML = QUOTA.is_pro
      ? "👑 Вы на подписке PRO — анализы демо <b>безлимитные</b>"
      : `Бесплатных анализов осталось: <b>${left}</b> из ${QUOTA.free_total}. Далее — ${QUOTA.price.toFixed(0)} ₽ за разбор.`;
    $("#paymentBox").classList.toggle("hidden", left > 0);
  } catch (_) {}
}

async function loadHistory() {
  if (!TOKEN) return;
  try {
    const items = await api("/api/demos/history");
    if (!items.length) return;
    $("#historyTitle").style.display = "block";
    $("#historyList").innerHTML = items.map(d => `
      <div class="history-item">
        <span class="map-tag">${esc(d.map || "—")}</span>
        <span>${esc(d.summary || d.status)}</span>
        ${d.rating ? `<span class="badge">${d.rating.letter} · ${d.rating.score}</span>` : ""}
        ${d.was_paid ? `<span class="badge">💳 платный</span>` : `<span class="badge">🆓 бесплатно</span>`}
        <span class="date">${esc(fmtDate(d.uploaded_at))}</span>
      </div>`).join("");
  } catch (_) {}
}

function renderDemoResult(result) {
  const r = result.result || {};
  const rating = r.rating || {};
  const ov = r.overview || {};
  const blocks = [
    ["🎯 Аим", r.aim_analysis],
    ["📍 Позиционирование", r.positioning],
    ["💣 Утилита", r.utility],
    ["💰 Экономика", r.economy],
    ["🔥 Клатчи", r.clutches],
  ];

  const blockHtml = blocks.map(([title, b]) => {
    if (!b) return "";
    const entries = Object.entries(b)
      .filter(([k, v]) => k !== "comment" && typeof v !== "object")
      .map(([k, v]) => `<li><b>${esc(k.replaceAll("_", " "))}:</b> ${esc(v ?? "—")}</li>`).join("");
    return `<div class="analysis-block">
      <h4>${title} <span class="score">${b.score != null ? b.score + "/100" : ""}</span></h4>
      <ul>${entries}</ul>
      ${b.comment ? `<p class="comment">${esc(b.comment)}</p>` : ""}
    </div>`;
  }).join("");

  $("#demoResult").innerHTML = `
    <div class="demo-result">
      <div class="rating-hero">
        <div class="rating-letter">${esc(rating.letter || "?")}</div>
        <div>
          <div class="rating-score">${rating.score ?? "?"} / 100</div>
          <div class="rating-overview">
            ${esc(ov.player || "")} · ${esc(ov.map || "")} · KDA ${esc(ov.kda || "—")} · ${esc(ov.team_result || "")}
            ${r.engine ? `<br/><small style="color:var(--muted)">Движок: ${esc(r.engine)}</small>` : ""}
          </div>
        </div>
      </div>
      ${r.warning ? `<p class="form-note warn" style="color:var(--warn)">⚠️ ${esc(r.warning)}</p>` : ""}
      <div class="analysis-grid">${blockHtml}</div>
      <div class="pros-cons">
        <div class="col strengths"><h4>Сильные стороны</h4>
          <ul>${(r.strengths || []).map(s => `<li>${esc(s)}</li>`).join("")}</ul></div>
        <div class="col weaknesses"><h4>Зоны роста</h4>
          <ul>${(r.weaknesses || []).map(s => `<li>${esc(s)}</li>`).join("")}</ul></div>
      </div>
      <div class="recommendations"><h4 class="sub-title">Рекомендации</h4>
        <ol>${(r.recommendations || []).map(s => `<li>${esc(s)}</li>`).join("")}</ol></div>
      <div class="training-plan-zone" id="trainingPlanZone" data-demo-id="${result.id}">
        <button class="btn btn-primary btn-lg" id="genPlanBtn">📋 Сформировать план прокачки на неделю</button>
        <div id="trainingPlan" class="hidden"></div>
      </div>
    </div>`;
  $("#demoResult").classList.remove("hidden");
  $("#demoResult").scrollIntoView({ behavior: "smooth", block: "nearest" });
  bindTrainingPlan();
}

function bindTrainingPlan() {
  const btn = $("#genPlanBtn");
  const zone = $("#trainingPlanZone");
  if (!btn || !zone) return;
  const demoId = zone.dataset.demoId;
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.textContent = "Нейросеть составляет план…";
    try {
      const plan = await api(`/api/demos/${demoId}/training-plan`, { method: "POST" });
      const items = plan.priorities.map(p => `
        <div class="plan-item">
          <div class="plan-rank">#${p.rank}</div>
          <div class="plan-body">
            <div class="plan-title">${esc(p.title)} <span class="plan-score">${p.current_score}/100</span></div>
            <p class="plan-why">${esc(p.why)}</p>
            <ul class="plan-drills">${p.drills.map(d => `<li>${esc(d)}</li>`).join("")}</ul>
            <div class="plan-meta">
              <span>🎯 Фокус: ${esc(p.focus)}</span>
              <span>⏱ ${esc(p.volume)}</span>
              <span>✅ Цель: ${esc(p.success_metric)}</span>
            </div>
          </div>
        </div>`).join("");
      $("#trainingPlan").innerHTML = `
        <div class="plan-summary">📋 ${esc(plan.summary)}</div>
        ${items}`;
      $("#trainingPlan").classList.remove("hidden");
      btn.classList.add("hidden");
      toast("План прокачки готов 📋");
    } catch (err) {
      toast(`Не удалось построить план: ${String(err.data ?? err.message)}`, "error", 6000);
      btn.disabled = false;
      btn.textContent = "📋 Сформировать план прокачки на неделю";
    }
  });
}

function initDemos() {
  $("#demoForm").addEventListener("submit", async e => {
    e.preventDefault();
    if (!TOKEN) {
      toast("Сначала войдите в аккаунт", "warn");
      openAuthModal("login");
      return;
    }
    const file = $("#demoFile").files[0];
    const faceitId = $("#demoFaceitId").value.trim();
    if (!file) return toast("Выберите демо-файл", "warn");
    if (!faceitId) return toast("Укажите Faceit ID для контекста анализа", "warn");

    const fd = new FormData();
    fd.append("file", file);
    fd.append("faceit_id", faceitId);
    fd.append("map_name", $("#demoMap").value);
    const payToken = $("#payToken").value.trim();
    if (payToken) fd.append("pay_token", payToken);

    $("#demoSubmitBtn").disabled = true;
    $("#demoLoading").classList.remove("hidden");
    $("#demoResult").classList.add("hidden");
    try {
      const data = await api("/api/demos/analyze", { method: "POST", body: fd });
      renderDemoResult(data);
      toast(data.was_paid ? "Платный анализ завершён ✅" : "Бесплатный анализ завершён ✅");
      refreshQuota();
      loadHistory();
      $("#demoFile").value = "";
      $("#payToken").value = "";
    } catch (err) {
      const d = err.data;
      if (err.status === 402 && d && d.code === "PAYMENT_REQUIRED") {
        toast(`Нужна оплата: ${d.price} ₽. Вставьте токен оплаты.`, "warn", 6000);
        $("#paymentBox").classList.remove("hidden");
        $("#payToken").focus();
      } else {
        toast(`Ошибка анализа: ${String(d ?? err.message)}`, "error", 6000);
      }
    } finally {
      $("#demoLoading").classList.add("hidden");
      $("#demoSubmitBtn").disabled = false;
    }
  });
}

// ==================== Сравнение ====================

function initCompare() {
  $("#compareForm").addEventListener("submit", async e => {
    e.preventDefault();
    const a = $("#cmpA").value.trim();
    const b = $("#cmpB").value.trim();
    if (!a || !b) return;
    if (a.toLowerCase() === b.toLowerCase()) return toast("Нельзя сравнивать игрока с самим собой", "warn");

    const box = $("#compareResult");
    box.classList.remove("hidden");
    box.innerHTML = `<div class="loading"><div class="spinner"></div><p>Загружаем статистику обоих игроков…</p></div>`;
    try {
      const data = await api("/api/players/compare", { method: "POST", body: { player_a: a, player_b: b } });
      // Засчитываем сравнение в миссии (если авторизованы)
      if (TOKEN) api("/api/missions/events/compare", { method: "POST", body: { player_a: a, player_b: b } }).catch(() => {});
      if (data.error) return toast(data.error, "warn");

      const rows = data.rows.map(r => `
        <tr>
          <td class="metric">${esc(r.label)}</td>
          <td class="${r.winner === "a" ? "winner-a" : ""}">${esc(r.display_a)}${r.winner === "a" ? " ★" : ""}</td>
          <td class="${r.winner === "b" ? "winner-b" : ""}">${esc(r.display_b)}${r.winner === "b" ? " ★" : ""}</td>
        </tr>`).join("");

      box.innerHTML = `
        <div class="compare-heads">
          <div class="head" style="color:var(--accent)">${esc(data.player_a.name)}
            <small>${esc(data.player_a.country || "")} · ${esc(data.player_a.rank_tier || "")}</small></div>
          <div class="head" style="color:var(--accent-2)">${esc(data.player_b.name)}
            <small>${esc(data.player_b.country || "")} · ${esc(data.player_b.rank_tier || "")}</small></div>
        </div>
        <table class="compare-table">
          <thead><tr><th style="text-align:left">Метрика</th><th>${esc(data.player_a.name)}</th><th>${esc(data.player_b.name)}</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
        <div class="compare-verdict">🏆 ${esc(data.verdict)} — счёт по метрикам ${data.points.a}:${data.points.b}</div>`;
      box.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (err) {
      box.innerHTML = `<div class="form-note error">Ошибка сравнения: ${esc(err.message)}</div>`;
    }
  });

  // --- Прогноз матча ---
  $("#predictBtn").addEventListener("click", async () => {
    const a = $("#cmpA").value.trim();
    const b = $("#cmpB").value.trim();
    if (!a || !b) return toast("Укажите обоих игроков для прогноза", "warn");
    if (a.toLowerCase() === b.toLowerCase()) return toast("Нельзя прогнозировать матч с самим собой", "warn");
    const pbox = $("#predictResult");
    pbox.classList.remove("hidden");
    pbox.innerHTML = `<div class="loading"><div class="spinner"></div><p>Считаем вероятность победы…</p></div>`;
    try {
      const d = await api("/api/players/predict", { method: "POST", body: { player_a: a, player_b: b } });
      if (d.error) return toast(d.error, "warn");
      const pa = Math.round(d.prob_a * 100), pb = Math.round(d.prob_b * 100);
      const metricNames = {kpr:"KPR", adr:"ADR", kd:"K/D", hs_pct:"HS%", win_rate:"Win Rate"};
      const contribs = d.contributions.map(c => `
        <tr>
          <td class="metric">${metricNames[c.key] || c.key}</td>
          <td>${(+c.a).toFixed(2)}</td><td>${(+c.b).toFixed(2)}</td>
          <td class="${c.favors==='a'?'winner-a':c.favors==='b'?'winner-b':''}">${c.favors==='draw'?'≈':(c.favors==='a'?'→ A':'→ B')}</td>
        </tr>`).join("");
      pbox.innerHTML = `
        <div class="predict-hero">
          <div class="predict-bar">
            <div class="predict-side a" style="width:${pa}%">${pa}%</div>
            <div class="predict-side b" style="width:${pb}%">${pb}%</div>
          </div>
          <div class="predict-verdict">🔮 ${esc(d.verdict)}</div>
          <small class="predict-model">Модель: ${esc(d.model)} · решающие метрики: ${esc(d.decisive_metrics.join(", "))}</small>
        </div>
        <table class="compare-table predict-table">
          <thead><tr><th style="text-align:left">Метрика</th><th>A</th><th>B</th><th>Преимущество</th></tr></thead>
          <tbody>${contribs}</tbody>
        </table>`;
      pbox.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (err) {
      pbox.innerHTML = `<div class="form-note error">Ошибка прогноза: ${esc(err.message)}</div>`;
    }
  });
}

// ==================== Контакты ====================

async function loadContactInfo() {
  try {
    const info = await api("/api/contact/info");
    const rows = [
      ["✉️", "Email", info.email],
      ["💬", "Telegram", info.telegram],
      ["🎮", "Discord", info.discord],
      ["🕐", "Часы работы", info.working_hours],
      ["📍", "Адрес", info.address],
    ];
    $("#contactInfo").innerHTML = rows.map(([icon, label, val]) => `
      <div class="ci-row"><span class="ci-icon">${icon}</span>
        <div><div class="ci-label">${label}</div><div>${esc(val)}</div></div></div>`).join("");
  } catch (err) {
    $("#contactInfo").innerHTML = `<p class="form-note error">Не удалось загрузить контакты</p>`;
  }
}

function initContacts() {
  $("#contactForm").addEventListener("submit", async e => {
    e.preventDefault();
    const note = $("#contactNote");
    note.className = "form-note";
    try {
      const data = await api("/api/contact", {
        method: "POST",
        body: {
          name: $("#ctName").value.trim(),
          email: $("#ctEmail").value.trim(),
          subject: $("#ctSubject").value.trim() || null,
          message: $("#ctMessage").value.trim(),
        },
      });
      note.style.color = "var(--ok)";
      note.textContent = data.message;
      e.target.reset();
      toast("Сообщение отправлено!");
    } catch (err) {
      note.style.color = "var(--danger)";
      note.textContent = String(err.data ?? err.message);
    }
  });
}

// ==================== Миссии и очки ====================

async function loadMissions() {
  if (!TOKEN) {
    $("#missionsStatus").textContent = "Войдите, чтобы получать миссии";
    $("#missionsContent").classList.add("hidden");
    return;
  }
  try {
    const st = await api("/api/missions");
    $("#missionsStatus").innerHTML = `Неделя ${esc(st.week_key)} · до сброса баланса: <b>${st.days_to_reset} дн.</b>` +
      (st.has_faceit_link ? "" : ` · <span style="color:var(--warn)">привяжите Faceit ID для засчёта побед</span>`);
    $("#pointsHero").innerHTML = `
      <div class="ph-card"><div class="ph-label">Очки за месяц</div><div class="ph-value">${st.points_balance}</div></div>
      <div class="ph-card"><div class="ph-label">За эту неделю</div><div class="ph-value">${st.weekly_points}<small> / ${st.weekly_point_cap}</small></div></div>
      <div class="ph-card"><div class="ph-label">Выполнено миссий</div><div class="ph-value">${st.missions.filter(m => m.completed).length}<small> / ${st.missions.length}</small></div></div>`;

    $("#missionsGrid").innerHTML = st.missions.map(m => `
      <div class="mission-card ${m.completed ? "done" : ""}">
        <div class="mission-top">
          <span class="mission-title">${esc(m.title)}</span>
          <span class="mission-points">+${m.points}</span>
        </div>
        <p class="mission-desc">${esc(m.description)}</p>
        <div class="mission-bar"><div style="width:${Math.round(m.progress / m.target * 100)}%"></div></div>
        <div class="mission-progress">${m.progress} / ${m.target}${m.completed ? " ✅" : ""}</div>
      </div>`).join("");

    const cd = Math.ceil((st.scan_cooldown_seconds || 0) / 60);
    $("#scanWinsBtn").disabled = cd > 0 || !st.has_faceit_link;
    $("#scanHint").textContent = !st.has_faceit_link
      ? "Нужен привязанный Faceit ID (кнопка «Привязать» появится после входа в аккаунт)"
      : (cd > 0 ? `Повторное сканирование через ${cd} мин` : "");

    $("#missionsContent").classList.remove("hidden");
    loadLeaderboard();
  } catch (err) {
    $("#missionsStatus").textContent = "Ошибка загрузки миссий: " + err.message;
  }
}

async function loadLeaderboard(month) {
  try {
    const lb = await api(`/api/missions/leaderboard${month ? `?month=${month}` : ""}`);
    $("#lbNote").textContent = lb.archived ? "Архив месяца" : "Живой рейтинг текущего месяца";
    const rows = lb.entries.slice(0, 20).map(e => `
      <tr>
        <td>${e.rank <= 3 ? ["🥇","🥈","🥉"][e.rank-1] : e.rank}</td>
        <td>${esc(e.username)}</td>
        <td><code>${esc(e.faceit_id || "—")}</code></td>
        <td class="res-won">${e.points}</td>
        <td>${e.reward_status === "pending" ? "⏳ награда" : e.reward_status === "activated" ? "✅ premium" : ""}</td>
      </tr>`).join("");
    $("#leaderboardTable").innerHTML = `
      <thead><tr><th>#</th><th>Игрок</th><th>Faceit ID</th><th>Очки</th><th>Награда</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="5">Пока нет участников — станьте первым!</td></tr>`}</tbody>`;

    // Награды (только для архивных месяцев с закрытым итогом)
    const rew = await api(`/api/missions/rewards${month ? `?month=${month}` : ""}`);
    if (rew.items.length) {
      $("#rewardsBox").classList.remove("hidden");
      $("#rewardsBox").innerHTML = `
        <h4 class="sub-title">🎁 Награды месяца (${esc(rew.month)}) — ${esc(rew.reward)}</h4>
        <ul class="rewards-list">${rew.items.map(i => `
          <li><b>#${i.rank} ${esc(i.username)}</b> · faceit_id: <code>${esc(i.faceit_id || "не привязан")}</code>
            · <span class="rw-status ${i.status}">${i.status === "activated" ? "активировано" : "в очереди активации"}</span></li>`).join("")}
        </ul>
        <p class="form-note">Активация выполняется автоматически по Faceit ID оператором; сервис фиксирует статус.</p>`;
    } else {
      $("#rewardsBox").classList.add("hidden");
    }
  } catch (_) {}
}

function initMissions() {
  $("#scanWinsBtn").addEventListener("click", async () => {
    const btn = $("#scanWinsBtn");
    btn.disabled = true;
    btn.textContent = "Сканируем матчи…";
    try {
      const res = await api("/api/missions/scan-wins", { method: "POST" });
      toast(`Сканировано ${res.scanned} матчей: побед ${res.wins_found}, новых ${res.new}, очков +${res.points}`, "ok", 6000);
      await Promise.all([loadMissions(), loadProgress()]);
    } catch (err) {
      const d = err.data ?? {};
      toast(d.cooldown_seconds ? `Подождите ${Math.ceil(d.cooldown_seconds/60)} мин до повторного скана`
                               : String(d.error ?? err.message), "warn", 6000);
    } finally {
      btn.textContent = "⚔️ Засчитать победы из истории матчей";
      loadMissions().then(() => {});
    }
  });

  // Выбор месяца для лидерборда
  const sel = $("#lbMonth");
  const now = new Date();
  let opts = "";
  for (let i = 0; i < 6; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const mk = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}`;
    opts += `<option value="${mk}" ${i===0?"selected":""}>${mk}</option>`;
  }
  sel.innerHTML = opts;
  sel.addEventListener("change", () => loadLeaderboard(sel.value));
}

// ==================== Трекер прогресса ====================

const CHART_INSTANCES = {};

function makeChart(domId, title) {
  const el = document.getElementById(domId);
  if (!el || typeof echarts === "undefined") return null;
  let inst = CHART_INSTANCES[domId];
  if (!inst) {
    inst = echarts.init(el, null, { renderer: "canvas" });
    CHART_INSTANCES[domId] = inst;
  }
  return inst;
}

function renderTrendChart(domId, labels, values, color, higherBetter) {
  const inst = makeChart(domId);
  if (!inst) return;
  // Подсвечиваем тренд: рост в «хорошую» сторону — зелёный, в плохую — красный
  const goodColor = "#3ddc84", badColor = "#ff5c6c";
  inst.setOption({
    backgroundColor: "transparent",
    grid: { left: 40, right: 16, top: 24, bottom: 28 },
    tooltip: { trigger: "axis", backgroundColor: "#1c2331", borderColor: "#262f40", textStyle: { color: "#e8edf5" } },
    xAxis: {
      type: "category", data: labels,
      axisLine: { lineStyle: { color: "#262f40" } },
      axisLabel: { color: "#8b97ab", fontSize: 10 },
    },
    yAxis: {
      type: "value", scale: true,
      splitLine: { lineStyle: { color: "#262f40", type: "dashed" } },
      axisLabel: { color: "#8b97ab" },
    },
    series: [{
      type: "line", data: values, smooth: true, symbol: "circle", symbolSize: 7,
      lineStyle: { width: 3, color: color || "#00e5a0" },
      itemStyle: { color: (p) => {
        if (values.length < 2) return color || "#00e5a0";
        const prev = values[p.dataIndex - 1], cur = values[p.dataIndex];
        if (prev == null || cur == null) return color || "#00e5a0";
        const up = cur >= prev;
        const isGood = higherBetter ? up : !up;
        return isGood ? goodColor : badColor;
      }},
      areaStyle: { opacity: 0.12, color: color || "#00e5a0" },
    }],
  });
}

async function loadProgress() {
  if (!TOKEN) {
    $("#progressStatus").textContent = "Войдите, чтобы отслеживать прогресс";
    return;
  }
  try {
    const status = await api("/api/progress/status");
    $("#progressStatus").innerHTML = status.linked_faceit_id
      ? `Привязан профиль: <code>${esc(status.linked_faceit_id)}</code> · Снимков: <b>${status.snapshots_count}</b>`
      : `Снимков: <b>${status.snapshots_count}</b>. Привяжите faceit_id или введите его вручную.`;
    if (status.linked_faceit_id && !$("#snapFaceitId").value) {
      $("#snapFaceitId").value = status.linked_faceit_id;
    }
    if (status.snapshots_count > 0) {
      await renderProgressCharts();
    } else {
      $("#progressResult").classList.add("hidden");
    }
  } catch (_) {}
}

async function renderProgressCharts() {
  try {
    const t = await api("/api/progress/trends");
    if (!t.count) return;
    $("#progressResult").classList.remove("hidden");

    const meta = Object.fromEntries(t.metrics.map(m => [m.key, m]));
    for (const key of ["win_rate", "kd", "hs_pct", "adr"]) {
      const m = meta[key];
      renderTrendChart(`chart_${key}`, t.labels, t.series[key], "#00e5a0", m.higher_is_better);
    }
    // Рейтинги демо
    renderTrendChart("chart_demo_ratings", t.demo_ratings.labels, t.demo_ratings.values, "#2f6bff", true);

    // Таблица снимков
    const hist = await api("/api/progress/history");
    const rows = hist.slice().reverse().map(s => {
      const d = s.delta || {};
      const deltaCell = (v, invert = false) => {
        if (v == null) return "<td>—</td>";
        const good = invert ? v <= 0 : v >= 0;
        const sign = v > 0 ? "+" : "";
        return `<td class="${good ? "res-won" : "res-lost"}">${sign}${(+v).toFixed(2)}</td>`;
      };
      return `<tr>
        <td>${esc(fmtDate(s.taken_at))}</td>
        <td>${((s.win_rate ?? 0) * 100).toFixed(1)}%</td>
        <td>${s.kd?.toFixed(2) ?? "—"}</td>
        <td>${s.hs_pct?.toFixed(1) ?? "—"}</td>
        <td>${s.adr?.toFixed(1) ?? "—"}</td>
        <td>${s.matches ?? "—"}</td>
        ${deltaCell(d.win_rate != null ? d.win_rate * 100 : null)}
        ${deltaCell(d.kd)}
        ${deltaCell(d.hs_pct)}
        ${deltaCell(d.adr)}
        <td>${s.source === "demo" ? "🧠 демо" : "📸 ручной"}</td>
      </tr>`;
    }).join("");
    $("#snapshotsTable").innerHTML = `
      <thead><tr><th>Дата</th><th>WR%</th><th>K/D</th><th>HS%</th><th>ADR</th><th>Матчи</th>
        <th>ΔWR</th><th>ΔK/D</th><th>ΔHS</th><th>ΔADR</th><th>Источник</th></tr></thead>
      <tbody>${rows}</tbody>`;
  } catch (err) {
    toast(`Ошибка загрузки прогресса: ${err.message}`, "error");
  }
}

function initProgress() {
  $("#snapshotForm").addEventListener("submit", async e => {
    e.preventDefault();
    if (!TOKEN) {
      toast("Сначала войдите в аккаунт", "warn");
      openAuthModal("login");
      return;
    }
    const fid = $("#snapFaceitId").value.trim();
    if (!fid) return toast("Укажите faceit_id", "warn");
    const btn = e.target.querySelector("button");
    btn.disabled = true;
    try {
      await api("/api/progress/snapshot", { method: "POST", body: { faceit_id: fid } });
      toast("Снимок статистики сохранён 📸");
      await Promise.all([loadProgress(), renderProgressCharts()]);
    } catch (err) {
      toast(String(err.data ?? err.message), "error");
    } finally {
      btn.disabled = false;
    }
  });
}

// ==================== Статус API / инициализация ====================

async function checkApiStatus() {
  try {
    const st = await api("/api/players/status");
    if (st.demo_mode) {
      toast("ℹ️ Faceit API key не настроен — показаны демонстрационные данные", "warn", 7000);
    }
  } catch (_) {}
}

document.addEventListener("DOMContentLoaded", () => {
  initNav();
  initAuthModal();
  initProfile();
  initMissions();
  initProgress();
  initDemos();
  initCompare();
  initContacts();
  loadContactInfo();
  checkApiStatus();
  tryRestoreSession().then(() => { loadProgress(); loadMissions(); });
  window.addEventListener("resize", () => {
    Object.values(CHART_INSTANCES).forEach(c => c.resize());
  });
});
