const form = document.getElementById("predictForm");
const urlInput = document.getElementById("urlInput");
const ensembleMethodInput = document.getElementById("ensembleMethodInput");
const thresholdInput = document.getElementById("thresholdInput");
const submitButton = document.getElementById("submitButton");
const exampleButton = document.getElementById("exampleButton");
const formMessage = document.getElementById("formMessage");
const resultPanel = document.getElementById("resultPanel");
const loadingOverlay = document.getElementById("loadingOverlay");
const loadingMessage = document.getElementById("loadingMessage");
const themeToggle = document.getElementById("themeToggle");
const themeToggleLabel = document.getElementById("themeToggleLabel");
const authPanel = document.getElementById("authPanel");
const authStatus = document.getElementById("authStatus");
const authMessage = document.getElementById("authMessage");
const logoutButton = document.getElementById("logoutButton");
const loginForm = document.getElementById("loginForm");
const registerForm = document.getElementById("registerForm");
const showLoginButton = document.getElementById("showLoginButton");
const showRegisterButton = document.getElementById("showRegisterButton");
const loginButton = document.getElementById("loginButton");
const registerButton = document.getElementById("registerButton");
const loginIdentifier = document.getElementById("loginIdentifier");
const loginPassword = document.getElementById("loginPassword");
const registerEmail = document.getElementById("registerEmail");
const registerUsername = document.getElementById("registerUsername");
const registerPassword = document.getElementById("registerPassword");
const historyPanel = document.getElementById("historyPanel");
const historyList = document.getElementById("historyList");
const refreshHistoryButton = document.getElementById("refreshHistoryButton");
const clearHistoryButton = document.getElementById("clearHistoryButton");

const exampleUrl = "https://www.autovit.ro/autoturisme/anunt/fiat-fiorino-ID7HMUoe.html";
const similarLimit = 4;
const loadingMessages = [
  "Preluam anuntul si extragem datele principale...",
  "Standardizam specificatiile masinii...",
  "Estimam pretul corect pe baza modelului...",
  "Cautam masini similare in baza de date...",
];

let loadingInterval = null;
let currentUser = null;

