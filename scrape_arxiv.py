#!/usr/bin/env python3
"""
ArXiv Autonomous Driving Papers Scraper
Fetches and categorizes recent autonomous driving research papers from arXiv.
"""

import sys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Dict
import time
import re
import random


USER_AGENT = "AlphaAD-arxiv-scraper/1.0 (+https://github.com/qinjing/AlphaAD)"


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

    BASE_URL = "https://export.arxiv.org/api/query?"

    def __init__(self, max_results: int = 200):
        self.max_results = max_results
        self.papers: List[ArXivPaper] = []

    def fetch_papers(self, keywords: List[str], days_back: int = 180):
        """Fetch papers matching keywords from the last N days."""
        print(f"Fetching papers from the last {days_back} days...")

        for idx, keyword in enumerate(keywords):
            print(f"Searching for: {keyword}")
            papers = self._query_arxiv(keyword, days_back)
            self.papers.extend(papers)
            # Be conservative between keywords to avoid rate limiting.
            # arXiv recommends >=3s; we use 20-30s for batch jobs.
            if idx < len(keywords) - 1:
                delay = random.uniform(20, 30)
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
        return f"""<div align="center">

# 🚗 Autonomous Driving Research Papers

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Last Update](https://img.shields.io/badge/Last%20Updated-{datetime.now().strftime('%Y--%m--%d')}-blue)
![Total Papers](https://img.shields.io/badge/Papers-{len(self.papers)}-green)
![Auto Update](https://img.shields.io/badge/Auto--Update-Daily-brightgreen)

> A curated collection of the latest research papers on autonomous driving from arXiv
> This repository is automatically updated daily to bring you the most recent advances
> in self-driving technology (papers from the last 6 months)

</div>

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

## ✨ Features

- 🕐 **Daily Updates**: Automatically updated every day with the latest papers
- 🎯 **Smart Categorization**: Papers are organized into 10 main categories
- 🏷️ **Recency Badges**: Visual indicators show how recent each paper is
- 🔍 **Easy Navigation**: Table of contents and category-based organization
- 📄 **Direct Links**: Quick access to arXiv abstracts and PDFs
- 📊 **Statistics**: Track the number of papers in each category

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
            content += f"**Links:** [arXiv]({paper.get_arxiv_url()}) | [PDF]({paper.get_pdf_url()}) | [BackToTop](#table-of-contents)  \n\n"

            # Abstract
            content += f"**Abstract:** {paper.get_short_abstract()}\n\n"
            content += "---\n\n"

        return content

    def _build_footer(self) -> str:
        """Build the README footer."""
        return """---

## 🤖 How It Works

This repository uses automation to stay up-to-date with the latest research:

- **Automated Fetching**: Python script queries the arXiv API daily using relevant keywords
- **Smart Categorization**: Papers are categorized by topic using keyword analysis
- **Auto-Generated README**: This README is automatically generated with formatted paper information
- **GitHub Actions**: Updates run automatically every day at 00:00 UTC

## ⚙️ Local Usage

Want to run the scraper locally or contribute to the project?

```bash
# Clone the repository
git clone https://github.com/qinjing/AlphaAD.git
cd AlphaAD

# The script uses only Python standard library (no external dependencies)
python3 scrape_arxiv.py
```

**Requirements**: Python 3.11 or higher

## 🤝 Contributing

Contributions are welcome! Here are some ways you can contribute:

- **Improve categorization**: Suggest better keywords or categories for paper classification
- **Add features**: Propose new features like filtering by date range, author search, etc.
- **Fix bugs**: Report or fix any issues you find
- **Enhance documentation**: Help improve the README or code comments

To contribute:
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📊 Topics Covered

| Category | Description |
|----------|-------------|
| **Perception** | Object detection, segmentation, tracking, sensor fusion |
| **Planning** | Path planning, motion planning, trajectory optimization |
| **Control** | Vehicle control, MPC, steering, acceleration |
| **Prediction** | Trajectory prediction, intent prediction, forecasting |
| **Simulation** | Simulation environments, synthetic data |
| **End-to-End Learning** | Imitation learning, reinforcement learning |
| **Mapping & Localization** | SLAM, HD maps, visual odometry |
| **Safety & Verification** | Safety verification, robust testing |
| **Dataset & Benchmark** | Dataset collections, benchmarks |
| **General** | Other autonomous driving research |

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 📮 Contact & Feedback

- **Issues**: [Open an issue](https://github.com/qinjing/AlphaAD/issues) for bugs or feature requests
- **Discussions**: [Start a discussion](https://github.com/qinjing/AlphaAD/discussions) for questions or ideas

---

<div align="center">

**⭐ If you find this repository helpful, consider giving it a star!**

Made with ❤️ by the autonomous driving community

</div>

**Note**: This is an automated repository. Papers are fetched from arXiv and categorized algorithmically. Categorization may not always be perfect. Please report any misclassified papers.
"""


def main():
    """Main function to run the scraper."""
    # Keywords to search for
    keywords = [
        "autonomous driving",
        "self-driving",
        "autonomous vehicles"
    ]

    # Create scraper and fetch papers from last 180 days
    scraper = ArXivScraper(max_results=200)
    scraper.fetch_papers(keywords, days_back=180)

    # Safeguard: never overwrite README with an empty result set.
    # Exiting non-zero makes the GitHub Action fail loudly and keeps
    # the existing README intact.
    if not scraper.papers:
        print("ERROR: No papers fetched. Aborting to preserve existing README.",
              file=sys.stderr)
        sys.exit(1)

    # Generate README
    scraper.generate_readme()

    print("Done!")


if __name__ == "__main__":
    main()
