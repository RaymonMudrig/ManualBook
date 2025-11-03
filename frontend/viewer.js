// Unified Document Viewer & Query Interface

// Document viewer elements
const docSelector = document.getElementById("doc-selector");
const tocNav = document.getElementById("toc-nav");
const documentStatus = document.getElementById("document-status");
const documentArticle = document.getElementById("document-article");

// Query interface elements
const queryForm = document.getElementById("query-form");
const queryInput = document.getElementById("query-input");
const thresholdInput = document.getElementById("threshold-input");
const topkInput = document.getElementById("topk-input");
const submitBtn = document.getElementById("submit-btn");
const queryStatus = document.getElementById("query-status");
const answerBlock = document.getElementById("answer-block");
const answerText = document.getElementById("answer-text");
const modeLabel = document.getElementById("mode-label");
const sourcesBlock = document.getElementById("sources-block");
const sourcesList = document.getElementById("sources-list");

// Tab elements
const tabDocument = document.getElementById("tab-document");
const tabQuery = document.getElementById("tab-query");
const contentDocument = document.getElementById("content-document");
const contentQuery = document.getElementById("content-query");

const DEFAULT_API_BASE_URL = "/api";
let apiBaseUrl = null;
let apiBaseUrlPromise = null;

// State
let currentDocument = null;
let tocItems = [];
let isScrollingFromClick = false;

const MODE_LABELS = {
  rag: "Knowledge Base",
  catalog_rag: "Catalog (Phase 2)",
  web: "Web Search",
  hybrid: "Hybrid",
  none: "No Data",
};

// Initialize
async function init() {
  await getApiBaseUrl();
  await loadDocumentList();
  setupTabSwitching();
  setupQueryForm();
}

// Setup tab switching
function setupTabSwitching() {
  tabDocument.addEventListener("click", () => switchTab("document"));
  tabQuery.addEventListener("click", () => switchTab("query"));
}

function switchTab(tabName) {
  // Update tab buttons
  [tabDocument, tabQuery].forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tabName);
  });

  // Update tab content
  [contentDocument, contentQuery].forEach((content) => {
    const isActive = content.id === `content-${tabName}`;
    content.classList.toggle("active", isActive);
  });
}

// Load list of available documents
async function loadDocumentList() {
  try {
    const response = await apiFetch("/documents");
    if (!response.ok) {
      throw new Error(`Failed to load documents: ${response.status}`);
    }

    const data = await response.json();
    const documents = data.documents || [];

    // Clear existing options
    docSelector.innerHTML = "";

    if (documents.length === 0) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No documents available";
      docSelector.appendChild(option);
      return;
    }

    // Add document options
    documents.forEach((doc) => {
      const option = document.createElement("option");
      option.value = doc.id;
      option.textContent = doc.title;
      docSelector.appendChild(option);
    });

    // Add change listener
    docSelector.addEventListener("change", (e) => {
      if (e.target.value) {
        loadDocument(e.target.value);
      }
    });

    // Auto-select first document
    if (documents.length > 0) {
      docSelector.value = documents[0].id;
      await loadDocument(documents[0].id);
    }
  } catch (error) {
    console.error("Error loading document list:", error);
    showDocumentStatus("Failed to load document list", "error");
  }
}

// Load a specific document
async function loadDocument(docId) {
  showDocumentStatus("Loading document...", "loading");
  tocNav.innerHTML = '<div class="toc-loading">Loading...</div>';
  documentArticle.hidden = true;

  try {
    const response = await apiFetch(`/documents/${docId}`);
    if (!response.ok) {
      throw new Error(`Failed to load document: ${response.status}`);
    }

    const data = await response.json();
    currentDocument = data;

    // Render TOC
    renderTOC(data.toc);

    // Render document content with heading IDs
    renderDocument(data.content, data.toc);

    showDocumentStatus("", "success");
    documentArticle.hidden = false;

    // Switch to document tab
    switchTab("document");
  } catch (error) {
    console.error("Error loading document:", error);
    showDocumentStatus("Failed to load document", "error");
  }
}

// Render Table of Contents
function renderTOC(toc) {
  if (!toc || toc.length === 0) {
    tocNav.innerHTML = '<div class="toc-loading">No headings found</div>';
    return;
  }

  tocNav.innerHTML = "";
  tocItems = [];

  toc.forEach((item) => {
    const link = document.createElement("a");
    link.className = "toc-item";
    link.setAttribute("data-level", item.level);
    link.setAttribute("data-id", item.id);
    link.textContent = item.title;
    link.href = `#${item.id}`;

    // Handle click
    link.addEventListener("click", (e) => {
      e.preventDefault();
      scrollToHeading(item.id);
    });

    tocNav.appendChild(link);
    tocItems.push({ id: item.id, element: link });
  });

  // Add scroll listener to highlight active TOC item
  const documentContent = contentDocument;
  documentContent.addEventListener("scroll", handleScroll);
}

// Render document content with heading IDs
function renderDocument(content, toc) {
  // First, parse the markdown
  let html = marked.parse(content);

  // Add IDs to headings based on TOC
  toc.forEach((item) => {
    // Create a regex to find headings with the same text
    const escapedTitle = escapeRegExp(item.title);
    const headingRegex = new RegExp(
      `<h${item.level}>\\s*${escapedTitle}\\s*</h${item.level}>`,
      "i"
    );

    // Replace heading with one that has an ID
    html = html.replace(
      headingRegex,
      `<h${item.level} id="${item.id}">${item.title}</h${item.level}>`
    );
  });

  documentArticle.innerHTML = html;
}