function formatCurrency(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "N/A";
  }
  return new Intl.NumberFormat("ro-RO", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "N/A";
  }
  return new Intl.NumberFormat("ro-RO").format(value);
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "N/A";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function formatDateTime(value) {
  if (!value) {
    return "N/A";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("ro-RO", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

function humanizeVerdict(verdict) {
  if (verdict === "too_low_suspicious") {
    return "Pret suspect de mic";
  }
  if (verdict === "too_high") {
    return "Pret prea mare";
  }
  if (verdict === "fair") {
    return "Pret corect";
  }
  return "Necunoscut";
}

function inferSiteFromUrl(url) {
  let host = "";
  try {
    host = new URL(url).hostname.toLowerCase();
  } catch (error) {
    return null;
  }
  if (host.endsWith("autovit.ro")) {
    return "autovit";
  }
  if (host.endsWith("mobile.de")) {
    return "mobilede";
  }
  return null;
}

function humanizeReason(reason) {
  const map = {
    "same make": "aceeasi marca",
    "same model": "acelasi model",
    "same fuel": "acelasi combustibil",
    "same gearbox": "aceeasi cutie",
    "year within 1": "an apropiat",
    "mileage within 25k km": "kilometri apropiati",
    "power within 20 hp": "putere apropiata",
    "engine within 250 cm3": "motorizare apropiata",
  };
  return map[reason] || reason;
}

function humanizeModelName(name) {
  const mapping = {
    svr_rbf: "SVR",
    ridge: "Ridge",
    knn_distance: "KNN",
    random_forest: "Random Forest",
    extra_trees: "Extra Trees",
    gradient_boosting: "Gradient Boosting",
    voting_ensemble: "Ensemble",
    weighted_average: "Estimare finala ponderata",
  };
  return mapping[name] || name;
}

function humanizeWeightingMethod(method) {
  if (method === "inverse_mae") {
    return "Doar MAE";
  }
  if (method === "inverse_mae_with_agreement") {
    return "MAE + acord intre modele";
  }
  return method || "N/A";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#39;");
}

function setMessage(message, tone = "") {
  formMessage.textContent = message;
  formMessage.className = `form-message${tone ? ` is-${tone}` : ""}`;
}

function setAuthMessage(message, tone = "") {
  authMessage.textContent = message;
  authMessage.className = `form-message${tone ? ` is-${tone}` : ""}`;
}

function setAuthLoading(isLoading) {
  loginButton.disabled = isLoading;
  registerButton.disabled = isLoading;
  logoutButton.disabled = isLoading;
  clearHistoryButton.disabled = isLoading;
  refreshHistoryButton.disabled = isLoading;
}

function setLoading(isLoading) {
  submitButton.disabled = isLoading;
  exampleButton.disabled = isLoading;
  submitButton.querySelector(".button-text").textContent = isLoading ? "Se analizeaza..." : "Analizeaza anuntul";

  if (isLoading) {
    let index = 0;
    loadingMessage.textContent = loadingMessages[0];
    loadingOverlay.classList.add("is-visible");
    loadingOverlay.setAttribute("aria-hidden", "false");
    loadingInterval = window.setInterval(() => {
      index = (index + 1) % loadingMessages.length;
      loadingMessage.textContent = loadingMessages[index];
    }, 1300);
  } else {
    window.clearInterval(loadingInterval);
    loadingInterval = null;
    loadingOverlay.classList.remove("is-visible");
    loadingOverlay.setAttribute("aria-hidden", "true");
  }
}

function applyTheme(theme) {
  document.body.dataset.theme = theme;
  localStorage.setItem("carvaluator-theme", theme);
  themeToggleLabel.textContent = theme === "dark" ? "Mod luminos" : "Mod intunecat";
}

function initializeTheme() {
  const stored = localStorage.getItem("carvaluator-theme");
  if (stored === "light" || stored === "dark") {
    applyTheme(stored);
    return;
  }
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(prefersDark ? "dark" : "light");
}

function renderAuthState(user) {
  currentUser = user;
  if (user) {
    authStatus.textContent = `Logat ca ${user.username}`;
    logoutButton.classList.remove("is-hidden");
    authPanel.classList.add("is-hidden");
    historyPanel.classList.remove("is-hidden");
    submitButton.disabled = false;
    setMessage("Poti analiza anunturi Autovit sau mobile.de.", "success");
    loadHistory();
    return;
  }

  authStatus.textContent = "Neautentificat";
  logoutButton.classList.add("is-hidden");
  authPanel.classList.remove("is-hidden");
  historyPanel.classList.add("is-hidden");
  historyList.innerHTML = '<p class="history-empty">Autentifica-te pentru a vedea istoricul analizelor.</p>';
  submitButton.disabled = false;
}

function showAuthMode(mode) {
  const isLogin = mode === "login";
  loginForm.classList.toggle("is-hidden", !isLogin);
  registerForm.classList.toggle("is-hidden", isLogin);
  showLoginButton.classList.toggle("is-active", isLogin);
  showRegisterButton.classList.toggle("is-active", !isLogin);
  setAuthMessage("");
}

async function readErrorMessage(response, fallback) {
  try {
    const data = await response.json();
    return data.detail || fallback;
  } catch (error) {
    return fallback;
  }
}

async function checkSession() {
  try {
    const response = await fetch("/auth/me", { credentials: "same-origin" });
    if (!response.ok) {
      renderAuthState(null);
      setMessage("Autentifica-te sau creeaza un cont pentru a analiza anunturi.");
      return;
    }
    const data = await response.json();
    renderAuthState(data.user);
  } catch (error) {
    renderAuthState(null);
    setMessage("Nu am putut verifica sesiunea. Serverul trebuie pornit pentru login.", "error");
  }
}

async function submitLogin(event) {
  event.preventDefault();
  setAuthLoading(true);
  setAuthMessage("Verificam datele...");

  try {
    const response = await fetch("/auth/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        identifier: loginIdentifier.value.trim(),
        password: loginPassword.value,
      }),
    });
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, "Login esuat."));
    }
    const data = await response.json();
    loginPassword.value = "";
    renderAuthState(data.user);
    setAuthMessage("");
  } catch (error) {
    setAuthMessage(error.message || "Login esuat.", "error");
  } finally {
    setAuthLoading(false);
  }
}

async function submitRegister(event) {
  event.preventDefault();
  setAuthLoading(true);
  setAuthMessage("Cream contul...");

  try {
    const response = await fetch("/auth/register", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: registerEmail.value.trim(),
        username: registerUsername.value.trim(),
        password: registerPassword.value,
      }),
    });
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, "Contul nu a putut fi creat."));
    }
    const data = await response.json();
    registerPassword.value = "";
    renderAuthState(data.user);
    setAuthMessage("");
  } catch (error) {
    setAuthMessage(error.message || "Contul nu a putut fi creat.", "error");
  } finally {
    setAuthLoading(false);
  }
}

