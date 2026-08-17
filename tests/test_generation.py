import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from scrape_arxiv import (
    ArXivFetchError,
    ArXivPaper,
    ArXivScraper,
    HTML_PAGE_SIZE,
    PAGES_URL,
    REPOSITORY_URL,
)


def paper(arxiv_id, title, category, days_old):
    published = (datetime.now() - timedelta(days=days_old)).strftime("%Y-%m-%dT00:00:00Z")
    item = ArXivPaper(
        title=title,
        authors=["Ada Researcher", "Lin Engineer"],
        abstract="A focused autonomous driving research abstract for generation tests.",
        arxiv_id=arxiv_id,
        published=published,
        updated=published,
    )
    item.category = category
    return item


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.scraper = ArXivScraper()
        self.scraper.papers = [
            paper("2608.00003", "Safe planning under uncertainty", "Planning", 1),
            paper("2608.00002", "A perception benchmark", "Perception", 4),
            paper("2607.00001", "Verified vehicle control", "Control", 40),
        ]

    def test_readme_keeps_every_paper_and_back_to_top_link(self):
        readme = self.scraper.build_readme()

        self.assertEqual(readme.count("[↑ BackToTop](#browse-by-topic)"), 3)
        self.assertEqual(readme.count('<a id="paper-'), 3)
        self.assertNotIn("Latest additions", readme)
        self.assertIn("# 🚗 AlphaAD · Autonomous Driving Research", readme)
        self.assertIn("## Browse by topic", readme)
        self.assertIn(PAGES_URL, readme)
        self.assertIn(REPOSITORY_URL, readme)

    def test_readme_recency_badges_are_preserved(self):
        self.assertIn("![New]", paper("new", "New", "General", 2).get_recency_badge())
        self.assertIn(
            "![Recent]", paper("recent", "Recent", "General", 20).get_recency_badge()
        )
        self.assertIn(
            "![Fresh]", paper("fresh", "Fresh", "General", 60).get_recency_badge()
        )
        self.assertEqual(paper("archive", "Archive", "General", 120).get_recency_badge(), "")

    def test_classification_uses_boundaries_and_title_weighting(self):
        rapid = ArXivPaper(
            title="A rapid review of autonomous driving research",
            authors=["Ada Researcher"],
            abstract="This review surveys recent autonomous driving systems.",
            arxiv_id="2608.10001",
            published="2026-08-01T00:00:00Z",
            updated="2026-08-01T00:00:00Z",
        )
        vla = ArXivPaper(
            title="A Vision-Language-Action Model for Autonomous Driving",
            authors=["Ada Researcher"],
            abstract="The model predicts a trajectory and uses reinforcement learning.",
            arxiv_id="2608.10002",
            published="2026-08-01T00:00:00Z",
            updated="2026-08-01T00:00:00Z",
        )

        self.assertNotEqual(rapid.category, "Control & Vehicle Dynamics")
        self.assertEqual(vla.category, "End-to-End & VLA")
        self.assertIn("VLA", vla.tags)
        self.assertEqual(vla.classification_confidence, "high")

    def test_resource_tags_require_central_contribution_evidence(self):
        evaluated = ArXivPaper(
            title="A perception method for autonomous driving",
            authors=["Ada Researcher"],
            abstract="We evaluate the method on several public datasets and benchmarks.",
            arxiv_id="2608.10003",
            published="2026-08-01T00:00:00Z",
            updated="2026-08-01T00:00:00Z",
        )
        released = ArXivPaper(
            title="RoadScenes: An autonomous driving dataset and benchmark",
            authors=["Ada Researcher"],
            abstract="We release a dataset for difficult road scenes.",
            arxiv_id="2608.10004",
            published="2026-08-01T00:00:00Z",
            updated="2026-08-01T00:00:00Z",
        )

        self.assertNotIn("Dataset", evaluated.tags)
        self.assertNotIn("Benchmark", evaluated.tags)
        self.assertIn("Dataset", released.tags)
        self.assertIn("Benchmark", released.tags)

    def test_scope_gate_rejects_semantic_collision_but_keeps_road_uav_work(self):
        laboratory = ArXivPaper(
            title="A self-driving laboratory for chemical discovery",
            authors=["Ada Researcher"],
            abstract="Autonomous vehicles motivate parts of our automation stack.",
            arxiv_id="2608.10005",
            published="2026-08-01T00:00:00Z",
            updated="2026-08-01T00:00:00Z",
        )
        traffic_uav = ArXivPaper(
            title="A UAV dataset for vehicle interactions in mixed traffic",
            authors=["Ada Researcher"],
            abstract="The dataset supports autonomous driving perception.",
            arxiv_id="2608.10006",
            published="2026-08-01T00:00:00Z",
            updated="2026-08-01T00:00:00Z",
        )

        self.assertFalse(laboratory.is_in_scope())
        self.assertTrue(traffic_uav.is_in_scope())

    def test_html_parser_keeps_complete_abstract_with_nested_highlights(self):
        html = """
        <ol>
          <li class="arxiv-result">
            <a href="https://arxiv.org/abs/2607.23404">arXiv:2607.23404</a>
            <p class="title is-5 mathjax">Transfer learning for driving labs</p>
            <p class="authors"><a href="#">Ada Researcher</a></p>
            <p class="abstract mathjax">
              <span class="abstract-short has-text-grey-dark mathjax">
                <span class="search-hit mathjax">Self</span>-driving labs increasingly rely&hellip;
                <a class="is-size-7">More</a>
              </span>
              <span class="abstract-full has-text-grey-dark mathjax">
                <span class="search-hit mathjax">Self</span>-<span class="search-hit mathjax">driving</span>
                laboratories increasingly rely on multi-fidelity optimization for efficient discovery.
                <a class="is-size-7">Less</a>
              </span>
            </p>
            <p class="is-size-7"><span>Submitted</span> 25 July, 2026;</p>
          </li>
        </ol>
        """

        papers, _ = self.scraper._parse_search_html(html, datetime(2026, 1, 1))

        self.assertEqual(len(papers), 1)
        self.assertEqual(
            papers[0].abstract,
            "Self-driving laboratories increasingly rely on multi-fidelity optimization "
            "for efficient discovery.",
        )

    def test_payload_is_sorted_and_matches_category_counts(self):
        payload = self.scraper.build_data_payload()

        self.assertEqual(payload["meta"]["total_papers"], 3)
        self.assertEqual(payload["papers"][0]["id"], "2608.00003")
        self.assertEqual(payload["papers"][-1]["id"], "2607.00001")
        counts = {item["name"]: item["count"] for item in payload["meta"]["categories"]}
        self.assertEqual(counts, {"Perception": 1, "Planning": 1, "Control": 1})
        self.assertEqual(payload["meta"]["taxonomy_version"], "2.0")
        self.assertIn("classification_confidence", payload["meta"])
        self.assertIn("primary_category", payload["papers"][0])
        self.assertIn("classification", payload["papers"][0])

    def test_readme_and_payload_share_research_tags(self):
        for item in self.scraper.papers:
            item.tags = []
        self.scraper.papers[0].tags = ["VLA", "World Model"]

        readme = self.scraper.build_readme()
        payload = self.scraper.build_data_payload()

        self.assertIn("## Research tags", readme)
        self.assertIn("| VLA | 1 |", readme)
        self.assertIn("**Research tags:** VLA · World Model", readme)
        tag_counts = {item["name"]: item["count"] for item in payload["meta"]["tags"]}
        self.assertEqual(tag_counts, {"VLA": 1, "World Model": 1})
        self.assertEqual(payload["papers"][0]["tags"], ["VLA", "World Model"])

    def test_generate_outputs_writes_matching_readme_and_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            readme_path = root / "README.md"
            data_path = root / "site" / "data" / "papers.json"

            self.scraper.generate_outputs(str(readme_path), str(data_path))

            readme = readme_path.read_text(encoding="utf-8")
            payload = json.loads(data_path.read_text(encoding="utf-8"))
            self.assertEqual(readme.count("BackToTop"), payload["meta"]["total_papers"])
            self.assertEqual(len(payload["papers"]), payload["meta"]["total_papers"])

    def test_html_query_uses_large_pages_to_reduce_rate_limit_pressure(self):
        with mock.patch.object(
            self.scraper, "_fetch_with_retry", return_value="<ol></ol>"
        ) as fetch:
            self.scraper._query_arxiv_html("autonomous driving", days_back=180)

        query = parse_qs(urlparse(fetch.call_args.args[0]).query)
        self.assertEqual(query["size"], [str(HTML_PAGE_SIZE)])
        self.assertEqual(HTML_PAGE_SIZE, 200)

    def test_html_pagination_failure_rejects_partial_results(self):
        submitted = (datetime.now() - timedelta(days=1)).strftime("%d %B, %Y")
        html = f"""
        <ol>
          <li class="arxiv-result">
            <a href="https://arxiv.org/abs/2608.00001">arXiv:2608.00001</a>
            <p class="title is-5 mathjax">Safe autonomous driving</p>
            <p class="authors"><a href="#">Ada Researcher</a></p>
            <p class="abstract mathjax">
              <span class="abstract-full">A complete abstract for pagination.</span>
            </p>
            <p class="is-size-7"><span>Submitted</span> {submitted};</p>
          </li>
        </ol>
        """
        with mock.patch.object(
            self.scraper, "_fetch_with_retry", side_effect=[html, None]
        ), mock.patch("scrape_arxiv.time.sleep"):
            with self.assertRaisesRegex(ArXivFetchError, "page 2 failed"):
                self.scraper._query_arxiv_html("autonomous driving", days_back=180)

    def test_collection_retention_rejects_large_one_run_drop(self):
        self.scraper.papers = self.scraper.papers[:2]
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "papers.json"
            data_path.write_text(
                json.dumps({"meta": {"total_papers": 3}}), encoding="utf-8"
            )

            with self.assertRaisesRegex(ArXivFetchError, "expected at least"):
                self.scraper.validate_collection_retention(
                    str(data_path), minimum_ratio=1.0
                )


