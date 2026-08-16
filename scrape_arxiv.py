#!/usr/bin/env python3
"""
ArXiv Autonomous Driving Papers Scraper
Fetches and categorizes recent autonomous driving research papers from arXiv.
"""

import sys
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Dict
import time
import re
import random
import html as html_module


# A real-looking UA helps avoid silent blocking on the HTML endpoint.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# arxiv.org/search/ uses fixed page size of 50.
HTML_PAGE_SIZE = 50

# Cap pagination per keyword. 10 pages * 50 = 500 papers, well above the
# previous API max_results=200 and enough to cover any 180-day window.
HTML_MAX_PAGES = 10

REPOSITORY_URL = "https://github.com/alaliqing/AlphaAD"
PAGES_URL = "https://alaliqing.github.io/AlphaAD/"
DATA_WINDOW_DAYS = 180
CATEGORY_ORDER = [
    "Perception",
    "Planning",
    "Prediction",
    "End-to-End Learning",
    "Mapping & Localization",
    "Control",
    "Safety & Verification",
    "Dataset & Benchmark",
    "Simulation",
    "General",
]


class ArXivPaper:
    """Represents a single arXiv paper."""

    def __init__(self, title: str, authors: List[str], abstract: str,
                 arxiv_id: str, published: str, updated: str):
        self.title = title.strip()
        self.authors = authors
        self.abstract = abstract.strip()
        self.arxiv_id = arxiv_id
        self.published = published
        self.updated = updated
        self.category = self._categorize()

    def _categorize(self) -> str:
        """Categorize paper based on title and abstract."""
        text = (self.title + " " + self.abstract).lower()

        # Define keywords for each category
        categories = {
            "Perception": ["detection", "segmentation", "tracking", "object detection",
                          "semantic segmentation", "lidar", "radar", "sensor fusion",
                          "3d detection", "point cloud", "camera", "vision"],
            "Planning": ["path planning", "motion planning", "trajectory", "navigation",
                        "route planning", "behavior planning", "decision making"],
            "Control": ["control", "steering", "acceleration", "vehicle dynamics",
                       "model predictive control", "mpc", "pid", "lateral control"],
            "Prediction": ["prediction", "trajectory prediction", "intent prediction",
                          "forecasting", "future trajectory"],
            "Simulation": ["simulation", "simulator", "carla", "lgsvl", "synthetic data",
                          "virtual environment"],
            "End-to-End Learning": ["end-to-end", "imitation learning", "behavior cloning",
                                   "reinforcement learning", "deep learning"],
            "Mapping & Localization": ["mapping", "localization", "slam", "hd map",
                                      "visual odometry", "pose estimation"],
            "Safety & Verification": ["safety", "verification", "robust", "adversarial",
                                     "testing", "validation", "certification"],
            "Dataset & Benchmark": ["dataset", "benchmark", "data collection", "annotation"],
        }

        # Score each category
        scores = {}
        for category, keywords in categories.items():
            score = sum(1 for keyword in keywords if keyword in text)
            if score > 0:
                scores[category] = score

        # Return category with highest score, or "General" if no match
        if scores:
            return max(scores.items(), key=lambda x: x[1])[0]
        return "General"

    def get_arxiv_url(self) -> str:
        """Get the arXiv URL for this paper."""
        return f"https://arxiv.org/abs/{self.arxiv_id}"

    def get_pdf_url(self) -> str:
        """Get the PDF URL for this paper."""
        return f"https://arxiv.org/pdf/{self.arxiv_id}.pdf"

    def get_short_abstract(self, length: int = 200) -> str:
        """Get truncated abstract."""
        if len(self.abstract) <= length:
            return self.abstract
        return self.abstract[:length].rsplit(' ', 1)[0] + "..."

    def get_recency_badge(self) -> str:
        """Get the visual recency badge shown beside README paper titles."""
        days_old = self.get_age_days()
        if days_old <= 7:
            return "![New](https://img.shields.io/badge/New-red)"
        if days_old <= 30:
            return "![Recent](https://img.shields.io/badge/Recent-orange)"
        if days_old <= 90:
            return "![Fresh](https://img.shields.io/badge/Fresh-yellow)"
        return ""

    def get_age_days(self) -> int:
        """Return the paper age in whole days, clamped at zero."""
        published_date = datetime.strptime(self.published, "%Y-%m-%dT%H:%M:%SZ")
        return max(0, (datetime.now() - published_date).days)

    def get_recency_label(self) -> str:
        """Return a short text label that does not rely on color alone."""
        days_old = self.get_age_days()
        if days_old <= 7:
            return f"NEW · {days_old}d"
        elif days_old <= 30:
            return f"RECENT · {days_old}d"
        elif days_old <= 90:
            return f"FRESH · {days_old}d"
        return ""