async function logout() {
  setAuthLoading(true);
  try {
    await fetch("/auth/logout", {
      method: "POST",
      credentials: "same-origin",
    });
  } finally {
    setAuthLoading(false);
    renderAuthState(null);
    showAuthMode("login");
    setMessage("Te-ai delogat. Autentifica-te pentru a analiza un anunt.");
  }
}

async function loadHistory() {
  if (!currentUser) {
    return;
  }

  historyList.innerHTML = '<p class="history-empty">Incarcam istoricul...</p>';
  try {
    const response = await fetch("/history?limit=20", { credentials: "same-origin" });
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, "Nu am putut incarca istoricul."));
    }
    const data = await response.json();
    renderHistory(data.items || []);
  } catch (error) {
    historyList.innerHTML = `<p class="history-empty is-error">${escapeHtml(error.message || "Nu am putut incarca istoricul.")}</p>`;
  }
}

async function deleteHistoryItem(historyId) {
  if (!currentUser || !historyId) {
    return;
  }
  if (!window.confirm("Stergi aceasta analiza din istoric?")) {
    return;
  }

  setAuthLoading(true);
  try {
    const response = await fetch(`/history/${encodeURIComponent(historyId)}`, {
      method: "DELETE",
      credentials: "same-origin",
    });
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, "Nu am putut sterge analiza."));
    }
    await loadHistory();
    setMessage("Analiza a fost stearsa din istoric.", "success");
  } catch (error) {
    setMessage(error.message || "Nu am putut sterge analiza.", "error");
  } finally {
    setAuthLoading(false);
  }
}

async function clearHistory() {
  if (!currentUser) {
    return;
  }
  if (!window.confirm("Stergi toate analizele din istoricul acestui cont?")) {
    return;
  }

  setAuthLoading(true);
  try {
    const response = await fetch("/history", {
      method: "DELETE",
      credentials: "same-origin",
    });
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, "Nu am putut sterge istoricul."));
    }
    await loadHistory();
    setMessage("Istoricul a fost sters.", "success");
  } catch (error) {
    setMessage(error.message || "Nu am putut sterge istoricul.", "error");
  } finally {
    setAuthLoading(false);
  }
}

function renderHistory(items) {
  if (!items.length) {
    historyList.innerHTML = '<p class="history-empty">Nu ai analizat inca niciun anunt.</p>';
    return;
  }

  historyList.innerHTML = items.map((item) => `
    <article class="history-card">
      ${item.image_url ? `<img src="${escapeHtml(item.image_url)}" alt="${escapeHtml(item.title || "Anunt analizat")}">` : '<div class="history-image-placeholder">Fara imagine</div>'}
      <div class="history-content">
        <div class="history-meta">
          <span>${escapeHtml(item.source || "unknown")}</span>
          <span>${formatDateTime(item.created_at)}</span>
        </div>
        <h3>${escapeHtml(item.title || "Anunt fara titlu")}</h3>
        <div class="history-values">
          <span>Anunt: <strong>${formatCurrency(item.actual_price_eur)}</strong></span>
          <span>Estimat: <strong>${formatCurrency(item.predicted_price_eur)}</strong></span>
          <span class="verdict-pill ${escapeHtml(item.verdict || "unknown")}">${escapeHtml(humanizeVerdict(item.verdict))}</span>
        </div>
        <a href="${escapeHtml(item.url || "#")}" target="_blank" rel="noreferrer">Deschide anuntul</a>
        <button class="history-delete-button" type="button" data-history-id="${escapeHtml(item.id)}">Sterge analiza</button>
      </div>
    </article>
  `).join("");

  historyList.querySelectorAll("[data-history-id]").forEach((button) => {
    button.addEventListener("click", () => deleteHistoryItem(button.dataset.historyId));
  });
}

function buildSpecPills(normalized) {
  const values = [
    normalized.make && normalized.model ? `${normalized.make} ${normalized.model}` : null,
    normalized.year ? `${normalized.year}` : null,
    normalized.mileage_km ? `${formatNumber(normalized.mileage_km)} km` : null,
    normalized.fuel_type || null,
    normalized.transmission || null,
    normalized.power_hp ? `${formatNumber(normalized.power_hp)} cp` : null,
    normalized.engine_capacity_cm3 ? `${formatNumber(normalized.engine_capacity_cm3)} cmc` : null,
  ].filter(Boolean);

  return values.map((value) => `<span class="spec-pill">${escapeHtml(value)}</span>`).join("");
}

