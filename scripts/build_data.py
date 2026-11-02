#!/usr/bin/env python3
"""Build docs/programme.js from the conference website and data/schedule.json.

Fetches the public oral/poster code lists, the public abstracts listing, the
detailed programme (event timeline) and the keynote pages from
events.adai.pt, joins them on presentation code and title, and writes a
single JS data file the static site loads.

Only public, presentation-level fields are kept (title, presenter, speaker
country and institution, authors, theme, keywords, abstract). Emails, ORCIDs and review comments that the
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


def parse_timeline(page):
    """Speaker country/institution and room per code from the detailed programme.

    Each talk is a `sub-activity-item` block holding a `badge-code` span, a
    room line and a "Speaker:" line of the form
    <b>Name</b><i>, Country</i><i style=...>, Institution</i>; either italic
    part may be missing (the institution one carries a style attribute)."""
    out = {}
    for block in page.split("sub-activity-item")[1:]:
        m_code = re.search(r'badge-code[^>]*>\s*([A-Z_0-9]+)(?:\s*\|\s*TV\s*(\d+))?\s*<', block)
        if not m_code or not CODE_RE.match(m_code.group(1)):
            continue
        code = m_code.group(1)
        m_room = re.search(r"fa-location-dot[^>]*></i>\s*([^<]+?)\s*<", block)
        m_spk = re.search(r"Speaker:</span>\s*<span[^>]*>\s*<span class=\"fw-bold[^\"]*\">([^<]*)</span>"
                          r"((?:<span class=\"text-muted fst-italic\"[^>]*>[^<]*</span>)*)", block)
        info = {"room": html.unescape(m_room.group(1)).strip() if m_room else "",
                "board": "TV" + m_code.group(2) if m_code.group(2) else ""}
        if m_spk:
            info["speaker"] = html.unescape(m_spk.group(1)).strip()
            for attrs, val in re.findall(r'<span class="text-muted fst-italic"([^>]*)>([^<]*)</span>', m_spk.group(2)):
                val = html.unescape(val).strip(" ,\n\t")
                if val:
                    info["institution" if "style=" in attrs else "country"] = val
        out.setdefault(code, info)
    return out


def regroup_poster_boards(posters, timeline):
    """Poster boards per day, taking each poster's board from the detailed
    programme (which states it per poster) and falling back to the board
    group read off the PDF table. Boards that only carry a note (e.g. the
    FAO Fire Hub screen) are kept as they are."""
    def board_key(label):
        m = re.search(r"\d+", label)
        return (int(m.group()) if m else 99, label)
    out = []
    for day in posters:
        groups, notes = {}, []
        for board in day["boards"]:
            label, codes = board[0], board[1]
            if len(board) > 2 and not codes:
                notes.append(board)
                continue
            for c in codes:
                groups.setdefault((timeline.get(c) or {}).get("board") or label, []).append(c)
        boards = [[label, codes] for label, codes in groups.items()] + notes
        boards.sort(key=lambda b: board_key(b[0]))
        out.append({**day, "boards": boards})
    return out


def same_person(a, b):
    """Name variants of one person ("Fábio M. Silva" / "Fábio Miguel Martins da
    Silva", "Mosbah Omar" / "Omar Mosbah", "Gómez González" / "Gómez-González"):
    at least two full name parts in common, ignoring initials."""
    parts = lambda n: {norm(t) for t in re.split(r"[\s\-]+", n) if len(norm(t)) > 1}
    return len(parts(a) & parts(b)) >= 2


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

    timeline = parse_timeline(fetch("event-timeline/timeline"))
    for code, info in timeline.items():
        e = entries.get(code)
        if not e:
            continue
        spk = info.get("speaker", "")
        if spk and not same_person(spk, e["presenter"]):
            # a different person: keep their details apart rather than attach them to the listed presenter
            e["altSpeaker"] = {k: info[k] for k in ("speaker", "country", "institution") if info.get(k)}
            print(f"speaker differs {code}: code list says {e['presenter']!r}, detailed programme says {spk!r}")
            continue
        for k in ("country", "institution"):
            if info.get(k):
                e[k] = info[k]

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
    no_country = sorted(c for c in scheduled if c in entries and entries[c]["kind"] != "keynote" and not entries[c].get("country"))

    # rooms in the detailed programme vs the grid transcribed from the PDF
    grid_room = {}
    for day in schedule["days"]:
        for _, _, slot in day["rows"]:
            if isinstance(slot, list):
                for i, c in enumerate(slot):
                    if c:
                        grid_room[c] = schedule["rooms"][i]
    grid_board = {c: b[0] for p in schedule["posters"] for b in p["boards"] for c in b[1]}
    board_diff = [f"{c} (grid {grid_board[c]}, detailed {timeline[c]['board']})" for c in sorted(grid_board)
                  if c in timeline and timeline[c]["board"] and timeline[c]["board"] not in grid_board[c]]
    schedule["posters"] = regroup_poster_boards(schedule["posters"], timeline)
    room_diff = [f"{c} (grid {grid_room[c]}, detailed {timeline[c]['room']})" for c in sorted(grid_room)
                 if c in timeline and timeline[c]["room"] and norm(timeline[c]["room"]) != norm(grid_room[c])]

    out = {"themes": THEMES, "schedule": schedule, "entries": entries, "unscheduled": unscheduled}
    dest = ROOT / "docs" / "programme.js"
    dest.write_text("window.PROGRAMME = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n")

    print(f"entries: {len(entries)}  (oral {len(talks)}, posters {len(posters)}, abstracts pool {len(abstracts)})")
    print(f"in grid but not in code lists ({len(missing)}): {' '.join(missing)}")
    print(f"scheduled without a matched abstract ({len(no_abstract)}): {' '.join(no_abstract)}")
    print(f"in code lists but not in grid ({len(unscheduled)}): {' '.join(unscheduled)}")
    print(f"detailed programme: {len(timeline)} codes; scheduled talks without speaker country ({len(no_country)}): {' '.join(no_country)}")
    print(f"room differs between grid and detailed programme ({len(room_diff)}): {'; '.join(room_diff)}")
    print(f"poster boards taken from the detailed programme where they differ from the PDF ({len(board_diff)}): {'; '.join(board_diff)}")
    print(f"wrote {dest.relative_to(ROOT)} ({dest.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
