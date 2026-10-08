"use strict";

const PAGE_SIZE = 24;
const THEME_MODES = ["auto", "light", "dark"];

const elements = {
  categoryFilters: document.querySelector("#category-filters"),
  clearSearch: document.querySelector("#clear-search"),
  emptyReset: document.querySelector("#empty-reset"),
  emptyState: document.querySelector("#empty-state"),
  feedStatus: document.querySelector("#feed-status"),
  feedStatusText: document.querySelector("#feed-status-text"),
  lastUpdated: document.querySelector("#last-updated"),
  loadMore: document.querySelector("#load-more"),
  newPapers: document.querySelector("#new-papers"),
  paperList: document.querySelector("#paper-list"),
  recency: document.querySelector("#recency-filter"),
  resetFilters: document.querySelector("#reset-filters"),
  retryFeed: document.querySelector("#retry-feed"),
  resultContext: document.querySelector("#result-context"),
  resultCount: document.querySelector("#result-count"),
  searchForm: document.querySelector("#search-form"),
  searchInput: document.querySelector("#search-input"),
  sort: document.querySelector("#sort-filter"),
  tag: document.querySelector("#tag-filter"),
  themeLabel: document.querySelector("#theme-label"),
  themeToggle: document.querySelector("#theme-toggle"),
  totalPapers: document.querySelector("#total-papers"),
};

const params = new URLSearchParams(window.location.search);
const state = {
  category: params.get("topic") || "all",
  days: params.get("days") || "all",
  papers: [],
  ready: false,
  query: params.get("q") || "",
  sort: params.get("sort") || "newest",
  tag: params.get("tag") || "all",
  visible: PAGE_SIZE,
};

let meta = null;
let searchTimer = null;
let loadingFeed = false;
let dataUrl = "data/papers.json";

function setFeedControls() {
  const controls = document.querySelectorAll(
    "#search-input, #clear-search, #recency-filter, #sort-filter, #tag-filter, " +
    "#category-filters button, #load-more, #reset-filters, #empty-reset, .paper-tag",
  );
  controls.forEach((control) => { control.disabled = !state.ready; });
}

function hasActiveView() {
  return Boolean(state.query.trim() || state.category !== "all" || state.days !== "all" ||
    state.tag !== "all" || state.sort !== "newest");
}

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
  elements.tag.value = state.tag;
}

function updateUrl() {
  const next = new URLSearchParams();
  if (state.query) next.set("q", state.query);
  if (state.category !== "all") next.set("topic", state.category);
  if (state.days !== "all") next.set("days", state.days);
  if (state.sort !== "newest") next.set("sort", state.sort);
  if (state.tag !== "all") next.set("tag", state.tag);
  const query = next.toString();
  window.history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
}

function selectCategory(category) {
  state.category = category;
  state.visible = PAGE_SIZE;
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
  button.disabled = !state.ready;
  return button;
}

function renderCategoryFilters(papers = state.papers) {
  const counts = new Map();
  for (const paper of papers) {
    const category = paper.primary_category || paper.category;
    counts.set(category, (counts.get(category) || 0) + 1);
  }
  const scrollLeft = elements.categoryFilters.scrollLeft;
  elements.categoryFilters.replaceChildren();
  elements.categoryFilters.append(categoryButton("all", papers.length));
  for (const category of meta.categories) {
    elements.categoryFilters.append(categoryButton(category.name, counts.get(category.name) || 0));
  }
  elements.categoryFilters.scrollLeft = scrollLeft;
}

function renderTagFilter(papers) {
  const counts = new Map();
  for (const paper of papers) {
    for (const tag of paper.tags || []) counts.set(tag, (counts.get(tag) || 0) + 1);
  }
  elements.tag.replaceChildren();
  elements.tag.append(new Option(`All research tags · ${papers.length}`, "all"));
  for (const tag of meta.tags || []) {
    elements.tag.append(new Option(`${tag.name} · ${counts.get(tag.name) || 0}`, tag.name));
  }
  elements.tag.value = state.tag;
}

function matchingPapers({ ignoreCategory = false, ignoreTag = false } = {}) {
  const query = normalize(state.query.trim());
  const terms = query.split(/\s+/).filter(Boolean);
  const maxDays = state.days === "all" ? Infinity : Number(state.days);

  return state.papers.filter((paper) => {
    const category = paper.primary_category || paper.category;
    const tags = paper.tags || [];
    if (!ignoreCategory && state.category !== "all" && category !== state.category) return false;
    if (!ignoreTag && state.tag !== "all" && !tags.includes(state.tag)) return false;
    if (paper.age_days > maxDays) return false;
    if (!terms.length) return true;

    const haystack = normalize(
      `${paper.title} ${paper.authors.join(" ")} ${paper.abstract} ${category} ${tags.join(" ")}`,
    );
    return terms.every((term) => haystack.includes(term));
  });
}

