#!/usr/bin/env python3
"""
ArXiv Autonomous Driving Papers Scraper
Fetches and categorizes recent autonomous driving research papers from arXiv.
"""

import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Dict
import time
import re


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
        """Get a badge indicating paper recency."""
        published_date = datetime.strptime(self.published, "%Y-%m-%dT%H:%M:%SZ")
        days_old = (datetime.now() - published_date).days

        if days_old <= 7:
            return "![New](https://img.shields.io/badge/New-red)"
        elif days_old <= 30:
            return "![Recent](https://img.shields.io/badge/Recent-orange)"
        elif days_old <= 90:
            return "![Fresh](https://img.shields.io/badge/Fresh-yellow)"
        return ""


class ArXivScraper:
    """Scrapes papers from arXiv API."""

    BASE_URL = "http://export.arxiv.org/api/query?"

    def __init__(self, max_results: int = 200):
        self.max_results = max_results
        self.papers: List[ArXivPaper] = []

    def fetch_papers(self, keywords: List[str], days_back: int = 90):
        """Fetch papers matching keywords from the last N days."""
        print(f"Fetching papers from the last {days_back} days...")

        for keyword in keywords:
            print(f"Searching for: {keyword}")
            papers = self._query_arxiv(keyword, days_back)
            self.papers.extend(papers)
            time.sleep(3)  # Be nice to arXiv API

        # Remove duplicates based on arxiv_id
        seen = set()
        unique_papers = []
        for paper in self.papers:
            if paper.arxiv_id not in seen:
                seen.add(paper.arxiv_id)
                unique_papers.append(paper)

        self.papers = unique_papers
        print(f"Found {len(self.papers)} unique papers")

    def _query_arxiv(self, keyword: str, days_back: int) -> List[ArXivPaper]:
        """Query arXiv API for a specific keyword."""
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

        try:
            with urllib.request.urlopen(url) as response:
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

        except Exception as e:
            print(f"Error querying arXiv for '{keyword}': {e}")
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

    def generate_readme(self):
        """Generate README.md file."""
        categories = self.categorize_papers()

        # Sort categories alphabetically
        sorted_categories = sorted(categories.items())

        readme_content = self._build_readme_header()
        readme_content += self._build_statistics(categories)
        readme_content += self._build_table_of_contents(sorted_categories)

        for category, papers in sorted_categories:
            readme_content += self._build_category_section(category, papers)

        readme_content += self._build_footer()

        with open('README.md', 'w', encoding='utf-8') as f:
            f.write(readme_content)

        print("README.md generated successfully!")

    def _build_readme_header(self) -> str:
        """Build the README header."""
        return f"""# Autonomous Driving Research Papers

![Update](https://img.shields.io/badge/Last%20Updated-{datetime.now().strftime('%Y--%m--%d')}-blue)
![Papers](https://img.shields.io/badge/Papers-{len(self.papers)}-green)

A curated collection of the latest research papers on autonomous driving from arXiv. This repository is automatically updated daily to bring you the most recent advances in self-driving technology.

## About

This repository tracks recent research papers in autonomous driving, covering topics including:
- Perception (object detection, segmentation, tracking)
- Planning and decision-making
- Control systems
- Prediction and forecasting
- Simulation environments
- End-to-end learning approaches
- Mapping and localization
- Safety and verification
- Datasets and benchmarks

Papers are automatically fetched from arXiv and categorized by topic for easy navigation.

"""

    def _build_statistics(self, categories: Dict[str, List[ArXivPaper]]) -> str:
        """Build statistics section."""
        content = "## Statistics\n\n"
        content += "| Category | Paper Count |\n"
        content += "|----------|-------------|\n"

        for category in sorted(categories.keys()):
            count = len(categories[category])
            content += f"| {category} | {count} |\n"

        content += "\n"
        return content

    def _build_table_of_contents(self, sorted_categories: List) -> str:
        """Build table of contents."""
        content = "## Table of Contents\n\n"

        for category, _ in sorted_categories:
            anchor = category.lower().replace(' ', '-').replace('&', '')
            content += f"- [{category}](#{anchor})\n"

        content += "\n---\n\n"
        return content

    def _build_category_section(self, category: str, papers: List[ArXivPaper]) -> str:
        """Build a section for a specific category."""
        content = f"## {category}\n\n"

        for paper in papers:
            # Title with badge
            badge = paper.get_recency_badge()
            badge_str = f" {badge}" if badge else ""

            content += f"### {paper.title}{badge_str}\n\n"

            # Authors
            authors_str = ", ".join(paper.authors[:5])  # First 5 authors
            if len(paper.authors) > 5:
                authors_str += ", et al."
            content += f"**Authors:** {authors_str}  \n"

            # Date
            published_date = datetime.strptime(paper.published, "%Y-%m-%dT%H:%M:%SZ")
            content += f"**Published:** {published_date.strftime('%Y-%m-%d')}  \n"

            # Links
            content += f"**Links:** [arXiv]({paper.get_arxiv_url()}) | [PDF]({paper.get_pdf_url()})  \n\n"

            # Abstract
            content += f"**Abstract:** {paper.get_short_abstract()}\n\n"
            content += "---\n\n"

        return content

    def _build_footer(self) -> str:
        """Build the README footer."""
        return """## How This Works

This repository uses a Python script to:
1. Query the arXiv API for papers matching autonomous driving keywords
2. Categorize papers based on their content using keyword analysis
3. Generate this README with formatted paper information
4. Update automatically via GitHub Actions daily

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/autonomous-driving-papers.git
cd autonomous-driving-papers

# Install dependencies (if any)
pip install -r requirements.txt

# Run the scraper
python scrape_arxiv.py
```

## Contributing

Contributions are welcome! Here are some ways you can contribute:

- **Improve categorization**: Suggest better keywords or categories for paper classification
- **Add features**: Propose new features like filtering by date range, author search, etc.
- **Fix bugs**: Report or fix any issues you find
- **Improve documentation**: Help make the README or code comments clearer

To contribute:
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Contact

For questions or suggestions, please open an issue on GitHub.

---

**Note:** This is an automated repository. Papers are fetched from arXiv and categorized algorithmically. Categorization may not always be perfect.
"""


def main():
    """Main function to run the scraper."""
    # Keywords to search for
    keywords = [
        "autonomous driving",
        "self-driving",
        "autonomous vehicles"
    ]

    # Create scraper and fetch papers from last 90 days
    scraper = ArXivScraper(max_results=200)
    scraper.fetch_papers(keywords, days_back=90)

    # Generate README
    scraper.generate_readme()

    print("Done!")


if __name__ == "__main__":
    main()
