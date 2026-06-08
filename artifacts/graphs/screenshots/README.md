# Screenshot Capture Instructions

This directory holds the before/after screenshots for the Episode 1 thread, YouTube build-log, and AIR piece.

## What to capture

### 1. `naive-full.png` — The corrupted "before" map (full view)
- Open `artifacts/graphs/naive.html` in a browser
- Wait for the force-directed layout to settle (~5 seconds)
- Full-screen screenshot at 1920x1080 or retina equivalent
- This is the "gorgeous map that's lying to you" shot

### 2. `naive-corruption-detail.png` — Zoomed corruption
- Same file, but zoom into a region showing one of the corruption modes
- Annotate (in a screenshot tool) which nodes are split/collapsed
- This is the "gut-punch" screenshot

### 3. `resolved-full.png` — The resolved "after" map (full view)
- Open `artifacts/graphs/resolved.html` in a browser
- Same dimensions as the naive screenshot for side-by-side comparison
- This is the "clean truth" shot

### 4. `before-after-sidebyside.png` — Side-by-side comparison
- Composite image: naive on left, resolved on right
- Same zoom level for both halves
- This is the restack magnet for the Twitter thread

### 5. `decision-log.png` — Terminal output of the decision log
- Run: `cat artifacts/logs/decisions.jsonl | python -m json.tool`
- Screenshot the terminal showing the merge, refuse, and drop decisions
- This proves the observability claim

## When to capture

- After running a fresh `substackgraph crawl` + `render-naive` + `render-resolved`
- BEFORE any manual edits to the HTML files
- Ideally with the same dataset used in the thread (110 nodes / 128 edges)

## Tips

- Use a dark terminal theme for the decision log screenshot (matches the build-in-public aesthetic)
- For the graph screenshots, use a browser without UI chrome (F11 fullscreen mode)
- Save at 2x resolution if possible for retina displays
- Consider recording a screen capture during the first render for the YouTube build-log