function filteredPapers() {
  const filtered = matchingPapers();
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
  article.dataset.paperId = paper.id;
  article.style.animationDelay = `${Math.min(index, 12) * 28}ms`;
  article.dataset.recency = paper.recency;

  const indexBlock = createElement("div", "paper-index", paper.id);
  const date = createElement("time", "paper-date", formatDate(paper.published));
  date.dateTime = paper.published;
  indexBlock.append(date);

  const main = createElement("div", "paper-main");
  const heading = createElement("h3");
  const title = createElement("a", "", paper.title);
  setExternalLink(title, paper.arxiv_url, `${paper.title} on arXiv`);
  const titleCue = createElement("span", "title-link-cue", "↗");
  titleCue.setAttribute("aria-hidden", "true");
  title.append(titleCue);
  heading.append(title);

  const authorNames = paper.authors.filter((author) => author.toLowerCase() !== "et al.");
  const authorText = authorNames.slice(0, 5).join(", ") + (authorNames.length > 5 || paper.authors.length > 5 ? ", et al." : "");
  const authors = createElement("p", "paper-authors", authorText);
  const tags = paper.tags || [];
  const abstractExcerpt = paper.short_abstract || paper.abstract;
  const abstract = createElement("p", "paper-abstract", abstractExcerpt);
  const abstractId = `abstract-${paper.id.replace(/[^a-z0-9]+/gi, "-")}`;
  abstract.id = abstractId;
  main.append(heading, authors);

  if (tags.length) {
    const tagList = createElement("div", "paper-tags");
    tagList.setAttribute("aria-label", "Research tags");
    for (const tag of tags) {
      const tagButton = createElement("button", "paper-tag", tag);
      tagButton.type = "button";
      tagButton.setAttribute("aria-pressed", String(state.tag === tag));
      tagList.append(tagButton);
    }
    main.append(tagList);
  }

  main.append(abstract);

  if (paper.abstract && paper.abstract !== abstractExcerpt) {
    const abstractToggle = createElement("button", "abstract-toggle", "Read full abstract +");
    abstractToggle.type = "button";
    abstractToggle.setAttribute("aria-controls", abstractId);
    abstractToggle.setAttribute("aria-expanded", "false");
    main.append(abstractToggle);
  }

  const aside = createElement("aside", "paper-aside", undefined);
  aside.setAttribute("aria-label", "Paper metadata and links");
  const primaryCategory = paper.primary_category || paper.category;
  const topic = createElement("span", "topic-label", primaryCategory);
  const classification = paper.classification;
  if (classification) {
    const evidence = (classification.evidence || []).slice(0, 3).join("; ");
    topic.title = `Automated classification · ${classification.confidence} confidence${evidence ? ` · ${evidence}` : ""}`;
  }
  aside.append(topic);

  const freshness = recencyText(paper);
  if (freshness) {
    const recency = createElement("span", "recency-label", freshness);
    recency.dataset.recency = paper.recency;
    aside.append(recency);
  }

  const links = createElement("div", "paper-links");
  const pdf = createElement("a", "", "PDF  ↗");
  setExternalLink(pdf, paper.pdf_url, `Open PDF for ${paper.title}`);
  links.append(pdf);
  aside.append(links);

  article.append(indexBlock, main, aside);
  return article;
}

function describeResultSet(count) {
  const parts = [];
  if (state.query) parts.push(`query “${state.query}”`);
  if (state.category !== "all") parts.push(state.category);
  if (state.tag !== "all") parts.push(`tag: ${state.tag}`);
  if (state.days !== "all") parts.push(`last ${state.days} days`);
  const scope = parts.length ? parts.join(" · ") : `all topics · ${meta.window_days}-day window`;
  return `${count.toLocaleString("en")} results · ${scope}`;
}

function renderResults({ preserveCards = false } = {}) {
  const papers = filteredPapers();
  const visible = papers.slice(0, state.visible);
  // Each facet counts matches for the other active filters, including recency.
  renderTagFilter(matchingPapers({ ignoreTag: true }));
  renderCategoryFilters(matchingPapers({ ignoreCategory: true }));

  const currentCards = [...elements.paperList.querySelectorAll(".paper-card")];
  const sameCards = currentCards.length === visible.length &&
    currentCards.every((card, index) => card.dataset.paperId === visible[index].id);
  if (!preserveCards || !sameCards) {
    const fragment = document.createDocumentFragment();
    visible.forEach((paper, index) => fragment.append(paperCard(paper, index)));
    elements.paperList.replaceChildren(fragment);
  }
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
  setFeedControls();
  updateUrl();
}

function resetView() {
  state.category = "all";
  state.days = "all";
  state.query = "";
  state.sort = "newest";
  state.tag = "all";
  state.visible = PAGE_SIZE;
  syncControls();
  renderResults();
  elements.categoryFilters.scrollLeft = 0;
}

function handleSearch(value) {
  state.query = value.trimStart();
  state.visible = PAGE_SIZE;
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(renderResults, 120);
  elements.clearSearch.hidden = !state.query;
}

