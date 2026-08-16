"use strict";

const PAGE_SIZE = 24;
const THEME_MODES = ["auto", "light", "dark"];

const elements = {
  categoryFilters: document.querySelector("#category-filters"),
  clearSearch: document.querySelector("#clear-search"),
  emptyReset: document.querySelector("#empty-reset"),
  emptyState: document.querySelector("#empty-state"),
  lastUpdated: document.querySelector("#last-updated"),
  loadMore: document.querySelector("#load-more"),
  newPapers: document.querySelector("#new-papers"),
  paperList: document.querySelector("#paper-list"),
  recency: document.querySelector("#recency-filter"),
  resetFilters: document.querySelector("#reset-filters"),
  resultContext: document.querySelector("#result-context"),
  resultCount: document.querySelector("#result-count"),
  searchForm: document.querySelector("#search-form"),
  searchInput: document.querySelector("#search-input"),
  sort: document.querySelector("#sort-filter"),
  themeLabel: document.querySelector("#theme-label"),
  themeToggle: document.querySelector("#theme-toggle"),
  totalPapers: document.querySelector("#total-papers"),
};

const params = new URLSearchParams(window.location.search);
const state = {
  category: params.get("topic") || "all",
  days: params.get("days") || "all",
  papers: [],
  query: params.get("q") || "",
  sort: params.get("sort") || "newest",
  visible: PAGE_SIZE,
};

let meta = null;
let searchTimer = null;

