#!/usr/bin/env python3
"""Generate the self-contained Pip patrol SVGs from daily contribution counts."""

import argparse
from base64 import b64encode
from datetime import date
import json
import math
import os
from pathlib import Path
import random
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
QUERY = '''{
  user(login: "fujita-minato") {
    contributionsCollection {
      contributionCalendar { weeks { contributionDays { date contributionCount } } }
    }
  }
}'''
PALETTES = {
    'light': ('#f4f2eb', '#232322', '#5c5a54', '#d9d5ca', '#e2dfd6',
              ('#e2dfd6', '#cfcbc0', '#8d8a82', '#e08f84', '#c33b2b')),
    'dark': ('#0d1117', '#e6e3da', '#a29f97', '#282e37', '#20262e',
             ('#272d35', '#4a515b', '#777d85', '#ac7b76', '#e85f4e')),
}
WIDTH, TOP, HEIGHT = 840, 7, 171
WEEKS, DAYS, STEP = 53, 7, 15
TRAVEL, HOLD, FADE = 14, 2, .18
CYCLE = TRAVEL + HOLD


def load_calendar(fixture):
    if fixture:
        weeks = json.loads(fixture.read_text(encoding='utf-8'))
    else:
        response = subprocess.run(
            ['gh', 'api', 'graphql', '-f', f'query={QUERY}'],
            check=True, stdout=subprocess.PIPE,
        )
        calendar = json.loads(response.stdout)['data']['user']['contributionsCollection']
        weeks = []
        for week in calendar['contributionCalendar']['weeks']:
            counts = [0] * DAYS
            for day in week['contributionDays']:
                row = (date.fromisoformat(day['date']).weekday() + 1) % DAYS
                counts[row] = day['contributionCount']
            weeks.append(counts)
        weeks = weeks[-WEEKS:]
        weeks = [[0] * DAYS for _ in range(WEEKS - len(weeks))] + weeks

    if (not isinstance(weeks, list) or len(weeks) != WEEKS or
            any(not isinstance(week, list) or len(week) != DAYS for week in weeks) or
            any(type(count) is not int or count < 0 for week in weeks for count in week)):
        raise ValueError('Expected 53 weeks of seven non-negative integer counts')
    return weeks


def cell_path(x, y, rng):
    def jitter():
        return rng.choice((-1, 1)) * rng.uniform(.6, 1)

    corners = [(x + dx + jitter(), y + dy + jitter())
               for dx, dy in [(-6, -6), (6, -6), (6, 6), (-6, 6)]]

    def toward(corner, neighbor):
        return tuple(a + .15 * (b - a) for a, b in zip(corner, neighbor))

    def point(pair):
        return f'{pair[0]:.1f} {pair[1]:.1f}'

    start = toward(corners[0], corners[-1])
    path = [f'M{point(start)}']
    for index, corner in enumerate(corners):
        next_corner = corners[(index + 1) % 4]
        exit_point = toward(corner, next_corner)
        entry_point = toward(next_corner, corner)
        mx, my = ((a + b) / 2 for a, b in zip(exit_point, entry_point))
        bend = rng.uniform(-.35, .35)
        control = (mx, my + bend) if index % 2 == 0 else (mx + bend, my)
        path.append(f'Q{point(corner)} {point(exit_point)}Q{point(control)} {point(entry_point)}')
    return ''.join(path) + 'Z'


