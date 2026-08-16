import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from scrape_arxiv import ArXivPaper, ArXivScraper, PAGES_URL, REPOSITORY_URL


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


class StaticSiteContractTests(unittest.TestCase):
    def test_site_exposes_accessible_search_and_filter_controls(self):
        html = Path("site/index.html").read_text(encoding="utf-8")
        script = Path("site/assets/app.js").read_text(encoding="utf-8")

        self.assertIn('role="search"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn('id="category-filters"', html)
        self.assertIn('id="recency-filter"', html)
        self.assertIn('id="sort-filter"', html)
        self.assertIn("URLSearchParams", script)
        self.assertIn("aria-controls", script)
        self.assertIn("aria-expanded", script)
        self.assertIn("Read full abstract", script)
        self.assertIn("prefers-reduced-motion", Path("site/assets/styles.css").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
