// Check if user is authenticated
const authToken = localStorage.getItem('authToken');
const currentUser = JSON.parse(localStorage.getItem('currentUser'));

if (authToken && currentUser) {
  // Redirect to dashboard if already logged in
  window.location.href = '/dashboard';
}

// Elements
const form = document.getElementById("entry-form");
const contentEl = document.getElementById("content");
const statusEl = document.getElementById("form-status");
const entriesEl = document.getElementById("entries");

const chartOriginalCtx = document.getElementById("chartOriginal");
const chartMultiCtx = document.getElementById("chartMulti");

const rangeSelect = document.getElementById("rangeSelect");
const startDateEl = document.getElementById("startDate");
const endDateEl = document.getElementById("endDate");
const applyFilterBtn = document.getElementById("applyFilter");

const prevBtn = document.getElementById("prevPage");
const nextBtn = document.getElementById("nextPage");
const pageInfo = document.getElementById("pageInfo");

// State
let currentPage = 0;
const pageSize = 10;
let totalEntries = 0;
let chartOriginal, chartMulti;

// Event listeners
rangeSelect.addEventListener("change", (e) => {
  const custom = e.target.value === "custom";
  startDateEl.style.display = custom ? "inline-block" : "none";
  endDateEl.style.display = custom ? "inline-block" : "none";
});

applyFilterBtn.addEventListener("click", () => loadEntries(0));

prevBtn.addEventListener("click", () => {
  if (currentPage > 0) loadEntries(currentPage - 1);
});
nextBtn.addEventListener("click", () => {
  const totalPages = Math.ceil(totalEntries / pageSize);
  if (currentPage < totalPages - 1) loadEntries(currentPage + 1);
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const content = contentEl.value.trim();
  if (!content) return;
  statusEl.textContent = "Analyzing...";
  try {
    await api("/api/entries", { method: "POST", body: JSON.stringify({ content }) });
    contentEl.value = "";
    statusEl.textContent = "Saved.";
    await loadEntries(0);
  } catch (err) {
    statusEl.textContent = "Error: " + err.message;
  }
});

// API function with authentication
async function api(path, opts = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...opts.headers
  };
  
  // Add auth token if available
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
  }
  
  const res = await fetch(path, { headers, ...opts });
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); if (j.error) msg = j.error; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

// Emoji mapping for moods
const emotionEmojis = {
  joy: "😄",
  happiness: "😄",
  sad: "😢",
  sadness: "😢",
  anger: "😠",
  angry: "😠",
  fear: "😨",
  surprise: "😲",
  disgust: "🤢",
  love: "❤️",
  neutral: "😐",
  mixed: "😶"
};
function getEmojiForEmotion(label) {
  if (!label) return "";
  const key = label.toLowerCase();
  return emotionEmojis[key] || "";
}

// Load entries and render charts
async function loadEntries(page = 0) {
  const offset = page * pageSize;
  const range = rangeSelect.value;
  let start_date = "", end_date = "";

  if (["7d", "30d", "365d"].includes(range)) {
    const days = parseInt(range);
    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - days);
    start_date = start.toISOString().slice(0, 10);
    end_date = end.toISOString().slice(0, 10);
  } else if (range === "custom") {
    start_date = startDateEl.value;
    end_date = endDateEl.value;
  }

  let url = `/api/entries?limit=${pageSize}&offset=${offset}`;
  if (start_date) url += `&start_date=${encodeURIComponent(start_date)}`;
  if (end_date) url += `&end_date=${encodeURIComponent(end_date)}`;

  const res = await api(url);
  totalEntries = res.total;
  currentPage = page;

  renderEntries(res.entries);
  renderCharts(res.original_trend, res.multi_trend);
  updatePagination();
}

// Render entries list with emoji
function renderEntries(entries) {
  entriesEl.innerHTML = "";
  entries.forEach(e => {
    const li = document.createElement("li");
    li.className = "entry";
    const when = e.created_at ? new Date(e.created_at).toLocaleString() : "";
    const emoji = getEmojiForEmotion(e.emotion_label);
    const scoreTxt = `${emoji} ${e.emotion_label} ${Number(e.emotion_score || 0).toFixed(2)}%`;
    li.innerHTML = `
      <div>${escapeHtml(e.content || "")}</div>
      <div class="meta">
        <span class="badge ${Number(e.emotion_score) >= 60 ? "ok" : "warn"}">${escapeHtml(scoreTxt)}</span>
        <span class="badge">${escapeHtml(when)}</span>
      </div>`;
    entriesEl.appendChild(li);
  });
}

// Render both charts with emoji in multi-series legend
function renderCharts(originalTrend, multiTrend) {
  if (chartOriginal) chartOriginal.destroy();
  if (chartMulti) chartMulti.destroy();

  // Original trend chart
  const labelsOriginal = originalTrend.map(e => new Date(e.created_at).toLocaleDateString());
  const dataOriginal = originalTrend.map(e => e.score);
  chartOriginal = new Chart(chartOriginalCtx, {
    type: "line",
    data: {
      labels: labelsOriginal,
      datasets: [{
        label: "Top emotion confidence (%)",
        data: dataOriginal,
        borderColor: "#60a5fa",
        backgroundColor: "rgba(96,165,250,0.15)",
        fill: true,
        tension: 0.3
      }]
    },
    options: { responsive: true }
  });

  // Multi-series chart
  const labelsMulti = multiTrend.map(e => new Date(e.created_at).toLocaleDateString());
  const emotionSet = new Set();
  multiTrend.forEach(e => (e.emotions || []).forEach(em => emotionSet.add(em.label)));
  const emotions = Array.from(emotionSet);

  const datasets = emotions.map((label, idx) => ({
    label: `${getEmojiForEmotion(label)} ${label}`,
    data: multiTrend.map(e => {
      const found = (e.emotions || []).find(em => em.label === label);
      return found ? found.score : null;
    }),
    borderColor: colorFromPalette(idx),
    backgroundColor: colorFromPalette(idx, 0.15),
    fill: false,
    tension: 0.3,
    spanGaps: true
  }));

  chartMulti = new Chart(chartMultiCtx, {
    type: "line",
    data: { labels: labelsMulti, datasets },
    options: { responsive: true }
  });
}

// Pagination UI
function updatePagination() {
  const totalPages = Math.max(1, Math.ceil(totalEntries / pageSize));
  pageInfo.textContent = `Page ${currentPage + 1} of ${totalPages}`;
  prevBtn.disabled = currentPage === 0;
  nextBtn.disabled = currentPage >= totalPages - 1;
}

// Color palette helper
function colorFromPalette(i, alpha = 1) {
  const palette = ["#60a5fa", "#34d399", "#f59e0b", "#ef4444", "#a78bfa", "#f472b6", "#22d3ee", "#f87171"];
  const base = palette[i % palette.length];
  if (alpha === 1) return base;
  const bigint = parseInt(base.slice(1), 16);
  const r = (bigint >> 16) & 255;
  const g = (bigint >> 8) & 255;
  const b = bigint & 255;
  return `rgba(${r},${g},${b},${alpha})`;
}

// Escape HTML
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
}

// Initial load
if (authToken && currentUser) {
  loadEntries(0);
} else {
  // Show login form or redirect
  entriesEl.innerHTML = '<p class="no-entries">Please log in to view your entries</p>';
}