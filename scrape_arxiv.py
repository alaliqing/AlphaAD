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
from typing import Any, Dict, List, Tuple
import time
import re
import random
import html as html_module
from html.parser import HTMLParser


# A real-looking UA helps avoid silent blocking on the HTML endpoint.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# arxiv.org/search/ supports up to 200 results per page. Using the largest
# page size keeps the daily job well below arXiv's request-rate limits.
HTML_PAGE_SIZE = 200

# Cap pagination per keyword. 5 pages * 200 = 1,000 papers, twice the previous
# ceiling while still requiring at most half as many requests.
HTML_MAX_PAGES = 5

# A daily rolling window should not lose a large share of its records at once.
# This guard prevents a superficially successful partial refresh from replacing
# the last complete published dataset.
MIN_COLLECTION_RETENTION_RATIO = 0.8

REPOSITORY_URL = "https://github.com/alaliqing/AlphaAD"
PAGES_URL = "https://alaliqing.github.io/AlphaAD/"
DATA_WINDOW_DAYS = 180
SEARCH_KEYWORDS = [
    "autonomous driving",
    "self-driving",
    "autonomous vehicles",
    "automated driving",
    "driverless vehicles",
    "connected and automated vehicles",
]
CATEGORY_ORDER = [
    "Perception & Sensor Fusion",
    "Prediction & World Models",
    "Planning & Decision-Making",
    "Control & Vehicle Dynamics",
    "Mapping & Localization",
    "End-to-End & VLA",
    "Safety, Security & Verification",
    "Systems, Deployment & Connectivity",
    "Human Factors & Policy",
    "Cross-cutting / Other",
]