function buildImageMarkup(data) {
  if (data.image_url) {
    return `
      <div class="image-card">
        <img class="result-image" src="${escapeHtml(data.image_url)}" alt="${escapeHtml(data.title || "Masina analizata")}">
        <div class="image-caption">
          <a href="${escapeHtml(data.url || "#")}" target="_blank" rel="noreferrer">Deschide anuntul original</a>
        </div>
      </div>
    `;
  }

  return `
    <div class="image-card">
      <div class="image-placeholder">Fotografia principala nu a fost disponibila in anunt.</div>
      <div class="image-caption">
        <a href="${escapeHtml(data.url || "#")}" target="_blank" rel="noreferrer">Deschide anuntul original</a>
      </div>
    </div>
  `;
}

function buildSimilarMarkup(similarListings) {
  if (!similarListings.length) {
    return `
      <section class="similar-section">
        <p class="section-kicker">Masini similare</p>
        <h3>Nu am gasit suficiente anunturi comparabile.</h3>
      </section>
    `;
  }

  const cards = similarListings.map((listing) => {
    const reasons = (listing.match_reasons || [])
      .map((reason) => `<span class="match-tag">${escapeHtml(humanizeReason(reason))}</span>`)
      .join("");

    return `
      <article class="similar-card">
        <span>Masina similara</span>
        <h4>${escapeHtml(listing.title || "Anunt fara titlu")}</h4>
        <p>${formatCurrency(listing.price_eur)} | ${formatNumber(listing.year)} | ${formatNumber(listing.mileage_km)} km</p>
        <p>${escapeHtml(listing.fuel_type || "N/A")} / ${escapeHtml(listing.transmission || "N/A")} | ${formatNumber(listing.power_hp)} cp</p>
        <div class="match-tags">${reasons}</div>
        <a class="similar-link" href="${escapeHtml(listing.url || "#")}" target="_blank" rel="noreferrer">Vezi anuntul</a>
      </article>
    `;
  }).join("");

  return `
    <section class="similar-section">
      <p class="section-kicker">Masini similare</p>
      <h3>Anunturi apropiate din baza de date</h3>
      <div class="similar-grid">${cards}</div>
    </section>
  `;
}

function buildModelEstimatesMarkup(modelEstimates) {
  if (!modelEstimates.length) {
    return "";
  }

  const cards = modelEstimates.map((item) => `
    <article class="model-card similar-card">
      <span>Model</span>
      <h4>${escapeHtml(humanizeModelName(item.model))}</h4>
      <strong>${formatCurrency(item.predicted_price_eur)}</strong>
      <p>RMSE test: ${formatCurrency(item.rmse)}</p>
      <p>R2: ${item.r2 !== null && item.r2 !== undefined ? Number(item.r2).toFixed(3) : "N/A"}</p>
      ${item.ensemble_weight ? `<p>Pondere: ${(Number(item.ensemble_weight) * 100).toFixed(1)}%</p>` : ""}
      ${item.agreement_weight ? `<p>Acord intre modele: ${(Number(item.agreement_weight) * 100).toFixed(0)}%</p>` : ""}
      ${item.weighting ? `<p>Metoda: ${escapeHtml(humanizeWeightingMethod(item.weighting))}</p>` : ""}
      ${item.confidence ? `<p>Incredere: ${escapeHtml(item.confidence)} (${formatNumber(item.sample_size)} anunturi)</p>` : ""}
      ${item.scope ? `<p>Grup comparatie: ${escapeHtml(item.scope)}</p>` : ""}
      ${item.is_best_model ? `<div class="model-best-badge">${item.model === "weighted_average" ? "Estimarea finala" : "Cel mai bun model"}</div>` : ""}
    </article>
  `).join("");

  return `
    <section class="models-section">
      <p class="section-kicker">Comparatie modele</p>
      <h3>Estimarea fiecarui model pentru acest anunt</h3>
      <div class="models-grid">${cards}</div>
    </section>
  `;
}

function buildPerformancePlotsMarkup() {
  const cacheKey = Date.now();
  return `
    <section class="plots-section">
      <p class="section-kicker">Performanta modelelor</p>
      <h3>Grafice generate in Python dupa antrenare</h3>
      <div class="plots-grid">
        <article class="plot-card">
          <h4>Comparatie RMSE intre modele</h4>
          <img src="/model-artifacts/model_performance.png?v=${cacheKey}" alt="Grafic comparativ RMSE pentru modele">
        </article>
        <article class="plot-card">
          <h4>Pret real vs pret estimat</h4>
          <img src="/model-artifacts/actual_vs_predicted.png?v=${cacheKey}" alt="Grafic pret real versus pret estimat">
        </article>
      </div>
    </section>
  `;
}

