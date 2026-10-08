"""Build a readable first page without waiting for the complete search feed."""

import argparse
import hashlib
import html
import json
import re
from datetime import datetime
from pathlib import Path


PAGE_SIZE = 24
TEMPLATE_PATH = Path(__file__).parent / "templates" / "index.html"


def escape(value):
    return html.escape(str(value), quote=True)


def format_date(value, include_year=True):
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    month = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")[date.month - 1]
    return f"{month} {date.day}" + (f", {date.year}" if include_year else "")


def external_link(href, text, label):
    return (
        f'<a href="{escape(href)}" target="_blank" rel="noopener noreferrer" '
        f'aria-label="{escape(label)} (opens in a new tab)">{text}</a>'
    )


def paper_card(paper):
    identifier = escape(paper["id"])
    abstract_id = "abstract-" + re.sub(r"[^a-z0-9]+", "-", paper["id"], flags=re.I)
    excerpt = paper.get("short_abstract") or paper["abstract"]
    authors = [author for author in paper["authors"] if author.lower() != "et al."]
    author_text = ", ".join(authors[:5])
    if len(authors) > 5 or len(paper["authors"]) > 5:
        author_text += ", et al."
    tags = "".join(
        f'<button class="paper-tag" type="button" aria-pressed="false" disabled>{escape(tag)}</button>'
        for tag in paper.get("tags", [])
    )
    tag_list = f'<div class="paper-tags" aria-label="Research tags">{tags}</div>' if tags else ""
    toggle = (
        f'<button class="abstract-toggle" type="button" aria-controls="{escape(abstract_id)}" '
        'aria-expanded="false">Read full abstract +</button>'
        if paper["abstract"] != excerpt else ""
    )
    classification = paper.get("classification") or {}
    evidence = "; ".join(classification.get("evidence", [])[:3])
    explanation = f'Automated classification · {classification.get("confidence", "unknown")} confidence'
    if evidence:
        explanation += f" · {evidence}"
    freshness = ""
    if paper["recency"] != "archive":
        label = {"new": "New", "recent": "Recent", "fresh": "Fresh"}[paper["recency"]]
        freshness = (
            f'<span class="recency-label" data-recency="{escape(paper["recency"])}">'
            f'{label} · {paper["age_days"]}d</span>'
        )
    title = external_link(
        paper["arxiv_url"],
        escape(paper["title"]) + '<span class="title-link-cue" aria-hidden="true">↗</span>',
        paper["title"] + " on arXiv",
    )
    pdf = external_link(paper["pdf_url"], "PDF  ↗", "Open PDF for " + paper["title"])
    return (
        f'<article class="paper-card is-initial" data-paper-id="{identifier}" data-recency="{escape(paper["recency"])}">'
        f'<div class="paper-index">{identifier}<time class="paper-date" datetime="{escape(paper["published"])}">'
        f'{format_date(paper["published"])}</time></div>'
        f'<div class="paper-main"><h3>{title}</h3><p class="paper-authors">{escape(author_text)}</p>'
        f'{tag_list}<p class="paper-abstract" id="{escape(abstract_id)}">{escape(excerpt)}</p>{toggle}</div>'
        '<aside class="paper-aside" aria-label="Paper metadata and links">'
        f'<span class="topic-label" title="{escape(explanation)}">{escape(paper.get("primary_category") or paper["category"])}</span>'
        f'{freshness}<div class="paper-links">{pdf}</div></aside></article>'
    )


def render_site(payload, data_version=None):
    papers = payload["papers"]
    metadata = payload["meta"]
    if metadata["total_papers"] != len(papers):
        raise ValueError("Paper count does not match the feed metadata")
    first_page = sorted(papers, key=lambda item: item["published"], reverse=True)[:PAGE_SIZE]
    recent_papers = sum(paper["age_days"] <= 7 for paper in papers)
    if data_version is None:
        data_version = hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()[:16]
    bootstrap = {
        "meta": {**metadata, "recent_papers": recent_papers},
        "papers": first_page,
        "data_url": f"data/papers.json?v={data_version}",
    }
    # Keep untrusted paper text inside the inert JSON script, including </script>.
    initial_data = json.dumps(bootstrap, ensure_ascii=False, separators=(",", ":"))
    for character, encoded in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026")):
        initial_data = initial_data.replace(character, encoded)
    categories = [{"name": "all", "count": len(papers)}, *metadata["categories"]]
    category_filters = "".join(
        f'<button class="category-chip" type="button" data-category="{escape(category["name"])}" '
        f'aria-pressed="{"true" if category["name"] == "all" else "false"}" disabled>'
        f'{escape("All topics" if category["name"] == "all" else category["name"])}'
        f'<span class="chip-count" aria-hidden="true">{category["count"]}</span></button>'
        for category in categories
    )
    replacements = {
        "styles_url": "assets/styles.css?v=" + hashlib.sha256(
            (TEMPLATE_PATH.parent.parent / "site/assets/styles.css").read_bytes()
        ).hexdigest()[:16],
        "script_url": "assets/app.js?v=" + hashlib.sha256(
            (TEMPLATE_PATH.parent.parent / "site/assets/app.js").read_bytes()
        ).hexdigest()[:16],
        "total_papers": f"{len(papers):,}",
        "recent_papers": f"{recent_papers:,}",
        "updated_at": format_date(metadata["generated_at"], False),
        "result_context": f'{len(papers):,} results · all topics · {metadata["window_days"]}-day window',
        "category_filters": category_filters,
        "tag_options": "".join(
            f'<option value="{escape(tag["name"])}">{escape(tag["name"])} · {tag["count"]}</option>'
            for tag in metadata.get("tags", [])
        ),
        "paper_cards": "\n".join(paper_card(paper) for paper in first_page),
        "initial_data": initial_data,
        "load_more_count": str(min(PAGE_SIZE, len(papers) - len(first_page))),
        "load_more_hidden": "hidden" if len(papers) <= PAGE_SIZE else "",
    }
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    return re.sub(r"\{\{([a-z_]+)\}\}", lambda match: replacements[match[1]], template)


def build_site(data_path=Path("site/data/papers.json"), output_path=Path("site/index.html")):
    raw = Path(data_path).read_bytes()
    version = hashlib.sha256(raw).hexdigest()[:16]
    content = render_site(json.loads(raw), version)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("site/data/papers.json"))
    parser.add_argument("--output", type=Path, default=Path("site/index.html"))
    args = parser.parse_args()
    build_site(args.data, args.output)