# Topic rules deliberately use word/phrase boundaries. Each tuple contains a
# human-readable signal, a regular expression, and its base weight. A title hit
# is worth three times an abstract hit so a passing mention cannot dominate the
# paper's stated subject.
CATEGORY_RULES = {
    "Perception & Sensor Fusion": [
        ("perception", r"\bperception\b", 3),
        ("object detection", r"\b(?:2d|3d)?\s*object detection\b", 4),
        ("scene segmentation", r"\b(?:semantic|instance|panoptic) segmentation\b", 4),
        ("occupancy", r"\boccupancy\b", 2),
        ("sensor fusion", r"\bsensor fusion\b", 4),
        ("point cloud", r"\bpoint clouds?\b", 3),
        ("LiDAR", r"\blidar\b", 3),
        ("radar", r"\bradar\b", 3),
        ("camera", r"\bcameras?\b", 2),
        ("depth estimation", r"\bdepth estimation\b", 3),
        ("lane detection", r"\blane detection\b", 3),
        ("traffic sign recognition", r"\btraffic sign (?:detection|recognition)\b", 3),
        ("scene understanding", r"\bscene understanding\b", 3),
        ("bird's-eye view", r"\bbird.?s.?eye view\b|\bbev\b", 2),
    ],
    "Prediction & World Models": [
        ("trajectory prediction", r"\btrajectory prediction\b", 5),
        ("motion forecasting", r"\bmotion (?:prediction|forecasting)\b", 5),
        ("behavior prediction", r"\bbehavior prediction\b|\bintent(?:ion)? prediction\b", 4),
        ("forecasting", r"\bforecasting\b", 3),
        ("world model", r"\bworld (?:action )?models?\b", 4),
        ("future-frame prediction", r"\bfuture[- ]frame\b", 4),
        ("future prediction", r"\bfuture prediction\b", 3),
        ("scene prediction", r"\bscene prediction\b", 3),
        ("predictive dynamics", r"\bpredictive dynamics\b", 3),
        ("prediction", r"\bprediction\b", 2),
    ],
    "Planning & Decision-Making": [
        ("motion planning", r"\bmotion planning\b|\bpath planning\b|\btrajectory planning\b", 5),
        ("planning", r"\bplanning\b", 3),
        ("decision-making", r"\bdecision[- ]making\b|\bdriving decisions?\b", 4),
        ("behavior planning", r"\bbehavior planning\b", 5),
        ("trajectory generation", r"\btrajectory generation\b", 3),
        ("navigation", r"\bnavigation\b", 2),
        ("route planning", r"\broute planning\b", 4),
        ("path generation", r"\bpath generation\b", 3),
    ],
    "Control & Vehicle Dynamics": [
        ("model predictive control", r"\bmodel predictive control\b|\bmpc\b", 5),
        ("vehicle dynamics", r"\bvehicle dynamics\b", 5),
        ("vehicle control", r"\b(?:lateral|longitudinal|vehicle|steering) control\b", 4),
        ("controller", r"\bcontrollers?\b", 3),
        ("control", r"\bcontrol(?:ling)?\b", 2),
        ("steering or braking", r"\bsteering\b|\bbraking\b|\bacceleration\b", 2),
        ("trajectory tracking", r"\btrajectory tracking\b|\bpath following\b", 4),
    ],
    "Mapping & Localization": [
        ("localization", r"\blocali[sz]ation\b", 5),
        ("HD map", r"\b(?:hd|high[- ]definition) maps?\b", 5),
        ("SLAM", r"\bslam\b", 6),
        ("visual odometry", r"\bvisual odometry\b", 6),
        ("mapping", r"\bmap construction\b|\bmapping\b", 4),
        ("place recognition", r"\bplace recognition\b", 4),
        ("pose estimation", r"\bpose estimation\b", 4),
        ("GNSS or GPS", r"\bgnss\b|\bgps\b", 2),
    ],
    "End-to-End & VLA": [
        ("end-to-end driving", r"\bend[- ]to[- ]end (?:autonomous )?driving\b|\be2e[- ]ad\b", 6),
        ("vision-language-action", r"\bvision[- ]language[- ]action\b|\bvla\b", 6),
        ("driving foundation model", r"\bdriving foundation models?\b|\blarge driving models?\b", 5),
        ("unified driving", r"\bunified driving\b", 3),
        ("end-to-end", r"\bend[- ]to[- ]end\b", 3),
        ("driving policy", r"\bdriving policy\b", 2),
    ],
    "Safety, Security & Verification": [
        ("safety", r"\bsafety\b|\bsafe driving\b", 4),
        ("security", r"\bsecurity\b|\bcybersecurity\b", 5),
        ("verification", r"\bformal verification\b|\bverification\b", 5),
        ("validation or testing", r"\bvalidation\b|\btesting\b", 3),
        ("attack or threat", r"\badversarial\b|\battacks?\b|\bthreats?\b|\bspoofing\b", 4),
        ("SOTIF", r"\bsotif\b", 6),
        ("risk assessment", r"\brisk assessment\b|\brisk-aware\b", 4),
        ("robustness", r"\brobust(?:ness)?\b", 2),
        ("uncertainty", r"\buncertaint(?:y|ies)\b", 2),
        ("failure", r"\bfail(?:ure|ures|safe)\b", 2),
    ],
    "Systems, Deployment & Connectivity": [
        ("V2X", r"\bv2x\b|\bvehicle[- ]to[- ](?:vehicle|everything|infrastructure)\b", 6),
        ("cooperative systems", r"\bcooperative\b|\bcollaborative\b", 3),
        ("connected vehicles", r"\bconnected (?:and )?(?:autonomous|automated)? ?vehicles?\b", 4),
        ("teleoperation", r"\bteleoperation\b|\bteleoperated\b", 5),
        ("deployment or real-time", r"\bdeployment\b|\breal[- ]time\b", 3),
        ("hardware", r"\bhardware\b|\baccelerators?\b", 3),
        ("edge or cloud", r"\bedge computing\b|\bcloud[- ]assisted\b", 4),
        ("communications", r"\bcommunication\b|\bconnectivity\b|\bnetwork(?:s|ing)?\b", 2),
        ("software architecture", r"\bsystem architecture\b|\bsoftware stacks?\b|\bautoware\b", 4),
        ("systems constraints", r"\blatenc(?:y|ies)\b|\bbandwidth\b|\bscheduling\b", 2),
        ("roadside infrastructure", r"\binfrastructure[- ]assisted\b|\broadside\b", 3),
    ],
    "Human Factors & Policy": [
        ("human factors", r"\bhuman factors?\b", 6),
        ("driver monitoring", r"\bdriver monitoring\b|\bdriver behavior\b|\bdriver state\b", 5),
        ("human-machine interaction", r"\bhuman[- ]in[- ]the[- ]loop\b|\bhuman[- ]machine\b", 5),
        ("takeover", r"\btakeover\b|\btake-over\b", 5),
        ("ethics", r"\bethics?\b|\bethical\b", 4),
        ("law or policy", r"\btraffic laws?\b|\bregulations?\b|\bpolicy\b|\blegal\b|\blawful\b", 4),
        ("social acceptance", r"\bsocial acceptance\b|\bpublic trust\b", 4),
        ("explainability", r"\bexplainab(?:ility|le)\b", 3),
        ("human driver", r"\bhuman drivers?\b", 3),
    ],
}