function normalize(value) {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function formatDate(value, includeYear = true) {
  const options = { day: "numeric", month: "short", timeZone: "UTC" };
  if (includeYear) options.year = "numeric";
  return new Intl.DateTimeFormat("en", options).format(new Date(value));
}

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function setExternalLink(link, href, label) {
  link.href = href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.setAttribute("aria-label", `${label} (opens in a new tab)`);
}

function readTheme() {
  const saved = window.localStorage.getItem("alphaad-theme");
  return THEME_MODES.includes(saved) ? saved : "auto";
}

function applyTheme(mode) {
  document.documentElement.dataset.theme = mode;
  elements.themeLabel.textContent = mode[0].toUpperCase() + mode.slice(1);
  window.localStorage.setItem("alphaad-theme", mode);
}

function cycleTheme() {
  const current = document.documentElement.dataset.theme || "auto";
  const next = THEME_MODES[(THEME_MODES.indexOf(current) + 1) % THEME_MODES.length];
  applyTheme(next);
}

function syncControls() {
  elements.searchInput.value = state.query;
  elements.clearSearch.hidden = !state.query;
  elements.recency.value = ["all", "7", "30", "90"].includes(state.days)
    ? state.days
    : "all";
  elements.sort.value = ["newest", "oldest", "title"].includes(state.sort)
    ? state.sort
    : "newest";
  state.days = elements.recency.value;
  state.sort = elements.sort.value;
}

function updateUrl() {
  const next = new URLSearchParams();
  if (state.query) next.set("q", state.query);
  if (state.category !== "all") next.set("topic", state.category);
  if (state.days !== "all") next.set("days", state.days);
  if (state.sort !== "newest") next.set("sort", state.sort);
  const query = next.toString();
  window.history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
}

function selectCategory(category) {
  state.category = category;
  state.visible = PAGE_SIZE;
  renderCategoryFilters();
  renderResults();
}

function categoryButton(name, count) {
  const button = createElement("button", "category-chip");
  button.type = "button";
  button.dataset.category = name;
  button.setAttribute("aria-pressed", String(state.category === name));
  button.append(document.createTextNode(name === "all" ? "All topics" : name));
  const countElement = createElement("span", "chip-count", String(count));
  countElement.setAttribute("aria-hidden", "true");
  button.append(countElement);
  button.addEventListener("click", () => selectCategory(name));
  return button;
}

function renderCategoryFilters() {
  elements.categoryFilters.replaceChildren();
  elements.categoryFilters.append(categoryButton("all", meta.total_papers));
  for (const category of meta.categories) {
    elements.categoryFilters.append(categoryButton(category.name, category.count));
  }
}

function filteredPapers() {
  const query = normalize(state.query.trim());
  const terms = query.split(/\s+/).filter(Boolean);
  const maxDays = state.days === "all" ? Infinity : Number(state.days);

  const filtered = state.papers.filter((paper) => {
    if (state.category !== "all" && paper.category !== state.category) return false;
    if (paper.age_days > maxDays) return false;
    if (!terms.length) return true;

    const haystack = normalize(
      `${paper.title} ${paper.authors.join(" ")} ${paper.abstract} ${paper.category}`,
    );
    return terms.every((term) => haystack.includes(term));
  });

  filtered.sort((left, right) => {
    if (state.sort === "oldest") return left.published.localeCompare(right.published);
    if (state.sort === "title") return left.title.localeCompare(right.title);
    return right.published.localeCompare(left.published);
  });
  return filtered;
}

function recencyText(paper) {
  if (paper.recency === "archive") return "";
  const label = paper.recency === "new" ? "New" : paper.recency === "recent" ? "Recent" : "Fresh";
  return `${label} · ${paper.age_days}d`;
}

function paperCard(paper, index) {
  const article = createElement("article", "paper-card");
  article.style.animationDelay = `${Math.min(index, 12) * 28}ms`;

  const indexBlock = createElement("div", "paper-index", paper.id);
  const date = createElement("time", "paper-date", formatDate(paper.published));
  date.dateTime = paper.published;
  indexBlock.append(date);

  const main = createElement("div", "paper-main");
  const heading = createElement("h3");
  const title = createElement("a", "", paper.title);
  setExternalLink(title, paper.arxiv_url, `${paper.title} on arXiv`);
  heading.append(title);

  const authorNames = paper.authors.filter((author) => author.toLowerCase() !== "et al.");
  const authorText = authorNames.slice(0, 5).join(", ") + (authorNames.length > 5 || paper.authors.length > 5 ? ", et al." : "");
  const authors = createElement("p", "paper-authors", authorText);
  const abstractExcerpt = paper.short_abstract || paper.abstract;
  const abstract = createElement("p", "paper-abstract", abstractExcerpt);
  const abstractId = `abstract-${paper.id.replace(/[^a-z0-9]+/gi, "-")}`;
  abstract.id = abstractId;
  main.append(heading, authors, abstract);

  if (paper.abstract && paper.abstract !== abstractExcerpt) {
    const abstractToggle = createElement("button", "abstract-toggle", "Read full abstract +");
    abstractToggle.type = "button";
    abstractToggle.setAttribute("aria-controls", abstractId);
    abstractToggle.setAttribute("aria-expanded", "false");
    abstractToggle.addEventListener("click", () => {
      const expanded = abstractToggle.getAttribute("aria-expanded") === "true";
      abstractToggle.setAttribute("aria-expanded", String(!expanded));
      abstractToggle.textContent = expanded ? "Read full abstract +" : "Collapse abstract −";
      abstract.textContent = expanded ? abstractExcerpt : paper.abstract;
    });
    main.append(abstractToggle);
  }

  const aside = createElement("aside", "paper-aside", undefined);
  aside.setAttribute("aria-label", "Paper metadata and links");
  aside.append(createElement("span", "topic-label", paper.category));

  const freshness = recencyText(paper);
  if (freshness) {
    const recency = createElement("span", "recency-label", freshness);
    recency.dataset.recency = paper.recency;
    aside.append(recency);
  }

  const links = createElement("div", "paper-links");
  const arxiv = createElement("a", "", "arXiv  ↗");
  const pdf = createElement("a", "", "PDF  ↗");
  setExternalLink(arxiv, paper.arxiv_url, `Open arXiv abstract for ${paper.title}`);
  setExternalLink(pdf, paper.pdf_url, `Open PDF for ${paper.title}`);
  links.append(arxiv, pdf);
  aside.append(links);

  article.append(indexBlock, main, aside);
  return article;
}

function describeResultSet(count) {
  const parts = [];
  if (state.query) parts.push(`query “${state.query}”`);
  if (state.category !== "all") parts.push(state.category);
  if (state.days !== "all") parts.push(`last ${state.days} days`);
  const scope = parts.length ? parts.join(" · ") : "all topics · 180-day window";
  return `${count.toLocaleString("en")} results · ${scope}`;
}

function renderResults() {
  const papers = filteredPapers();
  const visible = papers.slice(0, state.visible);

  elements.paperList.replaceChildren();
  const fragment = document.createDocumentFragment();
  visible.forEach((paper, index) => fragment.append(paperCard(paper, index)));
  elements.paperList.append(fragment);
  elements.paperList.setAttribute("aria-busy", "false");

  elements.resultCount.textContent = papers.length.toLocaleString("en");
  elements.resultContext.textContent = describeResultSet(papers.length);
  elements.emptyState.hidden = papers.length !== 0;
  elements.paperList.hidden = papers.length === 0;
  elements.loadMore.hidden = papers.length <= state.visible;
  if (!elements.loadMore.hidden) {
    const remaining = Math.min(PAGE_SIZE, papers.length - state.visible);
    elements.loadMore.firstChild.textContent = `Show ${remaining} more papers `;
  }

  elements.clearSearch.hidden = !state.query;
  updateUrl();
}

function resetView() {
  state.category = "all";
  state.days = "all";
  state.query = "";
  state.sort = "newest";
  state.visible = PAGE_SIZE;
  syncControls();
  renderCategoryFilters();
  renderResults();
}

function handleSearch(value) {
  state.query = value.trimStart();
  state.visible = PAGE_SIZE;
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(renderResults, 120);
  elements.clearSearch.hidden = !state.query;
}

function bindEvents() {
  elements.searchForm.addEventListener("submit", (event) => event.preventDefault());
  elements.searchInput.addEventListener("input", (event) => handleSearch(event.target.value));
  elements.clearSearch.addEventListener("click", () => {
    state.query = "";
    elements.searchInput.value = "";
    elements.searchInput.focus();
    state.visible = PAGE_SIZE;
    renderResults();
  });
  elements.recency.addEventListener("change", (event) => {
    state.days = event.target.value;
    state.visible = PAGE_SIZE;
    renderResults();
  });
  elements.sort.addEventListener("change", (event) => {
    state.sort = event.target.value;
    state.visible = PAGE_SIZE;
    renderResults();
  });
  elements.loadMore.addEventListener("click", () => {
    state.visible += PAGE_SIZE;
    renderResults();
  });
  elements.resetFilters.addEventListener("click", resetView);
  elements.emptyReset.addEventListener("click", resetView);
  elements.themeToggle.addEventListener("click", cycleTheme);
  document.addEventListener("keydown", (event) => {
    const target = event.target;
    const isTyping = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement;
    if (event.key === "/" && !isTyping && !event.metaKey && !event.ctrlKey && !event.altKey) {
      event.preventDefault();
      elements.searchInput.focus();
    }
  });
}

function renderStats() {
  elements.totalPapers.textContent = meta.total_papers.toLocaleString("en");
  elements.newPapers.textContent = state.papers.filter((paper) => paper.age_days <= 7).length.toLocaleString("en");
  elements.lastUpdated.textContent = formatDate(meta.generated_at, false);
}

function showLoadError(error) {
  console.error(error);
  elements.paperList.setAttribute("aria-busy", "false");
  elements.paperList.replaceChildren();
  const message = createElement("div", "empty-state");
  message.append(
    createElement("p", "empty-code", "SIGNAL LOST / 503"),
    createElement("h3", "", "The research feed could not be loaded."),
    createElement("p", "", "Refresh the page or use the complete repository README while the feed reconnects."),
  );
  const repository = createElement("a", "", "Open the README →");
  repository.href = "https://github.com/alaliqing/AlphaAD#readme";
  message.append(repository);
  elements.paperList.append(message);
  elements.resultCount.textContent = "0";
  elements.resultContext.textContent = "Research data unavailable";
}

async function initialize() {
  applyTheme(readTheme());
  syncControls();
  bindEvents();

  try {
    const response = await fetch("data/papers.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`Paper feed returned ${response.status}`);
    const payload = await response.json();
    if (!payload.meta || !Array.isArray(payload.papers)) throw new Error("Paper feed is malformed");

    meta = payload.meta;
    state.papers = payload.papers;
    const categoryNames = new Set(meta.categories.map((category) => category.name));
    if (state.category !== "all" && !categoryNames.has(state.category)) state.category = "all";

    renderStats();
    renderCategoryFilters();
    renderResults();
  } catch (error) {
    showLoadError(error);
  }
}

initialize();