function renderResult(data) {
  const normalized = data.normalized_listing || {};
  const verdictClass = data.verdict || "unknown";
  const similarListings = data.similar_listings || [];
  const modelEstimates = data.model_estimates || [];

  resultPanel.classList.remove("is-empty");
  resultPanel.innerHTML = `
    <div class="result-card">
      <div class="result-top">
        <div class="result-main">
          <p class="section-kicker">Rezultat</p>
          <h2>${escapeHtml(data.title || "Anunt fara titlu")}</h2>
          <p class="result-subcopy">
            Pret afisat: <strong>${formatCurrency(data.actual_price_eur)}</strong>.
            Pret estimat: <strong>${formatCurrency(data.predicted_price_eur)}</strong>.
          </p>

          <div class="verdict-row">
            <span class="verdict-pill ${escapeHtml(verdictClass)}">${escapeHtml(humanizeVerdict(verdictClass))}</span>
            <span class="spec-pill">Diferenta: ${formatPercent(data.delta_percent)}</span>
          </div>

          <div class="price-grid">
            <article class="price-card">
              <span>Pret anunt</span>
              <strong>${formatCurrency(data.actual_price_eur)}</strong>
            </article>
            <article class="price-card">
              <span>Pret estimat</span>
              <strong>${formatCurrency(data.predicted_price_eur)}</strong>
            </article>
            <article class="price-card">
              <span>Verdict</span>
              <strong>${escapeHtml(humanizeVerdict(verdictClass))}</strong>
            </article>
          </div>

          <div class="spec-list">${buildSpecPills(normalized)}</div>
        </div>

        ${buildImageMarkup(data)}
      </div>

      ${buildModelEstimatesMarkup(modelEstimates)}

      ${buildPerformancePlotsMarkup()}

      ${buildSimilarMarkup(similarListings)}

      <p class="result-note">
        Verdictul este calculat folosind un prag de ${formatNumber(data.threshold_percent)}% fata de pretul estimat de model.
      </p>
    </div>
  `;
}

async function submitPrediction(event) {
  if (event) {
    event.preventDefault();
  }

  const url = urlInput.value.trim();
  if (!currentUser) {
    setMessage("Te rog autentifica-te sau creeaza un cont inainte de analiza.", "error");
    authPanel.scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }

  if (!url) {
    setMessage("Te rog introdu un link valid de Autovit sau mobile.de.", "error");
    return;
  }

  const site = inferSiteFromUrl(url);
  if (!site) {
    setMessage("Momentan pot analiza doar linkuri de pe Autovit sau mobile.de.", "error");
    return;
  }

  const thresholdPercent = Number(thresholdInput.value || 15);
  if (!Number.isFinite(thresholdPercent) || thresholdPercent <= 0 || thresholdPercent > 100) {
    setMessage("Toleranta trebuie sa fie intre 1% si 100%.", "error");
    return;
  }
  const ensembleMethod = ensembleMethodInput.value || "inverse_mae_with_agreement";

  setLoading(true);
  setMessage("Analizam anuntul...");

  try {
    const response = await fetch("/predict", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        site,
        url,
        threshold_percent: thresholdPercent,
        ensemble_method: ensembleMethod,
        similar_limit: similarLimit,
      }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Analiza nu a putut fi finalizata.");
    }

    renderResult(data);
    loadHistory();
    setMessage("Analiza a fost finalizata cu succes.", "success");
  } catch (error) {
    setMessage(error.message || "A aparut o eroare la analiza.", "error");
  } finally {
    setLoading(false);
  }
}

function loadExample() {
  urlInput.value = exampleUrl;
  setMessage("Am completat un exemplu. Apasa pe buton pentru analiza.");
}

form.addEventListener("submit", submitPrediction);
exampleButton.addEventListener("click", loadExample);
loginForm.addEventListener("submit", submitLogin);
registerForm.addEventListener("submit", submitRegister);
showLoginButton.addEventListener("click", () => showAuthMode("login"));
showRegisterButton.addEventListener("click", () => showAuthMode("register"));
logoutButton.addEventListener("click", logout);
refreshHistoryButton.addEventListener("click", loadHistory);
clearHistoryButton.addEventListener("click", clearHistory);
themeToggle.addEventListener("click", () => {
  const current = document.body.dataset.theme === "dark" ? "dark" : "light";
  applyTheme(current === "dark" ? "light" : "dark");
});

initializeTheme();
showAuthMode("login");
checkSession();
