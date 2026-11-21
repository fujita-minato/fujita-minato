#!/usr/bin/env python3
"""Generate the self-contained Pip patrol SVGs from daily contribution counts."""

import argparse
from base64 import b64encode
from datetime import date
import fcntl
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import tempfile
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
CALENDAR_URL = 'https://github.com/users/fujita-minato/contributions'
PALETTES = {
    'light': ('#f4f2eb', '#232322', '#5c5a54', '#d9d5ca', '#e2dfd6',
              ('#e2dfd6', '#cfcbc0', '#8d8a82', '#e08f84', '#c33b2b')),
    'dark': ('#0d1117', '#e6e3da', '#a29f97', '#282e37', '#20262e',
             ('#272d35', '#4a515b', '#777d85', '#ac7b76', '#e85f4e')),
}
TOP, HEIGHT = 7, 171
DAYS, STEP = 7, 15
TRAVEL, HOLD, FADE = 14, 2, .18
CYCLE = TRAVEL + HOLD


class ContributionCalendar(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cells = []
        self.tooltips = {}
        self.tooltip_day = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'td' and 'data-date' in attrs:
            self.cells.append((date.fromisoformat(attrs['data-date']),
                               attrs['id'], attrs.get('data-level')))
        elif tag == 'tool-tip' and 'for' in attrs:
            self.tooltip_day = attrs['for']
            self.tooltips[self.tooltip_day] = ''

    def handle_data(self, data):
        if self.tooltip_day is not None:
            self.tooltips[self.tooltip_day] += data

    def handle_endtag(self, tag):
        if tag == 'tool-tip':
            self.tooltip_day = None


def load_calendar(fixture):
    if fixture:
        weeks = json.loads(fixture.read_text(encoding='utf-8'))
    else:
        calendar = ContributionCalendar()
        with urlopen(CALENDAR_URL, timeout=30) as response:
            calendar.feed(response.read().decode('utf-8'))
        calendar.close()
        dates = {day for day, _, _ in calendar.cells}
        if not dates or len(dates) != len(calendar.cells):
            raise ValueError('Expected one contribution cell per date')
        first = min(dates)
        sunday = first.toordinal() - (first.weekday() + 1) % DAYS
        columns = (max(dates).toordinal() - sunday) // DAYS + 1
        if columns not in (53, 54):
            raise ValueError('Expected 53 or 54 public weeks')
        weeks = [[0] * DAYS for _ in range(columns)]
        for day, cell_id, level in calendar.cells:
            label = calendar.tooltips.get(cell_id, '').strip()
            match = re.match(r'(No|[0-9][0-9,]*)\s+contributions?\b', label)
            if match:
                count = int(match[1].replace(',', '')) if match[1] != 'No' else 0
            else:
                # shortcut: color level only approximates the count when the tooltip is missing.
                count = int(level)
            col, row = divmod(day.toordinal() - sunday, DAYS)
            weeks[col][row] = count

    if (not isinstance(weeks, list) or (fixture is not None and len(weeks) != 53) or
            any(not isinstance(week, list) or len(week) != DAYS for week in weeks) or
            any(type(count) is not int or count < 0 for week in weeks for count in week)):
        raise ValueError('Expected seven non-negative integer counts per week and '
                         + ('53 fixture weeks' if fixture else '53 or 54 public weeks'))
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
    columns = len(weeks)
    width = 45 + columns * STEP
    points = [(30 + i * STEP, round(110 + 30 * math.sin(i * math.tau / 12)))
              for i in range(columns)]
    route = 'M' + 'L'.join(f'{x} {y}' for x, y in points)
    distances = [0.0]
    for previous, current in zip(points, points[1:]):
        distances.append(distances[-1] + math.dist(previous, current))
    visit_times = [(TRAVEL - FADE) * i / (columns - 1) for i in range(columns)]
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
    lines = ''.join(f'M23 {y}H{width - 23}' for y in range(60, 163, 24))
    total = sum(sum(week) for week in weeks)
    active = sum(count > 0 for week in weeks for count in week)
    backing = '<circle cy="-15" r="22" fill="#e6e3da" opacity=".9"/>' if theme == 'dark' else ''
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 {TOP} {width} {HEIGHT}">
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
  <mask id="trail" maskUnits="userSpaceOnUse" x="0" y="{TOP}" width="{width}" height="{HEIGHT}">
    <path class="trace" d="{route}" pathLength="1" fill="none" stroke="white"
      stroke-width="4" stroke-linejoin="round" stroke-dasharray="1" stroke-dashoffset="0"/>
  </mask>
</defs>
<rect y="{TOP}" width="{width}" height="{HEIGHT}" fill="{bg}"/>
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
<text x="{width - 24}" y="37" text-anchor="end" fill="{secondary}" font-family="monospace" font-size="18">{total} contributions · {active} active days</text>
</svg>
'''


def write_images(out, images):
    out.mkdir(parents=True, exist_ok=True)
    directory = os.open(out, os.O_RDONLY)
    try:
        fcntl.flock(directory, fcntl.LOCK_EX)
        replace_images(out, images)
    finally:
        os.close(directory)


def replace_images(out, images):
    targets = {out / f'pip-patrol-{theme}.svg': svg for theme, svg in images.items()}
    if not os.access(out, os.W_OK | os.X_OK):
        raise PermissionError(f'Cannot write to {out}')
    for target in targets:
        if target.is_symlink() or (target.exists() and
                                  (not target.is_file() or not os.access(target, os.W_OK))):
            raise OSError(f'Cannot replace {target}: expected a writable regular file')

    staging = Path(tempfile.mkdtemp(dir=out, prefix='.pip-patrol-'))
    replaced = []
    preserve_backups = False
    try:
        for target, svg in targets.items():
            (staging / target.name).write_bytes(svg)
            if target.exists():
                shutil.copy2(target, staging / f'{target.name}.bak')
        try:
            for target in targets:
                os.replace(staging / target.name, target)
                replaced.append(target)
        except OSError:
            preserve_backups = True
            for target in reversed(replaced):
                backup = staging / f'{target.name}.bak'
                try:
                    if backup.exists():
                        os.replace(backup, target)
                    else:
                        target.unlink()
                except OSError as error:
                    raise OSError(f'Could not restore {target}. Backups kept in {staging}: {error}') from error
            preserve_backups = False
            raise
    finally:
        if not preserve_backups:
            shutil.rmtree(staging)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path)
    parser.add_argument('--out', type=Path, default=ROOT / 'assets')
    args = parser.parse_args()
    try:
        weeks = load_calendar(args.fixture)
    except (AttributeError, KeyError, TypeError, ValueError, OSError) as error:
        parser.exit(1, f'Could not read the contribution calendar: {error}\n')

    pip = b64encode((ROOT / 'assets/pip-robot.png').read_bytes()).decode('ascii')
    images = {theme: render(weeks, pip, theme).encode('utf-8') for theme in PALETTES}
    if any(len(svg) > 300_000 for svg in images.values()):
        parser.exit(1, 'Pip patrol SVG exceeds 300 KB\n')
    try:
        write_images(args.out, images)
    except OSError as error:
        parser.exit(1, f'Could not write the SVGs: {error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
