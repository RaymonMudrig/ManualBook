const form = document.getElementById("query-form");
const queryInput = document.getElementById("query-input");
const thresholdInput = document.getElementById("threshold-input");
const topkInput = document.getElementById("topk-input");
const submitBtn = document.getElementById("submit-btn");
const statusEl = document.getElementById("status");
const answerBlock = document.getElementById("answer-block");
const answerText = document.getElementById("answer-text");
const modeLabel = document.getElementById("mode-label");
const sourcesBlock = document.getElementById("sources-block");
const sourcesList = document.getElementById("sources-list");

const DEFAULT_API_BASE_URL = "/api";
let apiBaseUrl = null;
let apiBaseUrlPromise = null;

const MODE_LABELS = {
  rag: "Knowledge Base",
  catalog_rag: "Catalog (Phase 2)",
  web: "Web Search",
  hybrid: "Hybrid",
  none: "No Data",
};

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = queryInput.value.trim();
  if (!query) {
    return;
  }

  const threshold = parseFloat(thresholdInput.value);
  const topK = parseInt(topkInput.value, 10);

  setStatus("Running agent pipeline…", "muted");
  setLoading(true);
  clearOutputs();

  try {
    const payload = {
      query,
      top_k: Number.isFinite(topK) ? topK : undefined,
    };
    if (!Number.isNaN(threshold)) {
      payload.threshold = Math.max(0, Math.min(1, threshold));
    }

    const response = await apiFetch("/query", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const message = await safeJson(response);
      throw new Error(message?.detail || `Request failed (${response.status})`);
    }

    const data = await response.json();
    renderResult(data);
    setStatus("Agent run complete.", "success");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Something went wrong.", "error");
  } finally {
    setLoading(false);
  }
});

function setStatus(message, variant = "muted") {
  statusEl.textContent = message;
  statusEl.classList.remove("status--success", "status--error");
  if (variant === "success") {
    statusEl.classList.add("status--success");
  } else if (variant === "error") {
    statusEl.classList.add("status--error");
  }
}

function setLoading(isLoading) {
  submitBtn.disabled = isLoading;
  submitBtn.textContent = isLoading ? "Searching…" : "Ask";
}

function clearOutputs() {
  answerBlock.hidden = true;
  sourcesBlock.hidden = true;
  answerText.textContent = "";
  sourcesList.innerHTML = "";
}

function renderResult(data) {
  if (data.answer) {
    answerBlock.hidden = false;
    // Render answer as markdown
    answerText.innerHTML = marked.parse(data.answer);
    const label = MODE_LABELS[data.mode] || "Result";
    modeLabel.textContent = label;
  }

  // Log steps to console instead of displaying in UI
  if (Array.isArray(data.steps) && data.steps.length) {
    console.group("🔍 Agent Trace");
    data.steps.forEach((step, index) => {
      const status = step.status === "success" ? "✅" : step.status === "failed" ? "❌" : "ℹ️";
      const stage = prettifyStage(step.stage || "step");
      console.log(`${index + 1}. ${status} ${stage}`);
      if (step.detail) {
        console.log(`   ${step.detail}`);
      }
      if (step.top_score !== undefined) {
        console.log(`   Top score: ${step.top_score}, Kept: ${step.kept || 0}`);
      }
      if (step.intent) {
        console.log(`   Intent: ${step.intent}, Category: ${step.category}, Confidence: ${step.confidence}`);
      }
    });
    console.groupEnd();
  }

  // Display sources in UI and log to console
  if (Array.isArray(data.sources) && data.sources.length) {
    sourcesBlock.hidden = false;

    // Log to console for debugging
    console.group("📚 Sources");

    data.sources.forEach((source, index) => {
      if (source.article_id) {
        // Phase 2: Catalog articles
        const title = source.title || source.article_id;
        const metadata = [source.intent, source.category].filter(Boolean).join(" · ");
        const content = source.content || "";
        const score = (source.score ?? 0).toFixed(3);

        // Console log
        console.log(`${index + 1}. ${title}`);
        console.log(`   ${metadata} · Score: ${score}`);
        console.log(`   Content (${content.length} chars)`);

        // Fix image paths in content to use /articles/ prefix
        const contentWithFixedPaths = content.replace(
          /!\[([^\]]*)\]\(([^)]+)\)/g,
          (match, alt, path) => {
            // If path doesn't start with http/https or /, prepend /articles/
            if (!path.startsWith("http") && !path.startsWith("/")) {
              return `![${alt}](/articles/${path})`;
            }
            return match;
          }
        );

        // Create article card for UI
        const article = document.createElement("article");
        article.className = "source-article";

        const titleEl = document.createElement("h4");
        titleEl.textContent = title;

        const metaEl = document.createElement("div");
        metaEl.className = "source-meta";
        metaEl.textContent = `${metadata} · Score: ${score}`;

        const contentEl = document.createElement("div");
        contentEl.className = "source-content markdown-content";
        contentEl.innerHTML = marked.parse(contentWithFixedPaths);

        article.appendChild(titleEl);
        article.appendChild(metaEl);
        article.appendChild(contentEl);
        sourcesList.appendChild(article);
      } else {
        // Phase 1: Chunk-based results
        const title = source.title || source.source_file || source.id;
        const sourceInfo = [source.source_kind, source.source_file].filter(Boolean).join(" · ");
        const score = (source.score ?? 0).toFixed(3);

        console.log(`${index + 1}. ${title}`);
        console.log(`   ${sourceInfo} · Score: ${score}`);

        const article = document.createElement("div");
        article.className = "source-article";
        article.innerHTML = `
          <h4>${escapeHtml(title)}</h4>
          <div class="source-meta">${escapeHtml(sourceInfo)} · Score: ${score}</div>
        `;
        sourcesList.appendChild(article);
      }
    });

    console.groupEnd();
  }

  // Log web results to console instead of displaying in UI
  if (Array.isArray(data.fallback_results) && data.fallback_results.length) {
    console.group("🌐 Web Results");
    data.fallback_results.forEach((result, index) => {
      console.log(`${index + 1}. ${result.title || result.url || "Result"}`);
      console.log(`   URL: ${result.url || "#"}`);
      if (result.snippet) {
        console.log(`   ${result.snippet}`);
      }
    });
    console.groupEnd();
  }
}

