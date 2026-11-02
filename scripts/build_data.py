#!/usr/bin/env python3
"""Build docs/programme.js from the conference website and data/schedule.json.

Fetches the public oral/poster code lists, the public abstracts listing and
the keynote pages from events.adai.pt, joins them on presentation code and
title, and writes a single JS data file the static site loads.

Only public, presentation-level fields are kept (title, presenter, authors,
theme, keywords, abstract). Emails, ORCIDs and review comments that the
abstracts page also embeds are deliberately dropped.

Usage: python3 scripts/build_data.py
"""
import difflib
import html
import json
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://events.adai.pt/en/10th-icffr/"
UA = {"User-Agent": "Mozilla/5.0 (programme viewer build)"}

THEMES = {
    "WUI": "Fire at the wildland urban interface",
    "NET": "New and emerging technologies",
    "RAD": "Risk adaptation",
    "RAS": "Risk assessment",
    "RR": "Risk reduction",
    "WMS": "Wildfire management and safety",
}
KEYNOTE_PAGES = ["kn-dxv", "kn-marta", "kn-sally", "kn-amy", "kn-matt", "kn-imma", "kn-dominique"]
CODE_RE = re.compile(r"^(WUI|NET|RAD|RAS|RR|WMS)(_P)?_\d+$")


def fetch(path):
    req = urllib.request.Request(BASE + path, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8")


def text(fragment):
    t = re.sub(r"<br\s*/?>", "\n", fragment)
    t = re.sub(r"</p>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", re.sub(r"\s*\n\s*", "\n", t)).strip()


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", s)


def parse_code_table(page):
    """Rows of (presenter, title, code) from a list-of-presentations page.

    Returns {code: [entry, ...]}; the organiser's lists occasionally give one
    code to two talks, so every listing is kept."""
    out = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.S):
        cells = [text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)]
        if len(cells) != 3:
            continue
        presenter, title, code = (c.replace("\n", " ").strip() for c in cells)
        if not CODE_RE.match(code):
            continue
        entry = {"presenter": presenter, "title": title}
        if all(norm(e["title"]) != norm(title) for e in out.get(code, [])):
            out.setdefault(code, []).append(entry)
    return out


def merge_code_lists(primary, secondary):
    """Primary list wins; talks the secondary list also files under the same
    code are kept as `conflicts` so the site can flag them."""
    merged = {}
    for code in sorted(set(primary) | set(secondary)):
        listed = primary.get(code, []) + secondary.get(code, [])
        uniq = []
        for e in listed:
            if all(norm(e["title"]) != norm(u["title"]) for u in uniq):
                uniq.append(e)
        entry = dict(uniq[0])
        if len(uniq) > 1:
            entry["conflicts"] = uniq[1:]
            print(f"warning: {code} is given to {len(uniq)} different talks", file=sys.stderr)
        merged[code] = entry
    return merged


def parse_abstracts(page):
    blob = max(re.findall(r'wire:initial-data="([^"]*)"', page), key=len)
    topics = json.loads(html.unescape(blob))["serverMemo"]["data"]["allTopicsProcessed"]
    out = []
    for t in topics.values():
        if t["state"]["code"] in ("withdrawal", "rejected"):
            continue
        p = t.get("parameters") or {}
        out.append({
            "title": (t.get("title") or {}).get("en", "").strip(),
            "authors": t.get("users") or [],
            "keywords": (p.get("keywords-up-to-5-separated-by-a-coma") or "").strip(),
            "abstract": (p.get("short-abstract-up-to-400-words-copy-and-paste-here-from-you-short-paper") or "").strip(),
        })
    return out


def parse_keynote(page, n):
    page = re.sub(r"<(style|script)\b.*?</\1>", "", page, flags=re.S | re.I)
    main = page[page.find("<main"):]
    body = main[main.find("Keynote %d" % n):]
    body = body[: body.find("Continue")] if "Continue" in body else body
    t = text(body)
    lines = [l for l in t.split("\n") if l.strip()]
    title = re.sub(r"^Keynote \d+\s*-\s*", "", lines[0]).strip()
    speaker = lines[1].strip() if len(lines) > 1 else ""
    m_bio = re.search(r"Short Biography\s*:\s*(.*?)(?=Short Summary\s*:|$)", t, flags=re.S | re.I)
    m_sum = re.search(r"Short Summary\s*:\s*(.*)$", t, flags=re.S | re.I)
    return {
        "title": title,
        "presenter": speaker,
        "abstract": m_sum.group(1).strip() if m_sum else "",
        "bio": m_bio.group(1).strip() if m_bio else "",
    }