TAG_RULES = {
    # Resource tags require title evidence or explicit contribution language in
    # the abstract; merely evaluating on a dataset or benchmark is not enough.
    "Dataset": (
        r"\bdatasets?\b|\bcorpus\b|\bdata collection\b",
        r"\b(?:introduc|present|releas|build|construct|collect|curat|provid)\w*\b.{0,80}\bdatasets?\b",
    ),
    "Benchmark": (
        r"\bbenchmarks?\b|\bleaderboards?\b",
        r"\b(?:introduc|present|releas|build|establish|propos)\w*\b.{0,80}\bbenchmarks?\b",
    ),
    "Simulation": (
        r"\bsimulat(?:ion|or|ors)\b|\btestbeds?\b|\bcarla\b|\blgsvl\b",
        r"\b(?:simulation (?:framework|platform|environment|testbed)|simulators?|carla|lgsvl)\b",
    ),
    "Synthetic Data": (
        r"\bsynthetic data\b|\bdata generation\b|\bscene generation\b",
        r"\bsynthetic data\b|\bdata generation (?:framework|pipeline)\b|\bscene generation\b",
    ),
    "Cooperative / V2X": (
        r"\bv2x\b|\bcooperative\b|\bcollaborative perception\b|\bvehicle[- ]to[- ]",
        r"\bv2x\b|\bcooperative\b|\bcollaborative perception\b|\bvehicle[- ]to[- ]",
    ),
    "VLA": (
        r"\bvision[- ]language[- ]action\b|\bvla\b",
        r"\bvision[- ]language[- ]action\b|\bvla\b",
    ),
    "World Model": (
        r"\bworld (?:action )?models?\b|\bworld modeling\b",
        r"\bworld (?:action )?models?\b|\bworld modeling\b",
    ),
    "Reinforcement Learning": (
        r"\breinforcement learning\b|\bgrpo\b|\bppo\b",
        r"\breinforcement learning\b|\bgrpo\b|\bppo\b",
    ),
    "Imitation Learning": (
        r"\bimitation learning\b|\bbehavior cloning\b",
        r"\bimitation learning\b|\bbehavior cloning\b",
    ),
    "Hardware / Real-Time": (
        r"\bhardware\b|\baccelerators?\b|\breal[- ]time\b|\blatenc(?:y|ies)\b",
        r"\bhardware deployment\b|\breal[- ]time (?:deployment|inference|performance|system)\b|\binference latency\b",
    ),
    "Survey": (
        r"\bsurveys?\b|\breviews?\b|\btutorial\b",
        r"\bthis (?:survey|systematic review|tutorial)\b",
    ),
    "Explainability": (
        r"\bexplainab(?:ility|le)\b|\binterpretab(?:ility|le)\b",
        r"\bexplainab(?:ility|le)\b|\binterpretab(?:ility|le)\b",
    ),
    "Human Interaction": (
        r"\bhuman[- ]in[- ]the[- ]loop\b|\bhuman[- ]machine\b|\bdriver monitoring\b|\btakeover\b",
        r"\bhuman[- ]in[- ]the[- ]loop\b|\bhuman[- ]machine\b|\bdriver monitoring\b|\btakeover\b",
    ),
}
TAG_ORDER = list(TAG_RULES)

