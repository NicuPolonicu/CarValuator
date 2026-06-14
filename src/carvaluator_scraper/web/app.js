const $ = (id) => document.getElementById(id);

const elements = {
  form: $("predictForm"),
  urlInput: $("urlInput"),
  ensembleMethodInput: $("ensembleMethodInput"),
  thresholdInput: $("thresholdInput"),
  submitButton: $("submitButton"),
  exampleButton: $("exampleButton"),
  formMessage: $("formMessage"),
  resultPanel: $("resultPanel"),
  loadingOverlay: $("loadingOverlay"),
  loadingMessage: $("loadingMessage"),
  themeToggle: $("themeToggle"),
  themeToggleLabel: $("themeToggleLabel"),
  authPanel: $("authPanel"),
  authStatus: $("authStatus"),
  authMessage: $("authMessage"),
  logoutButton: $("logoutButton"),
  loginForm: $("loginForm"),
  registerForm: $("registerForm"),
  showLoginButton: $("showLoginButton"),
  showRegisterButton: $("showRegisterButton"),
  loginButton: $("loginButton"),
  registerButton: $("registerButton"),
  loginIdentifier: $("loginIdentifier"),
  loginPassword: $("loginPassword"),
  registerEmail: $("registerEmail"),
  registerUsername: $("registerUsername"),
  registerPassword: $("registerPassword"),
  historyPanel: $("historyPanel"),
  historyLoginGate: $("historyLoginGate"),
  historyList: $("historyList"),
  historyDetailPanel: $("historyDetailPanel"),
  refreshHistoryButton: $("refreshHistoryButton"),
  clearHistoryButton: $("clearHistoryButton"),
  evaluatorPage: $("evaluatorPage"),
  historyPage: $("historyPage"),
  explanationsPage: $("explanationsPage"),
  helpDialog: $("helpDialog"),
  helpDialogTitle: $("helpDialogTitle"),
  helpDialogBody: $("helpDialogBody"),
  helpDialogClose: $("helpDialogClose"),
};

const exampleUrl = "https://www.autovit.ro/autoturisme/anunt/fiat-fiorino-ID7HMUoe.html";
const similarLimit = 4;
const loadingMessages = [
  "Preluam anuntul si extragem datele principale...",
  "Standardizam specificatiile masinii...",
  "Comparam estimarile modelelor...",
  "Cautam masini similare in baza de date...",
];

const helpContent = {
  voting: {
    title: "Cum este combinat pretul final?",
    body: `
      <p><strong>Doar MAE</strong> acorda o pondere mai mare modelelor care au avut eroarea medie cea mai mica la testare.</p>
      <p><strong>MAE + acord</strong> face acelasi lucru, dar reduce si influenta unei estimari care este foarte departe de restul modelelor.</p>
    `,
  },
  tolerance: {
    title: "Ce este toleranta verdictului?",
    body: `
      <p>Toleranta este marja acceptata in jurul pretului estimat. La 10%, un pret aflat cu cel mult 10% peste sau sub estimare este considerat corect.</p>
      <p>O toleranta mai mica produce verdicte mai stricte.</p>
    `,
  },
  weighted: {
    title: "Estimarea finala ponderata",
    body: `
      <p>Acesta este pretul principal al raportului. Nu este rezultatul unui singur algoritm, ci o combinatie a modelelor disponibile.</p>
      <p>Modelele cu erori istorice mai mici primesc o influenta mai mare.</p>
    `,
  },
  mae: {
    title: "MAE",
    body: "<p>Eroarea medie absoluta, exprimata in EUR. Mai mic este mai bine. Un MAE de 2.500 EUR inseamna o abatere medie de aproximativ 2.500 EUR.</p>",
  },
  r2: {
    title: "R2",
    body: "<p>Arata cat de bine explica modelul variatia preturilor. Mai aproape de 1 este mai bine, dar nu reprezinta un procent de precizie.</p>",
  },
  rmse: {
    title: "RMSE",
    body: "<p>Masura a erorii care penalizeaza mai mult greselile foarte mari. Mai mic este mai bine.</p>",
  },
  agreement: {
    title: "Acord intre modele",
    body: "<p>Arata cat de apropiata este estimarea unui model de centrul estimarilor celorlalte modele. Un acord mic reduce ponderea unei valori izolate.</p>",
  },
  votingExcluded: {
    title: "De ce Voting Ensemble este exclus?",
    body: `
      <p>Voting Ensemble combina deja predictiile mai multor modele de baza.</p>
      <p>Daca ar primi inca o pondere in estimarea finala, aceleasi modele ar fi numarate de doua ori. De aceea ii afisam predictia si metricile, dar nu ii calculam Pondere sau Acord.</p>
    `,
  },
  similar: {
    title: "Masini similare",
    body: "<p>Sunt exemple apropiate din dataset dupa marca, model, an, kilometraj si specificatii. Ele ajuta la verificarea rezultatului, dar nu modifica direct pretul final.</p>",
  },
};