class StaticSiteContractTests(unittest.TestCase):
    def test_site_exposes_accessible_search_and_filter_controls(self):
        html = Path("site/index.html").read_text(encoding="utf-8")
        script = Path("site/assets/app.js").read_text(encoding="utf-8")

        self.assertIn('role="search"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn('id="category-filters"', html)
        self.assertIn('id="tag-filter"', html)
        self.assertIn('id="recency-filter"', html)
        self.assertIn('id="sort-filter"', html)
        self.assertIn("URLSearchParams", script)
        self.assertIn('next.set("tag", state.tag)', script)
        self.assertIn("paper.tags || []", script)
        self.assertIn("aria-controls", script)
        self.assertIn("aria-expanded", script)
        self.assertIn("Read full abstract", script)
        self.assertIn("setExternalLink(title, paper.arxiv_url", script)
        self.assertNotIn('createElement("a", "", "arXiv', script)
        styles = Path("site/assets/styles.css").read_text(encoding="utf-8")
        self.assertNotIn("Newsreader", html)
        self.assertIn("Autonomous driving, <span>indexed.</span>", html)
        self.assertIn("width: min(1320px, calc(100% - 48px));", styles)
        self.assertIn("grid-template-columns: 118px minmax(0, 1fr) 166px;", styles)
        self.assertIn(".paper-tags", styles)
        self.assertIn("prefers-reduced-motion", styles)


if __name__ == "__main__":
    unittest.main()
