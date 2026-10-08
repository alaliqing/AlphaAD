import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from build_site import PAGE_SIZE, build_site, render_site
from scrape_arxiv import ArXivScraper
from test_generation import paper


def bootstrap(html):
    match = re.search(r'<script id="initial-data" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(match[1])


class StaticFirstPageTests(unittest.TestCase):
    def setUp(self):
        scraper = ArXivScraper()
        scraper.papers = [
            paper(f"2608.{index:05}", f"Paper {index}", "Planning", index)
            for index in range(40)
        ]
        self.payload = scraper.build_data_payload()

    def test_first_page_is_readable_before_fetch_and_uses_global_statistics(self):
        html = render_site(self.payload)
        initial = bootstrap(html)

        self.assertEqual(html.count('class="paper-card is-initial"'), PAGE_SIZE)
        self.assertEqual(len(initial["papers"]), PAGE_SIZE)
        self.assertEqual(initial["meta"]["total_papers"], 40)
        self.assertEqual(initial["meta"]["recent_papers"], 8)
        self.assertIn('<dd id="total-papers">40</dd>', html)
        self.assertIn('<dd id="new-papers">8</dd>', html)
        self.assertIn(self.payload["papers"][0]["title"], html)
        self.assertNotIn('rel="preload" href="data/papers.json"', html)

    def test_first_page_contains_full_abstracts_for_immediate_expansion(self):
        self.payload["papers"][0]["abstract"] = "Long abstract " * 100
        self.payload["papers"][0]["short_abstract"] = "Short preview"
        html = render_site(self.payload)

        self.assertIn('aria-expanded="false">Read full abstract +', html)
        self.assertEqual(bootstrap(html)["papers"][0]["abstract"], "Long abstract " * 100)

    def test_paper_text_cannot_escape_html_or_the_initial_json_script(self):
        hostile = '</script><script>alert("paper")</script> & <img src=x>'
        self.payload["papers"][0]["title"] = hostile
        self.payload["papers"][0]["abstract"] = hostile
        self.payload["papers"][0]["short_abstract"] = hostile
        html = render_site(self.payload)

        self.assertNotIn(hostile, html)
        self.assertNotIn('<script>alert(', html)
        self.assertIn('&lt;img src=x&gt;', html)
        self.assertEqual(bootstrap(html)["papers"][0]["title"], hostile)

    def test_data_changes_get_a_new_cache_key(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "papers.json"
            output = Path(directory) / "index.html"
            raw = json.dumps(self.payload).encode()
            data.write_bytes(raw)
            build_site(data, output)
            first = bootstrap(output.read_text())["data_url"]
            self.assertTrue(first.endswith(hashlib.sha256(raw).hexdigest()[:16]))

            self.payload["papers"][0]["title"] = "Updated paper"
            data.write_text(json.dumps(self.payload))
            build_site(data, output)
            second = bootstrap(output.read_text())["data_url"]
            self.assertNotEqual(first, second)
            self.assertIn("Updated paper", output.read_text())

    def test_small_and_empty_feeds_do_not_show_more_papers(self):
        papers = self.payload["papers"]
        for count in (0, 3, PAGE_SIZE):
            self.payload["papers"] = papers[:count]
            self.payload["meta"]["total_papers"] = count
            html = render_site(self.payload)
            self.assertEqual(len(bootstrap(html)["papers"]), count)
            self.assertIn('id="load-more" type="button" disabled hidden', html)

    def test_frontend_assets_have_content_versions(self):
        html = render_site(self.payload)
        for filename in ("styles.css", "app.js"):
            version = hashlib.sha256(Path("site/assets", filename).read_bytes()).hexdigest()[:16]
            self.assertIn(f"assets/{filename}?v={version}", html)

    def test_incomplete_feed_is_rejected(self):
        self.payload["meta"]["total_papers"] += 1
        with self.assertRaisesRegex(ValueError, "count does not match"):
            render_site(self.payload)