let loadingInterval = null;
let currentUser = null;

function currentRoute() {
  if (window.location.pathname === "/istoric") {
    return "history";
  }
  if (window.location.pathname === "/explicatii") {
    return "explanations";
  }
  return "evaluator";
}

function initializeRoute() {
  const route = currentRoute();
  elements.evaluatorPage.classList.toggle("is-hidden", route !== "evaluator");
  elements.historyPage.classList.toggle("is-hidden", route !== "history");
  elements.explanationsPage.classList.toggle("is-hidden", route !== "explanations");

  const routeNames = {
    "/": "evaluator",
    "/istoric": "history",
    "/explicatii": "explanations",
  };
  document.querySelectorAll(".nav-link").forEach((link) => {
    const normalizedRoute = routeNames[link.dataset.route];
    link.classList.toggle("is-active", normalizedRoute === route);
  });

  const titles = {
    evaluator: "CarValuator",
    history: "Istoric | CarValuator",
    explanations: "Explicatii | CarValuator",
  };
  document.title = titles[route];
}

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

function formatMetric(value, digits = 3) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "N/A";
  }
  return Number(value).toFixed(digits);
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "N/A";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${Number(value).toFixed(2)}%`;
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
  const mapping = {
    too_low_suspicious: "Pret suspect de mic",
    too_high: "Pret prea mare",
    fair: "Pret corect",
  };
  return mapping[verdict] || "Necunoscut";
}

function humanizeReason(reason) {
  const mapping = {
    "same make": "aceeasi marca",
    "same model": "acelasi model",
    "same fuel": "acelasi combustibil",
    "same gearbox": "aceeasi cutie",
    "year within 1": "an apropiat",
    "mileage within 25k km": "kilometri apropiati",
    "power within 20 hp": "putere apropiata",
    "engine within 250 cm3": "motorizare apropiata",
  };
  return mapping[reason] || reason;
}

function humanizeModelName(name) {
  const mapping = {
    svr_rbf: "SVR",
    ridge: "Ridge",
    knn_distance: "KNN",
    random_forest: "Random Forest",
    extra_trees: "Extra Trees",
    gradient_boosting: "Gradient Boosting",
    voting_ensemble: "Voting Ensemble",
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

function getEnsembleMethod(data) {
  const finalEstimate = (data.model_estimates || []).find((item) => item.model === "weighted_average");
  return finalEstimate?.weighting || data.ensemble_method || null;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#39;");
}

function helpButton(key, label) {
  return `<button class="help-button" type="button" data-help="${escapeHtml(key)}" aria-label="${escapeHtml(label)}">?</button>`;
}

function bindHelpButtons(root = document) {
  root.querySelectorAll("[data-help]").forEach((button) => {
    if (button.dataset.helpBound === "1") {
      return;
    }
    button.dataset.helpBound = "1";
    button.addEventListener("click", () => openHelp(button.dataset.help));
  });
}

function openHelp(key) {
  const content = helpContent[key];
  if (!content) {
    return;
  }
  elements.helpDialogTitle.textContent = content.title;
  elements.helpDialogBody.innerHTML = content.body;
  elements.helpDialog.showModal();
}

function setMessage(message, tone = "") {
  elements.formMessage.textContent = message;
  elements.formMessage.className = `form-message${tone ? ` is-${tone}` : ""}`;
}

function setAuthMessage(message, tone = "") {
  elements.authMessage.textContent = message;
  elements.authMessage.className = `form-message${tone ? ` is-${tone}` : ""}`;
}

function setAuthLoading(isLoading) {
  [
    elements.loginButton,
    elements.registerButton,
    elements.logoutButton,
    elements.clearHistoryButton,
    elements.refreshHistoryButton,
  ].forEach((button) => {
    button.disabled = isLoading;
  });
}

function setLoading(isLoading) {
  elements.submitButton.disabled = isLoading;
  elements.exampleButton.disabled = isLoading;
  elements.submitButton.querySelector(".button-text").textContent = isLoading
    ? "Se analizeaza..."
    : "Analizeaza anuntul";

  if (isLoading) {
    let index = 0;
    elements.loadingMessage.textContent = loadingMessages[0];
    elements.loadingOverlay.classList.add("is-visible");
    elements.loadingOverlay.setAttribute("aria-hidden", "false");
    loadingInterval = window.setInterval(() => {
      index = (index + 1) % loadingMessages.length;
      elements.loadingMessage.textContent = loadingMessages[index];
    }, 1300);
    return;
  }

  window.clearInterval(loadingInterval);
  loadingInterval = null;
  elements.loadingOverlay.classList.remove("is-visible");
  elements.loadingOverlay.setAttribute("aria-hidden", "true");
}

function applyTheme(theme) {
  document.body.dataset.theme = theme;
  localStorage.setItem("carvaluator-theme", theme);
  elements.themeToggleLabel.textContent = theme === "dark" ? "Mod luminos" : "Mod intunecat";
}

function initializeTheme() {
  const stored = localStorage.getItem("carvaluator-theme");
  if (stored === "light" || stored === "dark") {
    applyTheme(stored);
    return;
  }
  applyTheme(window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
}

function renderAuthState(user) {
  currentUser = user;
  const route = currentRoute();

  if (user) {
    elements.authStatus.textContent = `Logat ca ${user.username}`;
    elements.logoutButton.classList.remove("is-hidden");
    elements.authPanel.classList.add("is-hidden");
    elements.historyLoginGate.classList.add("is-hidden");
    elements.historyPanel.classList.toggle("is-hidden", route !== "history");
    elements.submitButton.disabled = false;
    if (route === "evaluator") {
      setMessage("Poti analiza anunturi Autovit sau mobile.de.", "success");
    }
    if (route === "history") {
      loadHistory();
    }
    return;
  }

  elements.authStatus.textContent = "Neautentificat";
  elements.logoutButton.classList.add("is-hidden");
  elements.authPanel.classList.toggle("is-hidden", route !== "evaluator");
  elements.historyPanel.classList.add("is-hidden");
  elements.historyLoginGate.classList.toggle("is-hidden", route !== "history");
  elements.historyDetailPanel.classList.add("is-hidden");
  elements.submitButton.disabled = false;
}

function showAuthMode(mode) {
  const isLogin = mode === "login";
  elements.loginForm.classList.toggle("is-hidden", !isLogin);
  elements.registerForm.classList.toggle("is-hidden", isLogin);
  elements.showLoginButton.classList.toggle("is-active", isLogin);
  elements.showRegisterButton.classList.toggle("is-active", !isLogin);
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
      if (currentRoute() === "evaluator") {
        setMessage("Autentifica-te sau creeaza un cont pentru a analiza anunturi.");
      }
      return;
    }
    const data = await response.json();
    renderAuthState(data.user);
  } catch (error) {
    renderAuthState(null);
    if (currentRoute() === "evaluator") {
      setMessage("Nu am putut verifica sesiunea. Serverul trebuie pornit pentru login.", "error");
    }
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
        identifier: elements.loginIdentifier.value.trim(),
        password: elements.loginPassword.value,
      }),
    });
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, "Login esuat."));
    }
    const data = await response.json();
    elements.loginPassword.value = "";
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
        email: elements.registerEmail.value.trim(),
        username: elements.registerUsername.value.trim(),
        password: elements.registerPassword.value,
      }),
    });
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, "Contul nu a putut fi creat."));
    }
    const data = await response.json();
    elements.registerPassword.value = "";
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
    if (currentRoute() === "evaluator") {
      setMessage("Te-ai delogat. Autentifica-te pentru a analiza un anunt.");
    }
  }
}

async function loadHistory() {
  if (!currentUser) {
    return;
  }
  elements.historyList.innerHTML = '<p class="history-empty">Incarcam istoricul...</p>';
  try {
    const response = await fetch("/history?limit=100", { credentials: "same-origin" });
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, "Nu am putut incarca istoricul."));
    }
    const data = await response.json();
    renderHistory(data.items || []);
  } catch (error) {
    elements.historyList.innerHTML = `<p class="history-empty is-error">${escapeHtml(error.message || "Nu am putut incarca istoricul.")}</p>`;
  }
}

async function loadHistoryDetail(historyId) {
  if (!currentUser || !historyId) {
    return;
  }
  elements.historyDetailPanel.classList.remove("is-hidden");
  elements.historyDetailPanel.innerHTML = '<p class="history-empty">Incarcam raportul complet...</p>';
  try {
    const response = await fetch(`/history/${encodeURIComponent(historyId)}`, {
      credentials: "same-origin",
    });
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, "Nu am putut incarca raportul."));
    }
    const data = await response.json();
    renderReport(data.prediction, elements.historyDetailPanel, { historical: true });
    elements.historyDetailPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    elements.historyDetailPanel.innerHTML = `<p class="history-empty is-error">${escapeHtml(error.message || "Nu am putut incarca raportul.")}</p>`;
  }
}

async function deleteHistoryItem(historyId) {
  if (!currentUser || !historyId || !window.confirm("Stergi aceasta analiza din istoric?")) {
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
    elements.historyDetailPanel.classList.add("is-hidden");
    await loadHistory();
  } catch (error) {
    window.alert(error.message || "Nu am putut sterge analiza.");
  } finally {
    setAuthLoading(false);
  }
}

async function clearHistory() {
  if (!currentUser || !window.confirm("Stergi toate analizele din istoricul acestui cont?")) {
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
    elements.historyDetailPanel.classList.add("is-hidden");
    await loadHistory();
  } catch (error) {
    window.alert(error.message || "Nu am putut sterge istoricul.");
  } finally {
    setAuthLoading(false);
  }
}

function renderHistory(items) {
  if (!items.length) {
    elements.historyList.innerHTML = '<p class="history-empty">Nu ai analizat inca niciun anunt.</p>';
    return;
  }

  elements.historyList.innerHTML = items.map((item) => `
    <article class="history-card">
      ${item.image_url
        ? `<img src="${escapeHtml(item.image_url)}" alt="${escapeHtml(item.title || "Anunt analizat")}">`
        : '<div class="history-image-placeholder">Fara imagine</div>'}
      <div class="history-content">
        <div class="history-meta">
          <span>${escapeHtml(item.source || "unknown")}</span>
          <span>${formatDateTime(item.created_at)}</span>
        </div>
        <h3>${escapeHtml(item.title || "Anunt fara titlu")}</h3>
        <div class="history-values">
          <span>Anunt <strong>${formatCurrency(item.actual_price_eur)}</strong></span>
          <span>Estimat <strong>${formatCurrency(item.predicted_price_eur)}</strong></span>
          <span class="verdict-pill ${escapeHtml(item.verdict || "unknown")}">${escapeHtml(humanizeVerdict(item.verdict))}</span>
        </div>
        <div class="history-settings">
          <span>Marja ${formatNumber(item.threshold_percent)}%</span>
          <span>${escapeHtml(humanizeWeightingMethod(item.ensemble_method))}</span>
          <span>${formatNumber(item.similar_count)} masini similare</span>
        </div>
        <div class="history-card-actions">
          <button class="secondary-button compact-button" type="button" data-view-history="${escapeHtml(item.id)}">Vezi raportul complet</button>
          <a href="${escapeHtml(item.url || "#")}" target="_blank" rel="noreferrer">Anunt original</a>
          <button class="history-delete-button" type="button" data-delete-history="${escapeHtml(item.id)}">Sterge</button>
        </div>
      </div>
    </article>
  `).join("");

  elements.historyList.querySelectorAll("[data-view-history]").forEach((button) => {
    button.addEventListener("click", () => loadHistoryDetail(button.dataset.viewHistory));
  });
  elements.historyList.querySelectorAll("[data-delete-history]").forEach((button) => {
    button.addEventListener("click", () => deleteHistoryItem(button.dataset.deleteHistory));
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
        <div class="section-title-row">
          <div>
            <p class="section-kicker">Masini similare</p>
            <h3>Nu am gasit suficiente anunturi comparabile.</h3>
          </div>
          ${helpButton("similar", "Explica masinile similare")}
        </div>
      </section>
    `;
  }

  const cards = similarListings.map((listing) => {
    const reasons = (listing.match_reasons || [])
      .map((reason) => `<span class="match-tag">${escapeHtml(humanizeReason(reason))}</span>`)
      .join("");
    return `
      <article class="similar-card">
        <div class="similar-card-body">
          <span class="card-eyebrow">Masina similara</span>
          <h4>${escapeHtml(listing.title || "Anunt fara titlu")}</h4>
          <p class="similar-price">${formatCurrency(listing.price_eur)}</p>
          <p class="similar-specs">${formatNumber(listing.year)} · ${formatNumber(listing.mileage_km)} km · ${escapeHtml(listing.fuel_type || "N/A")}</p>
          <p class="similar-specs">${escapeHtml(listing.transmission || "N/A")} · ${formatNumber(listing.power_hp)} cp</p>
          <div class="match-tags">${reasons}</div>
        </div>
        <a class="similar-link" href="${escapeHtml(listing.url || "#")}" target="_blank" rel="noreferrer">Vezi anuntul</a>
      </article>
    `;
  }).join("");

  return `
    <section class="similar-section">
      <div class="section-title-row">
        <div>
          <p class="section-kicker">Masini similare</p>
          <h3>Anunturi apropiate din baza de date</h3>
        </div>
        ${helpButton("similar", "Explica masinile similare")}
      </div>
      <div class="similar-grid">${cards}</div>
    </section>
  `;
}

