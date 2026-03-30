const form = document.getElementById("predictForm");
const urlInput = document.getElementById("urlInput");
const thresholdInput = document.getElementById("thresholdInput");
const submitButton = document.getElementById("submitButton");
const exampleButton = document.getElementById("exampleButton");
const formMessage = document.getElementById("formMessage");
const resultPanel = document.getElementById("resultPanel");
const apiStatus = document.getElementById("apiStatus");
const modelName = document.getElementById("modelName");

const exampleUrl = "https://www.autovit.ro/autoturisme/anunt/bmw-seria-1-ID7HNlbE.html";

function formatCurrency(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "N/A";
  }
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "N/A";
  }
  return new Intl.NumberFormat("en-GB").format(value);
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "N/A";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function humanizeVerdict(verdict) {
  if (verdict === "too_low_suspicious") {
    return "Too Low / Suspicious";
  }
  if (verdict === "too_high") {
    return "Too High";
  }
  if (verdict === "fair") {
    return "Fair Price";
  }
  return "Unknown";
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

function setLoading(isLoading) {
  submitButton.disabled = isLoading;
  exampleButton.disabled = isLoading;
  submitButton.querySelector(".button-text").textContent = isLoading ? "Analyzing..." : "Analyze Price";
}

function renderResult(data) {
  const verdictClass = data.verdict || "unknown";
  const normalized = data.normalized_listing || {};
  const featureItems = (data.selected_features || [])
    .map((feature) => `<div class="feature-chip">${escapeHtml(feature)}</div>`)
    .join("");

  resultPanel.classList.remove("is-empty");
  resultPanel.innerHTML = `
    <div class="result-card">
      <div class="result-top">
        <div class="result-header">
          <p class="verdict-label">Prediction Result</p>
          <h2>${escapeHtml(data.title || "Untitled Listing")}</h2>
          <p class="result-subtitle">
            <a class="inline-link" href="${escapeHtml(data.url || "#")}" target="_blank" rel="noreferrer">Open original listing</a>
          </p>
        </div>
        <div class="verdict-pill ${escapeHtml(verdictClass)}">${escapeHtml(humanizeVerdict(verdictClass))}</div>
      </div>

      <div class="metric-grid">
        <article class="metric-card">
          <span>Listed Price</span>
          <strong>${formatCurrency(data.actual_price_eur)}</strong>
        </article>
        <article class="metric-card">
          <span>Predicted Fair Price</span>
          <strong>${formatCurrency(data.predicted_price_eur)}</strong>
        </article>
        <article class="metric-card">
          <span>Delta vs Model</span>
          <strong>${formatPercent(data.delta_percent)}</strong>
        </article>
      </div>

      <div class="result-sections">
        <section class="detail-card">
          <span>Listing Snapshot</span>
          <div class="detail-list">
            <div class="detail-row"><span>Make / Model</span><strong>${escapeHtml(normalized.make || "N/A")} ${escapeHtml(normalized.model || "")}</strong></div>
            <div class="detail-row"><span>Year</span><strong>${escapeHtml(normalized.year ?? "N/A")}</strong></div>
            <div class="detail-row"><span>Mileage</span><strong>${formatNumber(normalized.mileage_km)} km</strong></div>
            <div class="detail-row"><span>Fuel / Gearbox</span><strong>${escapeHtml(normalized.fuel_type || "N/A")} / ${escapeHtml(normalized.transmission || "N/A")}</strong></div>
            <div class="detail-row"><span>Power / Engine</span><strong>${formatNumber(normalized.power_hp)} hp / ${formatNumber(normalized.engine_capacity_cm3)} cm3</strong></div>
            <div class="detail-row"><span>Seller / City</span><strong>${escapeHtml(normalized.seller_type || "N/A")} / ${escapeHtml(normalized.location_city || "N/A")}</strong></div>
          </div>
        </section>

        <section class="detail-card">
          <span>Model Features Used</span>
          <div class="feature-grid">${featureItems || '<div class="feature-chip">No features reported</div>'}</div>
        </section>
      </div>

      <p class="result-note">
        Model: <strong>${escapeHtml(data.model_name || "unknown")}</strong>.
        Threshold: <strong>${escapeHtml(data.threshold_percent ?? "N/A")}%</strong>.
        The verdict compares the observed ad price against the model's estimated fair price.
      </p>
    </div>
  `;

  modelName.textContent = data.model_name || "Unknown";
}

async function fetchHealth() {
  try {
    const response = await fetch("/health");
    if (!response.ok) {
      throw new Error("Health endpoint unavailable");
    }
    const data = await response.json();
    apiStatus.textContent = data.model_bundle_exists ? "Ready" : "Model Missing";
    if (!data.model_bundle_exists) {
      setMessage("The API is running, but the default model bundle is missing. Set CARVALUATOR_MODEL_BUNDLE.", "error");
    }
  } catch (error) {
    apiStatus.textContent = "Offline";
    setMessage("Could not reach the backend API. Start the FastAPI server first.", "error");
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = urlInput.value.trim();
  const threshold = Number(thresholdInput.value);

  if (!url) {
    setMessage("Please paste an Autovit listing URL.", "error");
    return;
  }

  setLoading(true);
  setMessage("Analyzing the listing and comparing it to the trained price model...");

  try {
    const response = await fetch("/predict", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        site: "autovit",
        url,
        threshold_percent: threshold,
      }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Prediction request failed.");
    }

    renderResult(data);
    setMessage("Prediction completed successfully.", "success");
  } catch (error) {
    setMessage(error.message || "Prediction failed.", "error");
  } finally {
    setLoading(false);
  }
});

exampleButton.addEventListener("click", () => {
  urlInput.value = exampleUrl;
  setMessage("Example listing loaded. Press Analyze Price to run the prediction.");
});

fetchHealth();