def render(weeks, pip, theme):
    bg, ink, secondary, ruling, unvisited, fills = PALETTES[theme]
    rng = random.Random(7)
    points = [(30 + i * STEP, round(110 + 30 * math.sin(i * math.tau / 12)))
              for i in range(WEEKS)]
    route = 'M' + 'L'.join(f'{x} {y}' for x, y in points)
    distances = [0.0]
    for previous, current in zip(points, points[1:]):
        distances.append(distances[-1] + math.dist(previous, current))
    visit_times = [(TRAVEL - FADE) * i / (WEEKS - 1) for i in range(WEEKS)]
    move, draw, reveals, ghost_grid, colored_grid = [], [], [], [], []
    for i, ((x, y), distance, visit, week) in enumerate(zip(points, distances, visit_times, weeks)):
        time = 100 * visit / CYCLE
        end = 100 * (visit + FADE) / CYCLE
        move.append(f'{time:.5f}% {{ transform: translate({x}px, {y}px); }}')
        draw.append(f'{time:.5f}% {{ stroke-dashoffset: {1 - distance / distances[-1]:.6f}; }}')
        reveals.append(f'@keyframes visit{i} {{ 0%, {time:.5f}% {{ opacity: 0; }} '
                       f'{end:.5f}%, 100% {{ opacity: 1; }} }}')

        paths = [[] for _ in fills]
        for row, count in enumerate(week):
            level = sum(count > threshold for threshold in (0, 3, 8, 15))
            paths[level].append(cell_path(x, 65 + row * STEP, rng))
        ghost_grid.extend(path for group in paths for path in group)
        colored_grid.append(f'<g class="week" style="--visit:visit{i}">')
        colored_grid.extend(f'<path fill="{fill}" d="{"".join(group)}"/>'
                            for fill, group in zip(fills, paths) if group)
        colored_grid.append('</g>')

    end_x, end_y = points[-1]
    move.append(f'100% {{ transform: translate({end_x}px, {end_y}px); }}')
    draw.append('100% { stroke-dashoffset: 0; }')
    lines = ''.join(f'M23 {y}H{WIDTH - 23}' for y in range(60, 163, 24))
    total = sum(sum(week) for week in weeks)
    active = sum(count > 0 for week in weeks for count in week)
    backing = '<circle cy="-15" r="22" fill="#e6e3da" opacity=".9"/>' if theme == 'dark' else ''
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 {TOP} {WIDTH} {HEIGHT}">
<style>
@media (prefers-reduced-motion: no-preference) {{
  .week {{ animation: var(--visit) {CYCLE}s linear infinite; }}
  .pip {{ animation: patrol {CYCLE}s linear infinite; }}
  .trace {{ animation: draw {CYCLE}s linear infinite; }}
}}
@keyframes patrol {{ {''.join(move)} }}
@keyframes draw {{ {''.join(draw)} }}
{chr(10).join(reveals)}
</style>
<defs>
  <mask id="trail" maskUnits="userSpaceOnUse" x="0" y="{TOP}" width="{WIDTH}" height="{HEIGHT}">
    <path class="trace" d="{route}" pathLength="1" fill="none" stroke="white"
      stroke-width="4" stroke-linejoin="round" stroke-dasharray="1" stroke-dashoffset="0"/>
  </mask>
</defs>
<rect y="{TOP}" width="{WIDTH}" height="{HEIGHT}" fill="{bg}"/>
<path d="{lines}" fill="none" stroke="{ruling}" stroke-opacity=".65"/>
<path d="{''.join(ghost_grid)}" fill="{unvisited}" stroke="{ruling}" stroke-width=".55"/>
<g stroke="{ink}" stroke-opacity=".66" stroke-width=".65">
{chr(10).join(colored_grid)}
</g>
<path d="{route}" mask="url(#trail)" fill="none" stroke="{fills[-1]}" stroke-width="1.4"
  stroke-dasharray="2 4" stroke-linecap="round" stroke-linejoin="round"/>
<g class="pip" transform="translate({end_x} {end_y})">
  {backing}<image href="data:image/png;base64,{pip}" x="-24" y="-39" width="48" height="48"/>
</g>
<text x="{WIDTH - 24}" y="37" text-anchor="end" fill="{secondary}" font-family="monospace" font-size="18">{total} contributions · {active} active days</text>
</svg>
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path)
    parser.add_argument('--out', type=Path, default=ROOT / 'assets')
    args = parser.parse_args()
    try:
        weeks = load_calendar(args.fixture)
    except subprocess.CalledProcessError as error:
        return error.returncode
    except (AttributeError, KeyError, TypeError, ValueError, OSError) as error:
        parser.exit(1, f'Could not read the contribution calendar: {error}\n')

    pip = b64encode((ROOT / 'assets/pip-robot.png').read_bytes()).decode('ascii')
    images = {theme: render(weeks, pip, theme).encode('utf-8') for theme in PALETTES}
    if any(len(svg) > 300_000 for svg in images.values()):
        parser.exit(1, 'Pip patrol SVG exceeds 300 KB\n')
    args.out.mkdir(parents=True, exist_ok=True)
    staged = {}
    try:
        for theme, svg in images.items():
            target = args.out / f'pip-patrol-{theme}.svg'
            with tempfile.NamedTemporaryFile(
                dir=args.out, prefix=f'.{target.name}.', suffix='.tmp', delete=False,
            ) as temporary:
                staged[target] = Path(temporary.name)
                temporary.write(svg)
        for target, temporary in staged.items():
            os.replace(temporary, target)
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