// Scroll to a specific heading
function scrollToHeading(headingId) {
  // Make sure we're on the document tab
  switchTab("document");

  const heading = document.getElementById(headingId);
  if (!heading) {
    console.warn(`Heading with ID "${headingId}" not found`);
    return;
  }

  // Set flag to prevent scroll event from triggering highlight
  isScrollingFromClick = true;

  // Scroll the document tab content
  const scrollContainer = contentDocument;
  const headingTop = heading.offsetTop;
  scrollContainer.scrollTop = headingTop - 20; // 20px offset from top

  // Update active TOC item
  updateActiveTOCItem(headingId);

  // Reset flag after scroll animation
  setTimeout(() => {
    isScrollingFromClick = false;
  }, 1000);
}

// Handle scroll to highlight active TOC item
function handleScroll() {
  if (isScrollingFromClick) return;

  // Only handle scroll if document tab is active
  if (!contentDocument.classList.contains("active")) return;

  const scrollTop = contentDocument.scrollTop;
  const viewportHeight = contentDocument.clientHeight;
  const centerY = scrollTop + viewportHeight / 3;

  let activeId = null;
  let minDistance = Infinity;

  // Find the heading closest to the center of viewport
  tocItems.forEach((item) => {
    const heading = document.getElementById(item.id);
    if (heading) {
      const headingTop = heading.offsetTop;
      const distance = Math.abs(headingTop - centerY);

      if (headingTop <= centerY && distance < minDistance) {
        minDistance = distance;
        activeId = item.id;
      }
    }
  });

  if (activeId) {
    updateActiveTOCItem(activeId);
  }
}

// Update active TOC item
function updateActiveTOCItem(headingId) {
  tocItems.forEach((item) => {
    if (item.id === headingId) {
      item.element.classList.add("active");
      item.element.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
      });
    } else {
      item.element.classList.remove("active");
    }
  });
}

// Show document status message
function showDocumentStatus(message, type) {
  if (!message) {
    documentStatus.style.display = "none";
    return;
  }

  documentStatus.style.display = "block";
  documentStatus.textContent = message;
  documentStatus.className = "content-status";

  if (type === "error") {
    documentStatus.style.color = "#dc2626";
  } else if (type === "loading") {
    documentStatus.style.color = "#64748b";
  } else {
    documentStatus.style.color = "#16a34a";
  }
}

// Setup query form
function setupQueryForm() {
  queryForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = queryInput.value.trim();
    if (!query) {
      return;
    }

    const threshold = parseFloat(thresholdInput.value);
    const topK = parseInt(topkInput.value, 10);

    setQueryStatus("Running semantic query...", "muted");
    setLoading(true);
    clearQueryOutputs();

    // Switch to query tab
    switchTab("query");

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
      renderQueryResult(data);
      setQueryStatus("Query complete.", "success");
    } catch (error) {
      console.error(error);
      setQueryStatus(error.message || "Something went wrong.", "error");
    } finally {
      setLoading(false);
    }
  });
}

function setQueryStatus(message, variant = "muted") {
  queryStatus.textContent = message;
  queryStatus.classList.remove("status--success", "status--error");
  if (variant === "success") {
    queryStatus.classList.add("status--success");
  } else if (variant === "error") {
    queryStatus.classList.add("status--error");
  }
}

function setLoading(isLoading) {
  submitBtn.disabled = isLoading;
  submitBtn.textContent = isLoading ? "Searching..." : "Ask";
}

function clearQueryOutputs() {
  answerBlock.hidden = true;
  sourcesBlock.hidden = true;
  answerText.textContent = "";
  sourcesList.innerHTML = "";
}

function renderQueryResult(data) {
  if (data.answer) {
    answerBlock.hidden = false;
    answerText.innerHTML = marked.parse(data.answer);
    const label = MODE_LABELS[data.mode] || "Result";
    modeLabel.textContent = label;
  }

  // Log steps to console
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

  // Display sources in UI
  if (Array.isArray(data.sources) && data.sources.length) {
    sourcesBlock.hidden = false;

    console.group("📚 Sources");

    data.sources.forEach((source, index) => {
      if (source.article_id) {
        // Phase 2: Catalog articles
        const title = source.title || source.article_id;
        const metadata = [source.intent, source.category].filter(Boolean).join(" · ");
        const content = source.content || "";
        const score = (source.score ?? 0).toFixed(3);

        console.log(`${index + 1}. ${title}`);
        console.log(`   ${metadata} · Score: ${score}`);
        console.log(`   Content (${content.length} chars)`);

        // Fix image paths in content
        const contentWithFixedPaths = content.replace(
          /!\[([^\]]*)\]\(([^)]+)\)/g,
          (match, alt, path) => {
            if (!path.startsWith('http') && !path.startsWith('/')) {
              return `![${alt}](/articles/${path})`;
            }
            return match;
          }
        );

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

  // Log web results to console
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

function escapeRegExp(string) {
  return string.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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
    scripts.find((tag) => tag.src && tag.src.endsWith("viewer.js")) ||
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

// Initialize on page load
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