function bindEvents() {
  elements.categoryFilters.addEventListener("click", (event) => {
    const button = event.target.closest("[data-category]");
    if (button && state.ready) selectCategory(button.dataset.category);
  });
  elements.paperList.addEventListener("click", (event) => {
    const tagButton = event.target.closest(".paper-tag");
    if (tagButton && state.ready) {
      state.tag = tagButton.textContent;
      state.visible = PAGE_SIZE;
      renderResults();
      elements.tag.focus({ preventScroll: true });
      return;
    }
    const toggle = event.target.closest(".abstract-toggle");
    if (!toggle) return;
    const card = toggle.closest(".paper-card");
    const paper = state.papers.find((item) => item.id === card.dataset.paperId);
    if (!paper) return;
    const expanded = toggle.getAttribute("aria-expanded") === "true";
    const abstract = card.querySelector(".paper-abstract");
    toggle.setAttribute("aria-expanded", String(!expanded));
    toggle.textContent = expanded ? "Read full abstract +" : "Collapse abstract −";
    abstract.textContent = expanded ? (paper.short_abstract || paper.abstract) : paper.abstract;
    abstract.classList.toggle("is-expanded", !expanded);
  });
  elements.retryFeed.addEventListener("click", () => loadFeed({ reload: true }));
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
  elements.tag.addEventListener("change", (event) => {
    state.tag = event.target.value;
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
  const recentPapers = meta.recent_papers ?? state.papers.filter((paper) => paper.age_days <= 7).length;
  elements.newPapers.textContent = recentPapers.toLocaleString("en");
  elements.lastUpdated.textContent = formatDate(meta.generated_at, false);
}

function showLoadError(error) {
  console.error(error);
  elements.paperList.setAttribute("aria-busy", "false");
  elements.feedStatus.hidden = false;
  elements.feedStatusText.textContent = "Search and filters could not be loaded. You can still read the latest papers below.";
  elements.retryFeed.hidden = false;
  if (hasActiveView()) {
    elements.feedStatusText.textContent = "Matching papers could not be loaded. Retry or browse the complete repository README.";
  }
}

async function loadFeed({ reload = false } = {}) {
  if (loadingFeed || state.ready) return;
  loadingFeed = true;
  elements.retryFeed.hidden = true;
  elements.feedStatusText.textContent = "Preparing search and filters…";
  try {
    // Reuse fresh HTTP cache entries and let the server validate expired data.
    const response = await fetch(dataUrl, reload ? { cache: "reload" } : undefined);
    if (!response.ok) throw new Error(`Paper feed returned ${response.status}`);
    const payload = await response.json();
    if (!payload.meta || !Array.isArray(payload.papers) ||
        !Array.isArray(payload.meta.categories) || !Array.isArray(payload.meta.tags || []) ||
        payload.meta.total_papers !== payload.papers.length) {
      throw new Error("Paper feed is malformed");
    }

    const sameSnapshot = meta?.generated_at === payload.meta.generated_at;
    meta = payload.meta;
    state.papers = payload.papers;
    state.ready = true;
    validateView();
    syncControls();
    renderStats();
    renderResults({ preserveCards: sameSnapshot && !hasActiveView() });
    elements.feedStatus.hidden = true;
  } catch (error) {
    state.ready = false;
    setFeedControls();
    showLoadError(error);
  } finally {
    loadingFeed = false;
  }
}

function validateView() {
  const categoryNames = new Set(meta.categories.map((category) => category.name));
  if (state.category !== "all" && !categoryNames.has(state.category)) state.category = "all";
  const tagNames = new Set((meta.tags || []).map((tag) => tag.name));
  if (state.tag !== "all" && !tagNames.has(state.tag)) state.tag = "all";
}

function initialize() {
  // Older cached HTML can load the current script during a deployment.
  if (!elements.feedStatus) {
    elements.feedStatus = createElement("div", "feed-status");
    elements.feedStatusText = createElement("span", "", "Preparing search and filters…");
    elements.retryFeed = createElement("button", "text-button", "Retry");
    elements.retryFeed.type = "button";
    elements.retryFeed.hidden = true;
    elements.feedStatus.append(elements.feedStatusText, elements.retryFeed);
    elements.paperList.before(elements.feedStatus);
  }
  applyTheme(readTheme());
  const initialData = document.querySelector("#initial-data");
  if (initialData) {
    const payload = JSON.parse(initialData.textContent);
    meta = payload.meta;
    state.papers = payload.papers;
    dataUrl = payload.data_url;
    state.ready = state.papers.length === meta.total_papers;
    validateView();
  }
  syncControls();
  bindEvents();
  setFeedControls();
  if (state.ready) {
    renderStats();
    renderResults({ preserveCards: !hasActiveView() });
    elements.feedStatus.hidden = true;
    return;
  }
  if (hasActiveView()) {
    elements.paperList.hidden = true;
    elements.paperList.setAttribute("aria-busy", "true");
    elements.loadMore.hidden = true;
    elements.resultCount.textContent = "—";
    elements.resultContext.textContent = "Loading matching papers…";
  }
  // Give the static first page a paint before downloading the complete feed.
  window.requestAnimationFrame(() => window.setTimeout(loadFeed, 0));
}

initialize();