class ArXivScraper:
    """Scrapes papers from arXiv API."""

    BASE_URL = "https://export.arxiv.org/api/query?"

    def __init__(self, max_results: int = 200):
        self.max_results = max_results
        self.papers: List[ArXivPaper] = []

    def fetch_papers(self, keywords: List[str], days_back: int = 180):
        """Fetch papers matching keywords from the last N days.

        Strategy: HTML search (arxiv.org/search/) is the primary path because
        the /api/query endpoint is frequently rate-limited at the IP level,
        especially from cloud / CI runner ranges. The API is kept as a
        per-keyword fallback for when HTML parsing produces no results.
        """
        print(f"Fetching papers from the last {days_back} days...")

        for idx, keyword in enumerate(keywords):
            print(f"Searching for: {keyword}")

            papers = self._query_arxiv_html(keyword, days_back)
            if not papers:
                print(f"  HTML returned 0 papers for '{keyword}', "
                      f"falling back to API...")
                papers = self._query_arxiv(keyword, days_back)

            print(f"  Got {len(papers)} papers for '{keyword}'")
            self.papers.extend(papers)

            if idx < len(keywords) - 1:
                delay = random.uniform(5, 10)
                print(f"Sleeping {delay:.1f}s before next keyword...")
                time.sleep(delay)

        # Remove duplicates based on arxiv_id
        seen = set()
        unique_papers = []
        for paper in self.papers:
            if paper.arxiv_id not in seen:
                seen.add(paper.arxiv_id)
                unique_papers.append(paper)

        self.papers = unique_papers
        print(f"Found {len(self.papers)} unique papers")

    def _query_arxiv_html(self, keyword: str, days_back: int) -> List[ArXivPaper]:
        """Query arxiv.org/search/ HTML endpoint, paginating until results
        fall outside the date window or the page cap is reached.

        Returns paper objects within the last `days_back` days. Stops early
        when a page's oldest result is older than the cutoff (results are
        sorted by submittedDate descending by default).
        """
        cutoff = datetime.now() - timedelta(days=days_back)
        all_papers: List[ArXivPaper] = []

        for page in range(HTML_MAX_PAGES):
            start = page * HTML_PAGE_SIZE
            params = {
                "searchtype": "all",
                "query": f'"{keyword}"',  # phrase search, matches all:"..." API behaviour
                "start": start,
            }
            url = "https://arxiv.org/search/?" + urllib.parse.urlencode(params)

            html_text = self._fetch_with_retry(url, label=f"HTML '{keyword}' p{page + 1}")
            if html_text is None:
                # Fail this page; if first page, caller will fall back to API.
                break

            page_papers, oldest_date = self._parse_search_html(html_text, cutoff)
            all_papers.extend(page_papers)

            # Early break: page is non-empty but its oldest paper is already
            # past the cutoff -> all remaining pages will be older.
            if oldest_date is not None and oldest_date < cutoff:
                break

            # If page yielded fewer than a full page of *parsed* results, end.
            # (Trailing pages of search results often have <50 items.)
            if not page_papers:
                break

            # Be polite between pages even though no rate limit observed.
            time.sleep(random.uniform(1.5, 3.0))

        return all_papers

    def _fetch_with_retry(self, url: str, label: str) -> str:
        """GET url with retry/backoff. Returns body text or None on failure."""
        max_retries = 4
        base_delay = 8

        for attempt in range(max_retries):
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xml;q=0.9,*/*;q=0.8",
                })
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:
                if (e.code == 429 or 500 <= e.code < 600) and attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 5)
                    print(f"  {label}: HTTP {e.code}, sleeping {delay:.1f}s "
                          f"(retry {attempt + 2}/{max_retries})...")
                    time.sleep(delay)
                    continue
                print(f"  {label}: HTTP {e.code} - {e.reason}")
                return None
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 5)
                    print(f"  {label}: network error ({e}), sleeping {delay:.1f}s "
                          f"(retry {attempt + 2}/{max_retries})...")
                    time.sleep(delay)
                    continue
                print(f"  {label}: network error - {e}")
                return None
            except Exception as e:
                print(f"  {label}: unexpected error - {e}")
                return None
        return None

    @staticmethod
    def _strip_tags(s: str) -> str:
        """Remove HTML tags and decode entities, collapse whitespace."""
        s = re.sub(r"<[^>]+>", "", s)
        s = html_module.unescape(s)
        return re.sub(r"\s+", " ", s).strip()

    def _parse_search_html(self, html: str, cutoff: datetime):
        """Parse one search results page into ArXivPaper objects within cutoff.

        Returns (papers_in_window, oldest_seen_date). oldest_seen_date is the
        oldest paper date observed on this page regardless of window — used
        by the caller to decide whether to stop pagination.
        """
        # Each result is a <li class="arxiv-result"> ... </li> block.
        blocks = re.findall(
            r'<li class="arxiv-result">(.*?)</li>\s*(?=<li class="arxiv-result">|</ol>)',
            html,
            re.DOTALL,
        )
        papers: List[ArXivPaper] = []
        oldest_seen: datetime = None

        for block in blocks:
            # arXiv ID
            m = re.search(r'/abs/(\d{4}\.\d{4,5})', block)
            if not m:
                continue
            arxiv_id = m.group(1)

            # Title
            m = re.search(
                r'<p class="title is-5 mathjax">(.*?)</p>', block, re.DOTALL
            )
            if not m:
                continue
            title = self._strip_tags(m.group(1))

            # Authors
            m = re.search(r'<p class="authors">(.*?)</p>', block, re.DOTALL)
            authors: List[str] = []
            if m:
                authors = [
                    self._strip_tags(a)
                    for a in re.findall(
                        r'<a [^>]*>(.*?)</a>', m.group(1), re.DOTALL
                    )
                ]

            # Abstract: prefer abstract-full, fall back to abstract-short
            abstract = ""
            m = re.search(
                r'<span class="abstract-full[^"]*"[^>]*>(.*?)</span>',
                block,
                re.DOTALL,
            )
            if m:
                # Strip the trailing "△ Less" link before stripping all tags.
                abs_html = re.sub(r'<a [^>]*>.*?</a>', '', m.group(1), flags=re.DOTALL)
                abstract = self._strip_tags(abs_html)
            else:
                m = re.search(
                    r'<span class="abstract-short[^"]*"[^>]*>(.*?)</span>',
                    block,
                    re.DOTALL,
                )
                if m:
                    abs_html = re.sub(r'<a [^>]*>.*?</a>', '', m.group(1), flags=re.DOTALL)
                    abstract = self._strip_tags(abs_html).rstrip("…").rstrip()

            # Submission date. Date paragraph contains:
            #   "Submitted 4 June, 2026; ... originally announced June 2026."
            # For revised papers there can be multiple "Submitted" lines; the
            # LAST one is the v1/original submission, which matches the API's
            # <published> field.
            date_para = re.search(
                r'<p class="is-size-7">(.*?)</p>', block, re.DOTALL
            )
            if not date_para:
                continue
            date_text = self._strip_tags(date_para.group(1))
            date_matches = re.findall(
                r'(\d{1,2})\s+(January|February|March|April|May|June|July|'
                r'August|September|October|November|December),?\s+(\d{4})',
                date_text,
            )
            if not date_matches:
                continue
            day, month_name, year = date_matches[-1]  # original (v1) submission
            try:
                published_dt = datetime.strptime(
                    f"{day} {month_name} {year}", "%d %B %Y"
                )
            except ValueError:
                continue

            if oldest_seen is None or published_dt < oldest_seen:
                oldest_seen = published_dt

            if published_dt < cutoff:
                continue

            published_iso = published_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            papers.append(
                ArXivPaper(
                    title=title,
                    authors=authors,
                    abstract=abstract,
                    arxiv_id=arxiv_id,
                    published=published_iso,
                    updated=published_iso,
                )
            )

        return papers, oldest_seen

    def _query_arxiv(self, keyword: str, days_back: int) -> List[ArXivPaper]:
        """Query arXiv API for a specific keyword with retry logic."""
        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)

        # Build query
        search_query = f'all:"{keyword}"'
        params = {
            'search_query': search_query,
            'start': 0,
            'max_results': self.max_results,
            'sortBy': 'submittedDate',
            'sortOrder': 'descending'
        }

        url = self.BASE_URL + urllib.parse.urlencode(params)

        # Retry logic with exponential backoff. Start at 15s because arXiv's
        # rate limiter often holds for ~10s after a 429.
        max_retries = 5
        base_delay = 15

        for attempt in range(max_retries):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=60) as response:
                    data = response.read()

                # Parse XML
                root = ET.fromstring(data)
                ns = {'atom': 'http://www.w3.org/2005/Atom'}

                papers = []
                for entry in root.findall('atom:entry', ns):
                    # Extract data
                    title = entry.find('atom:title', ns).text.replace('\n', ' ')

                    authors = [author.find('atom:name', ns).text
                              for author in entry.findall('atom:author', ns)]

                    abstract = entry.find('atom:summary', ns).text.replace('\n', ' ')

                    arxiv_id = entry.find('atom:id', ns).text.split('/abs/')[-1]

                    published = entry.find('atom:published', ns).text
                    updated = entry.find('atom:updated', ns).text

                    # Filter by date
                    published_date = datetime.strptime(published, "%Y-%m-%dT%H:%M:%SZ")
                    if published_date >= start_date:
                        paper = ArXivPaper(title, authors, abstract, arxiv_id,
                                          published, updated)
                        papers.append(paper)

                return papers

            except urllib.error.HTTPError as e:
                # Retry on rate limiting (429) and transient server errors (5xx).
                if e.code == 429 or 500 <= e.code < 600:
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt) + random.uniform(0, 5)
                        print(f"HTTP {e.code}, waiting {delay:.1f}s before retry "
                              f"(attempt {attempt + 2}/{max_retries})...")
                        time.sleep(delay)
                        continue
                    else:
                        print(f"Error querying arXiv for '{keyword}': "
                              f"HTTP {e.code} after {max_retries} attempts")
                        return []
                else:
                    print(f"Error querying arXiv for '{keyword}': HTTP {e.code} - {e.reason}")
                    return []

            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 5)
                    print(f"Network error ({e}), waiting {delay:.1f}s before retry "
                          f"(attempt {attempt + 2}/{max_retries})...")
                    time.sleep(delay)
                    continue
                print(f"Error querying arXiv for '{keyword}': {e}")
                return []

            except Exception as e:
                print(f"Error querying arXiv for '{keyword}': {e}")
                return []

        return []

    def categorize_papers(self) -> Dict[str, List[ArXivPaper]]:
        """Group papers by category."""
        categories = {}
        for paper in self.papers:
            if paper.category not in categories:
                categories[paper.category] = []
            categories[paper.category].append(paper)

        # Sort papers within each category by date (newest first)
        for category in categories:
            categories[category].sort(
                key=lambda p: p.published,
                reverse=True
            )

        return categories

    @staticmethod
    def _category_slug(category: str) -> str:
        """Build a stable category anchor shared by README navigation."""
        return re.sub(r"[^a-z0-9]+", "-", category.lower()).strip("-")

    @staticmethod
    def _paper_anchor(paper: ArXivPaper) -> str:
        """Build a stable README anchor from the arXiv identifier."""
        suffix = re.sub(r"[^a-z0-9]+", "-", paper.arxiv_id.lower()).strip("-")
        return f"paper-{suffix}"

    @staticmethod
    def _markdown_text(value: str) -> str:
        """Keep generated table and link text on one safe Markdown line."""
        return re.sub(r"\s+", " ", value).strip().replace("|", "\\|")

    @staticmethod
    def _ordered_categories(categories: Dict[str, List[ArXivPaper]]):
        """Return product-oriented categories followed by future additions."""
        ordered = [
            (category, categories[category])
            for category in CATEGORY_ORDER
            if category in categories
        ]
        known = set(CATEGORY_ORDER)
        ordered.extend(
            (category, categories[category])
            for category in sorted(categories)
            if category not in known
        )
        return ordered

    @staticmethod
    def _write_text_atomic(path: Path, content: str):
        """Write generated output without exposing a partial file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(path.name + ".tmp")
        temporary_path.write_text(content, encoding="utf-8")
        temporary_path.replace(path)

    def build_readme(self) -> str:
        """Build the complete GitHub-native research index."""
        categories = self.categorize_papers()
        ordered_categories = self._ordered_categories(categories)
        content = self._build_readme_header()
        content += self._build_category_navigation(ordered_categories)
        for category, papers in ordered_categories:
            content += self._build_category_section(category, papers)
        return content + self._build_footer()

    def build_data_payload(self) -> Dict[str, Any]:
        """Build the structured data consumed by GitHub Pages."""
        categories = self.categorize_papers()
        ordered_categories = self._ordered_categories(categories)
        papers = sorted(self.papers, key=lambda paper: paper.published, reverse=True)
        generated_at = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z")
        return {
            "meta": {
                "generated_at": generated_at,
                "window_days": DATA_WINDOW_DAYS,
                "total_papers": len(papers),
                "repository_url": REPOSITORY_URL,
                "categories": [
                    {
                        "name": category,
                        "slug": self._category_slug(category),
                        "count": len(category_papers),
                        "latest_published": category_papers[0].published[:10],
                    }
                    for category, category_papers in ordered_categories
                ],
            },
            "papers": [self._paper_record(paper) for paper in papers],
        }

    def _paper_record(self, paper: ArXivPaper) -> Dict[str, Any]:
        """Serialize one paper for search, filtering, and rendering."""
        days_old = paper.get_age_days()
        if days_old <= 7:
            recency = "new"
        elif days_old <= 30:
            recency = "recent"
        elif days_old <= 90:
            recency = "fresh"
        else:
            recency = "archive"
        return {
            "id": paper.arxiv_id,
            "anchor": self._paper_anchor(paper),
            "title": paper.title,
            "authors": paper.authors,
            "abstract": paper.abstract,
            "short_abstract": paper.get_short_abstract(260),
            "published": paper.published[:10],
            "updated": paper.updated[:10],
            "category": paper.category,
            "recency": recency,
            "age_days": days_old,
            "arxiv_url": paper.get_arxiv_url(),
            "pdf_url": paper.get_pdf_url(),
        }

    def generate_outputs(
        self,
        readme_path: str = "README.md",
        data_path: str = "site/data/papers.json",
    ):
        """Generate README and Pages data from the same collection."""
        data_content = json.dumps(
            self.build_data_payload(), ensure_ascii=False, indent=2
        ) + "\n"
        self._write_text_atomic(Path(readme_path), self.build_readme())
        self._write_text_atomic(Path(data_path), data_content)
        print(f"Generated {readme_path}")
        print(f"Generated {data_path}")

    def generate_readme(self):
        """Backward-compatible wrapper for README-only callers."""
        self._write_text_atomic(Path("README.md"), self.build_readme())
        print("README.md generated successfully!")

    def _build_readme_header(self) -> str:
        """Build the README header."""
        return f"""<div align="center">

# 🚗 AlphaAD · Autonomous Driving Research

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Last Update](https://img.shields.io/badge/Last%20Updated-{datetime.now().strftime('%Y--%m--%d')}-blue)
![Total Papers](https://img.shields.io/badge/Papers-{len(self.papers)}-green)
![Auto Update](https://img.shields.io/badge/Auto--Update-Daily-brightgreen)

**A daily research signal for autonomous driving.**<br>
Discover, scan, and open the latest arXiv papers from a rolling {DATA_WINDOW_DAYS}-day window.

<p><a href="{PAGES_URL}"><strong>Explore the interactive research index →</strong></a></p>

[Browse by topic](#browse-by-topic) · [How it works](#how-it-works)

</div>

"""

    def _build_category_navigation(self, ordered_categories) -> str:
        """Combine statistics and navigation into one useful section."""
        content = "<a id=\"browse-by-topic\"></a>\n\n## Browse by topic\n\n"
        content += (
            f"All {len(self.papers)} papers remain in this README. For full-text search, "
            f"filters, and sorting, use the [interactive index]({PAGES_URL}).\n\n"
        )
        content += "| Topic | Papers | Latest | Jump |\n|:--|--:|:--|:--|\n"
        for category, papers in ordered_categories:
            content += (
                f"| {category} | {len(papers)} | {papers[0].published[:10]} | "
                f"[View papers](#category-{self._category_slug(category)}) |\n"
            )
        return content + "\n---\n\n"

    def _build_category_section(self, category: str, papers: List[ArXivPaper]) -> str:
        """Build a complete category section with compact paper entries."""
        slug = self._category_slug(category)
        content = f"<a id=\"category-{slug}\"></a>\n\n## {category} · {len(papers)} papers\n\n"
        for paper in papers:
            badge = paper.get_recency_badge()
            badge_str = f" {badge}" if badge else ""
            title = self._markdown_text(paper.title)
            authors_str = ", ".join(paper.authors[:5])
            if len(paper.authors) > 5:
                authors_str += ", et al."
            content += f"<a id=\"{self._paper_anchor(paper)}\"></a>\n\n"
            content += f"### {title}{badge_str}\n\n"
            content += f"**Authors:** {authors_str}<br>\n"
            content += f"**Published:** {paper.published[:10]}<br>\n"
            content += (
                f"**Links:** [arXiv abstract]({paper.get_arxiv_url()}) | "
                f"[PDF]({paper.get_pdf_url()}) | [↑ BackToTop](#browse-by-topic)\n\n"
            )
            content += f"**Abstract:** {paper.get_short_abstract()}\n\n"
        return content + "---\n\n"

    def _build_footer(self) -> str:
        """Build concise, accurate project notes."""
        return f"""<a id="how-it-works"></a>

## Project notes

<details>
<summary><strong>How it works</strong></summary>

- Searches arXiv's HTML results first and uses the arXiv API as a fallback.
- Deduplicates papers by arXiv ID and groups them with keyword-based categorization.
- Generates this README and the [GitHub Pages dataset](site/data/papers.json) from the same records.
- Runs daily at 00:00 UTC through GitHub Actions.

</details>

<details>
<summary><strong>Run locally</strong></summary>

```bash
git clone {REPOSITORY_URL}.git
cd AlphaAD
python3 scrape_arxiv.py
```

**Requirements**: Python 3.11 or higher

</details>

<details>
<summary><strong>Contributing and feedback</strong></summary>

- Improve categorization or report an incorrect topic through [Issues]({REPOSITORY_URL}/issues).
- Propose product and data improvements through [Discussions]({REPOSITORY_URL}/discussions).
- Fork the repository, create a focused branch, and open a pull request.

</details>

## Data quality

Collection and categorization are automated. A paper can match the search terms without being
primarily about road vehicles, and keyword-based topic assignment can be imperfect. Treat this
project as a discovery index and verify important details on arXiv.

<div align="center">

**⭐ If you find this repository helpful, consider giving it a star!**

[Interactive index]({PAGES_URL}) · [MIT License](LICENSE) · [Report an issue]({REPOSITORY_URL}/issues)

</div>
"""


def main():
    """Main function to run the scraper."""
    # Keywords to search for
    keywords = [
        "autonomous driving",
        "self-driving",
        "autonomous vehicles"
    ]

    # Create scraper and fetch papers from the configured rolling window
    scraper = ArXivScraper(max_results=200)
    scraper.fetch_papers(keywords, days_back=DATA_WINDOW_DAYS)

    # Safeguard: never overwrite README with an empty result set.
    # Exiting non-zero makes the GitHub Action fail loudly and keeps
    # the existing README intact.
    if not scraper.papers:
        print("ERROR: No papers fetched. Aborting to preserve existing README.",
              file=sys.stderr)
        sys.exit(1)

    # Generate the GitHub README and the shared Pages dataset together.
    scraper.generate_outputs()

    print("Done!")


if __name__ == "__main__":
    main()