function buildModelEstimatesMarkup(modelEstimates) {
  const estimates = modelEstimates.filter((item) => item.model !== "weighted_average");
  if (!estimates.length) {
    return '<p class="history-empty">Nu sunt disponibile estimari individuale pentru acest raport.</p>';
  }

  return `
    <div class="models-grid">
      ${estimates.map((item) => {
        const excludedFromWeightedAverage =
          item.excluded_from_weighted_average || item.model === "voting_ensemble";
        return `
        <article class="model-card">
          <span class="card-eyebrow">Model</span>
          <h4>${escapeHtml(humanizeModelName(item.model))}</h4>
          <strong>${formatCurrency(item.predicted_price_eur)}</strong>
          <dl class="metric-list">
            <div>
              <dt>MAE ${helpButton("mae", "Explica MAE")}</dt>
              <dd>${formatCurrency(item.mae)}</dd>
            </div>
            <div>
              <dt>RMSE ${helpButton("rmse", "Explica RMSE")}</dt>
              <dd>${formatCurrency(item.rmse)}</dd>
            </div>
            <div>
              <dt>R2 ${helpButton("r2", "Explica R2")}</dt>
              <dd>${formatMetric(item.r2)}</dd>
            </div>
            ${item.ensemble_weight != null ? `
              <div>
                <dt>Pondere</dt>
                <dd>${(Number(item.ensemble_weight) * 100).toFixed(1)}%</dd>
              </div>
            ` : excludedFromWeightedAverage ? `
              <div>
                <dt>Pondere ${helpButton("votingExcluded", "Explica excluderea din estimarea finala")}</dt>
                <dd>Exclus</dd>
              </div>
            ` : ""}
            ${item.agreement_weight != null ? `
              <div>
                <dt>Acord ${helpButton("agreement", "Explica acordul intre modele")}</dt>
                <dd>${(Number(item.agreement_weight) * 100).toFixed(0)}%</dd>
              </div>
            ` : excludedFromWeightedAverage ? `
              <div>
                <dt>Acord</dt>
                <dd>Nu se calculeaza</dd>
              </div>
            ` : ""}
          </dl>
          ${item.is_best_model ? '<div class="model-best-badge">Cel mai bun model individual</div>' : ""}
          ${excludedFromWeightedAverage ? '<div class="model-excluded-badge">Afisat pentru comparatie, neinclus in pretul final</div>' : ""}
        </article>
      `;
      }).join("")}
    </div>
  `;
}