# These title patterns are high-confidence semantic collisions with the search
# phrases. The gate stays deliberately narrow; ambiguous papers remain visible
# as Cross-cutting / Other instead of being silently discarded.
OUT_OF_SCOPE_TITLE_RULES = [
    ("self-driving laboratory", r"\bself[- ]driving (?:labs?|laborator(?:y|ies)|microscopy)\b"),
    ("laboratory automation", r"\blaboratory automation\b|\bautonomous liquid handling\b|\bliquid handling robots?\b"),
    ("materials or chemical discovery", r"\bmaterials? (?:discovery|exploration|science)\b|\bchemical reaction\b|\boptoelectronic materials?\b"),
    ("non-road transport", r"\bair traffic controllers?\b|\bdrone networks?\b"),
    ("non-road vision dataset", r"\bcooking\b|\bkitchen\b"),
    ("non-road embodied systems", r"\bworld model for robot learning\b|\brobotic manipulation\b"),
    ("unrelated computing systems", r"\bdatacenter\b|\bdata center performance\b"),
    ("unrelated AI risk", r"\bsentience\b|\bexistential risk\b"),
]


class ArXivFetchError(RuntimeError):
    """Raised when a refresh cannot prove that its collection is complete."""


class _ClassTextExtractor(HTMLParser):
    """Collect text from a span while preserving nested highlighted spans."""

    def __init__(self, target_class: str):
        super().__init__(convert_charrefs=True)
        self.target_class = target_class
        self.parts: List[str] = []
        self._in_target = False
        self._span_depth = 0
        self._link_depth = 0

    def handle_starttag(self, tag: str, attrs):
        classes = dict(attrs).get("class", "").split()
        if not self._in_target:
            if tag == "span" and self.target_class in classes:
                self._in_target = True
                self._span_depth = 1
            return

        if tag == "span":
            self._span_depth += 1
        elif tag == "a":
            self._link_depth += 1

    def handle_endtag(self, tag: str):
        if not self._in_target:
            return
        if tag == "a" and self._link_depth:
            self._link_depth -= 1
        elif tag == "span":
            self._span_depth -= 1
            if self._span_depth == 0:
                self._in_target = False

    def handle_data(self, data: str):
        if self._in_target and self._link_depth == 0:
            self.parts.append(data)

    def get_text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self.parts)).strip()


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
        classification = self._classify()
        self.category = classification["category"]
        self.classification_confidence = classification["confidence"]
        self.classification_score = classification["score"]
        self.classification_margin = classification["margin"]
        self.classification_evidence = classification["evidence"]
        self.tags = self._derive_tags()

    def _categorize(self) -> str:
        """Return the explainable primary topic for backward-compatible callers."""
        return self._classify()["category"]

    @staticmethod
    def _searchable_text(value: str) -> str:
        """Normalize punctuation without collapsing meaningful word boundaries."""
        return re.sub(r"\s+", " ", value.lower().replace("–", "-").replace("—", "-")).strip()

    def _classify(self) -> Dict[str, Any]:
        """Assign one primary topic using weighted, boundary-aware evidence."""
        title = self._searchable_text(self.title)
        abstract = self._searchable_text(self.abstract)
        scores: Dict[str, int] = {}
        evidence_by_category: Dict[str, List[str]] = {}

        for category, rules in CATEGORY_RULES.items():
            score = 0
            evidence = []
            for label, pattern, weight in rules:
                title_match = re.search(pattern, title)
                abstract_match = re.search(pattern, abstract)
                if title_match:
                    score += weight * 3
                    evidence.append(f"title: {label}")
                if abstract_match:
                    score += weight
                    evidence.append(f"abstract: {label}")
            scores[category] = score
            evidence_by_category[category] = evidence

        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        (top_category, top_score), (second_category, second_score) = ranked[:2]
        is_ambiguous = top_score < 6 or top_score == second_score
        category = "Cross-cutting / Other" if is_ambiguous else top_category
        margin = top_score - second_score

        if is_ambiguous:
            confidence = "low"
            evidence = []
            if top_score:
                for candidate in (top_category, second_category):
                    evidence.extend(
                        f"{candidate}: {item}" for item in evidence_by_category[candidate]
                    )
            if not evidence:
                evidence = ["no strong primary-topic signal"]
        else:
            if top_score >= 18 and margin >= 7:
                confidence = "high"
            elif top_score >= 9 and margin >= 3:
                confidence = "medium"
            else:
                confidence = "low"
            evidence = evidence_by_category[top_category]

        return {
            "category": category,
            "confidence": confidence,
            "score": top_score,
            "margin": margin,
            "evidence": evidence[:8],
        }

    def _derive_tags(self) -> List[str]:
        """Attach orthogonal method and resource tags independently of topic."""
        title = self._searchable_text(self.title)
        abstract = self._searchable_text(self.abstract)
        return [
            tag
            for tag, (title_pattern, abstract_pattern) in TAG_RULES.items()
            if re.search(title_pattern, title) or re.search(abstract_pattern, abstract)
        ]

    def scope_rejection_reason(self) -> str:
        """Return a reason only for high-confidence non-road search collisions."""
        title = self._searchable_text(self.title)
        for reason, pattern in OUT_OF_SCOPE_TITLE_RULES:
            if re.search(pattern, title):
                return reason
        return ""

    def is_in_scope(self) -> bool:
        """Keep ambiguous work visible; reject only an explicit scope collision."""
        return not self.scope_rejection_reason()

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

        rejected = [paper for paper in unique_papers if not paper.is_in_scope()]
        self.papers = [paper for paper in unique_papers if paper.is_in_scope()]
        print(f"Found {len(unique_papers)} unique papers")
        if rejected:
            reasons: Dict[str, int] = {}
            for paper in rejected:
                reason = paper.scope_rejection_reason()
                reasons[reason] = reasons.get(reason, 0) + 1
            summary = ", ".join(f"{reason}: {count}" for reason, count in reasons.items())
            print(f"Excluded {len(rejected)} high-confidence scope collisions ({summary})")
        print(f"Retained {len(self.papers)} in-scope papers")

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
                "size": HTML_PAGE_SIZE,
            }
            url = "https://arxiv.org/search/?" + urllib.parse.urlencode(params)

            html_text = self._fetch_with_retry(url, label=f"HTML '{keyword}' p{page + 1}")
            if html_text is None:
                raise ArXivFetchError(
                    f"Incomplete HTML results for '{keyword}': page {page + 1} failed"
                )

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

    @staticmethod
    def _extract_class_text(fragment: str, class_name: str) -> str:
        """Extract complete text from a classed span, including nested spans."""
        parser = _ClassTextExtractor(class_name)
        parser.feed(fragment)
        parser.close()
        return parser.get_text()

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

            # Abstract spans contain nested search-hit spans. Parse the element
            # structure so a highlighted keyword cannot terminate extraction.
            abstract = self._extract_class_text(block, "abstract-full")
            if not abstract:
                abstract = self._extract_class_text(block, "abstract-short")
                abstract = abstract.strip("…").strip()

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
                        raise ArXivFetchError(
                            f"API query for '{keyword}' failed with HTTP {e.code} "
                            f"after {max_retries} attempts"
                        ) from e
                else:
                    raise ArXivFetchError(
                        f"API query for '{keyword}' failed with HTTP {e.code}: {e.reason}"
                    ) from e

            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 5)
                    print(f"Network error ({e}), waiting {delay:.1f}s before retry "
                          f"(attempt {attempt + 2}/{max_retries})...")
                    time.sleep(delay)
                    continue
                raise ArXivFetchError(
                    f"API query for '{keyword}' failed after {max_retries} attempts: {e}"
                ) from e

            except Exception as e:
                raise ArXivFetchError(
                    f"API query for '{keyword}' failed: {e}"
                ) from e

        raise ArXivFetchError(f"API query for '{keyword}' exhausted its retries")

    def validate_collection_retention(
        self,
        data_path: str = "site/data/papers.json",
        minimum_ratio: float = MIN_COLLECTION_RETENTION_RATIO,
    ):
        """Reject an implausibly large one-run drop from the published dataset."""
        path = Path(data_path)
        if not path.exists():
            return

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            existing_count = int(payload["meta"]["total_papers"])
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise ArXivFetchError(
                f"Cannot validate the existing dataset at {path}: {exc}"
            ) from exc

        if existing_count <= 0:
            return

        minimum_count = max(1, int(existing_count * minimum_ratio))
        if len(self.papers) < minimum_count:
            raise ArXivFetchError(
                "Refresh produced only "
                f"{len(self.papers)} papers; expected at least {minimum_count} "
                f"({minimum_ratio:.0%} of the previous {existing_count})"
            )

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

    def count_tags(self) -> List[Tuple[str, int]]:
        """Return non-empty tag counts in a stable product order."""
        counts = {tag: 0 for tag in TAG_ORDER}
        for paper in self.papers:
            for tag in paper.tags:
                counts[tag] += 1
        return [(tag, counts[tag]) for tag in TAG_ORDER if counts[tag]]

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
        content += self._build_tag_navigation(self.count_tags())
        for category, papers in ordered_categories:
            content += self._build_category_section(category, papers)
        return content + self._build_footer()

    def build_data_payload(self) -> Dict[str, Any]:
        """Build the structured data consumed by GitHub Pages."""
        categories = self.categorize_papers()
        ordered_categories = self._ordered_categories(categories)
        tag_counts = self.count_tags()
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
                "taxonomy_version": "2.0",
                "categories": [
                    {
                        "name": category,
                        "slug": self._category_slug(category),
                        "count": len(category_papers),
                        "latest_published": category_papers[0].published[:10],
                    }
                    for category, category_papers in ordered_categories
                ],
                "tags": [
                    {
                        "name": tag,
                        "slug": self._category_slug(tag),
                        "count": count,
                    }
                    for tag, count in tag_counts
                ],
                "classification_confidence": {
                    confidence: sum(
                        paper.classification_confidence == confidence for paper in papers
                    )
                    for confidence in ("high", "medium", "low")
                },
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
            "primary_category": paper.category,
            "tags": paper.tags,
            "classification": {
                "confidence": paper.classification_confidence,
                "score": paper.classification_score,
                "margin": paper.classification_margin,
                "evidence": paper.classification_evidence,
            },
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