def find_abstract(talk, abstracts, by_norm):
    """Exact title, then near-identical title, then (for retitled talks) the
    presenter's own submission with the most similar title."""
    k = norm(talk["title"])
    if k in by_norm:
        return by_norm[k]
    close = difflib.get_close_matches(k, list(by_norm), n=1, cutoff=0.85)
    if close:
        return by_norm[close[0]]
    surname = norm(talk["presenter"].split()[-1]) if talk["presenter"].split() else ""
    mine = [a for a in abstracts if surname and any(norm(u).endswith(surname) for u in a["authors"])]
    scored = sorted(((difflib.SequenceMatcher(None, k, norm(a["title"])).ratio(), i) for i, a in enumerate(mine)), reverse=True)
    if scored and scored[0][0] >= 0.45:
        return mine[scored[0][1]]
    return None


def match_abstracts(talks, abstracts):
    by_norm = {norm(a["title"]): a for a in abstracts}
    unmatched = []
    for code, talk in talks.items():
        for t in [talk] + talk.get("conflicts", []):
            a = find_abstract(t, abstracts, by_norm)
            if a is None:
                if t is talk:
                    unmatched.append(code)
                continue
            if norm(a["title"]) != norm(t["title"]):
                print(f"check fuzzy match {code}: {t['title'][:60]!r} -> {a['title'][:60]!r}")
            t.update({kk: a[kk] for kk in ("authors", "keywords", "abstract")})
    return unmatched


def main():
    schedule = json.loads((ROOT / "data" / "schedule.json").read_text())
    talks = merge_code_lists(parse_code_table(fetch("list-of-oral-presentations")),
                             parse_code_table(fetch("list-of-oral-presentation-by-theme")))
    posters = merge_code_lists(parse_code_table(fetch("list-of-poster-presentations")), {})
    abstracts = parse_abstracts(fetch("abstracts"))

    entries = {}
    for code, t in {**talks, **posters}.items():
        prefix = code.split("_")[0]
        t["theme"] = prefix
        t["kind"] = "poster" if "_P_" in code else "oral"
        entries[code] = t
    unmatched = match_abstracts(entries, abstracts)

    for i, slug in enumerate(KEYNOTE_PAGES, start=1):
        k = parse_keynote(fetch(slug), i)
        k.update({"theme": "KN", "kind": "keynote"})
        entries["KN %d" % i] = k

    scheduled = set()
    for day in schedule["days"]:
        for _, _, slot in day["rows"]:
            if isinstance(slot, list):
                scheduled.update(c for c in slot if c)
            elif "keynote" in slot:
                scheduled.add(slot["keynote"])
    for p in schedule["posters"]:
        for board in p["boards"]:
            scheduled.update(board[1])

    missing = sorted(c for c in scheduled if c not in entries)
    unscheduled = sorted(c for c in entries if c not in scheduled)
    no_abstract = sorted(c for c in unmatched if c in scheduled)

    out = {"themes": THEMES, "schedule": schedule, "entries": entries, "unscheduled": unscheduled}
    dest = ROOT / "docs" / "programme.js"
    dest.write_text("window.PROGRAMME = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n")

    print(f"entries: {len(entries)}  (oral {len(talks)}, posters {len(posters)}, abstracts pool {len(abstracts)})")
    print(f"in grid but not in code lists ({len(missing)}): {' '.join(missing)}")
    print(f"scheduled without a matched abstract ({len(no_abstract)}): {' '.join(no_abstract)}")
    print(f"in code lists but not in grid ({len(unscheduled)}): {' '.join(unscheduled)}")
    print(f"wrote {dest.relative_to(ROOT)} ({dest.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