function buildModelDisclosure(data) {
  return `
    <details class="model-disclosure">
      <summary>
        <span>
          <strong>Vezi performanta fiecarui model</strong>
          <small>Estimari individuale, MAE, RMSE si R2</small>
        </span>
        <span class="disclosure-icon" aria-hidden="true">+</span>
      </summary>
      <div class="model-disclosure-content">
        <div class="section-title-row compact-title">
          <div>
            <p class="section-kicker">Comparatie modele</p>
            <h3>Cum a contribuit fiecare model?</h3>
          </div>
          ${helpButton("weighted", "Explica estimarea finala ponderata")}
        </div>
        ${buildModelEstimatesMarkup(data.model_estimates || [])}
      </div>
    </details>
  `;
}

function renderReport(data, target, options = {}) {
  const normalized = data.normalized_listing || {};
  const verdictClass = data.verdict || "unknown";
  const similarListings = data.similar_listings || [];
  const weightingMethod = getEnsembleMethod(data);
  const historicalLabel = options.historical
    ? `<div class="report-history-label">Raport salvat la ${formatDateTime(data.history_created_at)}</div>`
    : "";

  target.classList.remove("is-empty", "is-hidden");
  target.innerHTML = `
    <div class="result-card">
      ${historicalLabel}
      <div class="result-top">
        <div class="result-main">
          <div class="section-title-row">
            <p class="section-kicker">Verdict final</p>
            ${helpButton("weighted", "Explica estimarea finala ponderata")}
          </div>
          <h2>${escapeHtml(data.title || "Anunt fara titlu")}</h2>
          <p class="result-subcopy">Concluzia este calculata din estimarea finala ponderata a modelelor.</p>

          <div class="verdict-row">
            <span class="verdict-pill ${escapeHtml(verdictClass)}">${escapeHtml(humanizeVerdict(verdictClass))}</span>
            <span class="spec-pill">Diferenta ${formatPercent(data.delta_percent)}</span>
          </div>

          <div class="price-grid">
            <article class="price-card">
              <span>Pret anunt</span>
              <strong>${formatCurrency(data.actual_price_eur)}</strong>
            </article>
            <article class="price-card featured-price">
              <span>Estimare finala</span>
              <strong>${formatCurrency(data.predicted_price_eur)}</strong>
            </article>
            <article class="price-card">
              <span>Verdict</span>
              <strong>${escapeHtml(humanizeVerdict(verdictClass))}</strong>
            </article>
          </div>

          <div class="report-settings">
            <span>Marja verdict: <strong>${formatNumber(data.threshold_percent)}%</strong></span>
            <span>Vot: <strong>${escapeHtml(humanizeWeightingMethod(weightingMethod))}</strong></span>
          </div>
          <div class="spec-list">${buildSpecPills(normalized)}</div>
        </div>
        ${buildImageMarkup(data)}
      </div>

      ${buildModelDisclosure(data)}
      ${buildSimilarMarkup(similarListings)}

      <p class="result-note">
        Verdictul compara pretul anuntului cu estimarea finala si aplica marja de ${formatNumber(data.threshold_percent)}%.
      </p>
    </div>
  `;
  bindHelpButtons(target);
}

