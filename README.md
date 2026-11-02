# 10th ICFFR programme viewer

Unofficial, browsable version of the [10th International Conference on Forest Fire Research](https://events.adai.pt/en/10th-icffr/programme) programme (Coimbra, 2–5 November 2026). Hover a talk for its title, authors and abstract; click or tap to pin it open and star it.

- `data/schedule.json`: the session grid, transcribed by hand from the organisers' schematic programme PDF (final version).
- `scripts/build_data.py`: fetches the public presenter/title/code lists, the detailed programme (speaker country and institution), keynote pages and abstracts from events.adai.pt, joins them to the grid, and writes `docs/programme.js`. Emails, ORCIDs and review comments that the source pages also carry are left out.
- `docs/`: the static site served by GitHub Pages.

Rebuild after the organisers change the lists:

```
python3 scripts/build_data.py
```

Poster boards come from the detailed programme, which states one per poster; the PDF table is the fallback. The script prints codes that appear in the grid with no listing, scheduled talks with no matched abstract or speaker country, listed talks missing from the grid, and any room, poster-board or speaker differences between the grid and the detailed programme. If the grid itself changes, edit `data/schedule.json`.