**A daily, explainable research signal for autonomous driving.**<br>
Browse one primary topic per paper, then refine the signal with method and resource tags.

<p><a href="{PAGES_URL}"><strong>Explore the interactive research index →</strong></a></p>

[Browse by topic](#browse-by-topic) · [Research tags](#research-tags) · [How it works](#how-it-works)

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

    def _build_tag_navigation(self, tag_counts: List[Tuple[str, int]]) -> str:
        """Explain the second taxonomy axis and link tags to the web index."""
        content = '<a id="research-tags"></a>\n\n## Research tags\n\n'
        content += (
            "Each paper has one primary topic and may carry several method or resource tags. "
            "Use the interactive index to combine a topic with a tag.\n\n"
        )
        content += "| Tag | Papers | Filter |\n|:--|--:|:--|\n"
        for tag, count in tag_counts:
            query = urllib.parse.urlencode({"tag": tag})
            content += f"| {tag} | {count} | [Open filter]({PAGES_URL}?{query}) |\n"
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
            if paper.tags:
                content += f"**Research tags:** {' · '.join(paper.tags)}<br>\n"
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

- Searches a focused set of road-autonomy phrases in arXiv HTML results first and uses the arXiv API as a fallback.
- Deduplicates papers by arXiv ID and rejects narrow, high-confidence phrase collisions such as self-driving laboratories.
- Assigns one weighted, boundary-aware primary topic from title and abstract evidence.
- Adds independent method and resource tags so cross-domain papers remain discoverable.
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

Collection and classification are automated and intentionally explainable. Title evidence is
weighted above abstract mentions, ambiguous papers move to Cross-cutting / Other, and every JSON
record includes classification confidence and matched evidence. The scope gate only removes
high-confidence semantic collisions, so some adjacent research may remain. Treat this project as
a discovery index and verify important details on arXiv.

<div align="center">

**⭐ If you find this repository helpful, consider giving it a star!**

[Interactive index]({PAGES_URL}) · [MIT License](LICENSE) · [Report an issue]({REPOSITORY_URL}/issues)

</div>
"""


def main():
    """Main function to run the scraper."""
    # Create scraper and fetch papers from the configured rolling window
    scraper = ArXivScraper(max_results=200)
    try:
        scraper.fetch_papers(SEARCH_KEYWORDS, days_back=DATA_WINDOW_DAYS)
        scraper.validate_collection_retention()
    except ArXivFetchError as exc:
        print(f"ERROR: {exc}. Aborting to preserve the published index.", file=sys.stderr)
        return 1

    # Safeguard: never overwrite README with an empty result set.
    # Exiting non-zero makes the GitHub Action fail loudly and keeps
    # the existing README intact.
    if not scraper.papers:
        print("ERROR: No papers fetched. Aborting to preserve existing README.",
              file=sys.stderr)
        return 1

    # Generate the GitHub README and the shared Pages dataset together.
    scraper.generate_outputs()

    print("Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