function inferSiteFromUrl(url) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (host.endsWith("autovit.ro")) {
      return "autovit";
    }
    if (host.endsWith("mobile.de")) {
      return "mobilede";
    }
  } catch (error) {
    return null;
  }
  return null;
}

async function submitPrediction(event) {
  event.preventDefault();
  const url = elements.urlInput.value.trim();
  if (!currentUser) {
    setMessage("Te rog autentifica-te sau creeaza un cont inainte de analiza.", "error");
    elements.authPanel.scrollIntoView({ behavior: "smooth", block: "center" });
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

  const thresholdPercent = Number(elements.thresholdInput.value || 15);
  if (!Number.isFinite(thresholdPercent) || thresholdPercent <= 0 || thresholdPercent > 100) {
    setMessage("Toleranta trebuie sa fie intre 1% si 100%.", "error");
    return;
  }

  setLoading(true);
  setMessage("Analizam anuntul...");
  try {
    const response = await fetch("/predict", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        site,
        url,
        threshold_percent: thresholdPercent,
        ensemble_method: elements.ensembleMethodInput.value || "inverse_mae_with_agreement",
        similar_limit: similarLimit,
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Analiza nu a putut fi finalizata.");
    }
    renderReport(data, elements.resultPanel);
    setMessage("Analiza a fost finalizata cu succes.", "success");
  } catch (error) {
    setMessage(error.message || "A aparut o eroare la analiza.", "error");
  } finally {
    setLoading(false);
  }
}

function loadExample() {
  elements.urlInput.value = exampleUrl;
  setMessage("Am completat un exemplu. Apasa pe buton pentru analiza.");
}

elements.form.addEventListener("submit", submitPrediction);
elements.exampleButton.addEventListener("click", loadExample);
elements.loginForm.addEventListener("submit", submitLogin);
elements.registerForm.addEventListener("submit", submitRegister);
elements.showLoginButton.addEventListener("click", () => showAuthMode("login"));
elements.showRegisterButton.addEventListener("click", () => showAuthMode("register"));
elements.logoutButton.addEventListener("click", logout);
elements.refreshHistoryButton.addEventListener("click", loadHistory);
elements.clearHistoryButton.addEventListener("click", clearHistory);
elements.themeToggle.addEventListener("click", () => {
  const current = document.body.dataset.theme === "dark" ? "dark" : "light";
  applyTheme(current === "dark" ? "light" : "dark");
});
elements.helpDialogClose.addEventListener("click", () => elements.helpDialog.close());
elements.helpDialog.addEventListener("click", (event) => {
  if (event.target === elements.helpDialog) {
    elements.helpDialog.close();
  }
});

initializeRoute();
initializeTheme();
showAuthMode("login");
bindHelpButtons();
checkSession();