function prettifyStage(stage) {
  return stage
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function escapeHtml(value = "") {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

async function safeJson(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function normalizeApiBase(value) {
  if (typeof value !== "string") {
    return DEFAULT_API_BASE_URL;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return DEFAULT_API_BASE_URL;
  }
  if (/^https?:\/\//i.test(trimmed)) {
    return trimmed.replace(/\/+$/, "");
  }
  const withLeading = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
  const withoutTrailing = withLeading.replace(/\/+$/, "");
  return withoutTrailing || "/";
}

function resolveConfiguredApiBase() {
  const candidates = [
    window.API_BASE_URL,
    window.__MANUAL_BOOK_CONFIG__?.apiBaseUrl,
    window.__MANUAL_BOOK_API_BASE__,
  ];
  const meta = document.querySelector('meta[name="api-base-url"]');
  if (meta?.content) {
    candidates.push(meta.content);
  }
  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate.trim()) {
      return normalizeApiBase(candidate);
    }
  }
  return null;
}

function deriveApiBaseFromScript() {
  const scripts = Array.from(document.getElementsByTagName("script"));
  const script =
    document.currentScript ||
    scripts.find((tag) => tag.src && tag.src.endsWith("script.js")) ||
    scripts[scripts.length - 1];

  if (script?.src) {
    try {
      const scriptUrl = new URL(script.src, window.location.href);
      const dirPath = scriptUrl.pathname.replace(/\/[^/]*$/, "/");
      const basePath = dirPath.replace(/\/+$/, "");
      return normalizeApiBase(`${basePath}/api`);
    } catch (error) {
      console.warn("Failed to derive API base URL from script path:", error);
    }
  }

  return DEFAULT_API_BASE_URL;
}

async function loadApiBaseUrl() {
  const configured = resolveConfiguredApiBase();
  if (configured) {
    return configured;
  }

  const candidates = [
    new URL("config.json", window.location.href).pathname,
    "/config.json",
  ];

  for (const path of candidates) {
    try {
      const response = await fetch(path, { cache: "no-cache" });
      if (!response.ok) {
        continue;
      }
      const data = await response.json();
      if (data && typeof data.apiBaseUrl === "string" && data.apiBaseUrl.trim()) {
        return normalizeApiBase(data.apiBaseUrl);
      }
    } catch {
      // Ignore config lookup failures; we'll fall back to defaults.
    }
  }

  return deriveApiBaseFromScript();
}

function getApiBaseUrl() {
  if (apiBaseUrl) {
    return Promise.resolve(apiBaseUrl);
  }
  if (!apiBaseUrlPromise) {
    apiBaseUrlPromise = loadApiBaseUrl().then((value) => {
      apiBaseUrl = value || DEFAULT_API_BASE_URL;
      window.__MANUAL_BOOK_API_BASE__ = apiBaseUrl;
      return apiBaseUrl;
    });
  }
  return apiBaseUrlPromise;
}

async function apiFetch(endpoint, options) {
  const base = await getApiBaseUrl();
  const url = joinUrlParts(base, endpoint);
  return fetch(url, options);
}

function joinUrlParts(base, endpoint) {
  const normalizedEndpoint = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
  if (/^https?:\/\//i.test(base)) {
    return `${base}${normalizedEndpoint}`;
  }
  const trimmedBase = base.replace(/\/+$/, "");
  if (!trimmedBase || trimmedBase === "/") {
    return normalizedEndpoint;
  }
  return `${trimmedBase}${normalizedEndpoint}`;
}
