"""Generate the profile stats, activity and trophy SVGs from the GitHub GraphQL API.

Usage: GITHUB_TOKEN=... python scripts/stats.py [login]

With a token that belongs to the profile owner (STATS_TOKEN in CI), private
contributions and languages are included. Repository names are never written
to the output.
"""

import json
import math
import os
import sys
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path

LOGIN = sys.argv[1] if len(sys.argv) > 1 else "ATICHOF"
TOKEN = os.environ.get("STATS_TOKEN") or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
OUT = Path(__file__).resolve().parent.parent / "assets"

NAVY, NAVY_LIGHT, CREAM, TEAL, TEAL_LIGHT, ORANGE, MUTED = "#0B2540", "#123456", "#F5F1EA", "#0E7490", "#5EC4D6", "#E07B39", "#8A99AB"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"
SERIF = "Georgia, 'Times New Roman', Times, serif"

IGNORED_LANGUAGES = {"TeX", "HTML", "CSS", "SCSS", "Makefile", "Dockerfile"}
LANGUAGE_PALETTE = [TEAL_LIGHT, ORANGE, CREAM, "#3B82A6", "#C9A86A", MUTED]

# name, light, dark
TIERS = [
    ("BRONZE", "#E3A574", "#A8643A"),
    ("SILVER", "#E4EAF0", "#8E9BA8"),
    ("GOLD", "#F6D27A", "#C9952B"),
    ("PLATINUM", "#A7EEF7", "#3BA8BC"),
]


# --------------------------------------------------------------------------- data

def gql(query, **variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as res:
        payload = json.load(res)
    if payload.get("errors"):
        raise SystemExit(payload["errors"])
    return payload["data"]


COLLECTION = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    createdAt
    contributionsCollection(from: $from, to: $to) {
      contributionYears
      totalCommitContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      contributionCalendar { totalContributions weeks { contributionDays { date contributionCount } } }
      commitContributionsByRepository(maxRepositories: 100) {
        contributions { totalCount }
        repository { primaryLanguage { name } }
      }
    }
  }
}
"""


def collection(start, end):
    return gql(COLLECTION, login=LOGIN, **{"from": start.isoformat(), "to": end.isoformat()})["user"]


def fetch():
    now = datetime.now(timezone.utc)
    recent = collection(now - timedelta(days=365), now)
    c = recent["contributionsCollection"]

    days = {}
    languages = Counter()
    for year in c["contributionYears"]:
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end = min(datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc), now)
        yc = collection(start, end)["contributionsCollection"]
        for week in yc["contributionCalendar"]["weeks"]:
            for d in week["contributionDays"]:
                days[d["date"]] = d["contributionCount"]
        for item in yc["commitContributionsByRepository"]:
            lang = item["repository"]["primaryLanguage"]
            if lang and lang["name"] not in IGNORED_LANGUAGES:
                languages[lang["name"]] += item["contributions"]["totalCount"]

    recent_days = {}
    for week in c["contributionCalendar"]["weeks"]:
        for d in week["contributionDays"]:
            recent_days[d["date"]] = d["contributionCount"]

    return dict(
        created=datetime.fromisoformat(recent["createdAt"].replace("Z", "+00:00")),
        commits=c["totalCommitContributions"],
        prs=c["totalPullRequestContributions"],
        days=days,
        recent_days=recent_days,
        languages=languages,
        today=now.date(),
    )


def streaks(days, today):
    longest = run = 0
    prev = None
    for key in sorted(days):
        d = date.fromisoformat(key)
        if d > today:
            continue
        if days[key] > 0:
            run = run + 1 if prev and (d - prev).days == 1 else 1
            prev = d
            longest = max(longest, run)
    current = 0
    d = today if days.get(today.isoformat(), 0) > 0 else today - timedelta(days=1)
    while days.get(d.isoformat(), 0) > 0:
        current += 1
        d -= timedelta(days=1)
    return current, longest


def monthly(days, today, offset=0):
    """Totals for the 12 calendar months ending `offset` years before this month."""
    months = []
    y, m = today.year - offset, today.month
    for _ in range(12):
        months.append((y, m))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    months.reverse()
    totals = Counter()
    for key, count in days.items():
        d = date.fromisoformat(key)
        totals[(d.year, d.month)] += count
    return [(date(y, m, 1).strftime("%b").upper(), totals[(y, m)]) for y, m in months]


def weekly(recent_days):
    counts = [recent_days[k] for k in sorted(recent_days)]
    return [sum(counts[i:i + 7]) for i in range(0, len(counts), 7)]


# --------------------------------------------------------------------------- drawing helpers

def fmt(n):
    return f"{n:,}"


BASE_STYLE = f"""
  .mono {{ font-family: {MONO}; }}
  .serif {{ font-family: {SERIF}; }}
  .pulse {{ animation: pulse 2.2s ease-in-out infinite; }}
  @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: .35; }} }}
"""


def frame(w, h, label, inner, defs="", style=""):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{escape(label)}">
  <style>{BASE_STYLE}{style}</style>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{NAVY_LIGHT}"/><stop offset="1" stop-color="{NAVY}"/>
    </linearGradient>
    <pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse">
      <circle cx="1" cy="1" r="1" fill="{TEAL_LIGHT}" fill-opacity=".07"/>
    </pattern>
    <radialGradient id="glow" cx="1" cy="0" r="1">
      <stop offset="0" stop-color="{TEAL_LIGHT}" stop-opacity=".14"/><stop offset="1" stop-color="{TEAL_LIGHT}" stop-opacity="0"/>
    </radialGradient>{defs}
  </defs>
  <rect width="{w}" height="{h}" rx="18" fill="url(#bg)"/>
  <rect width="{w}" height="{h}" rx="18" fill="url(#dots)"/>
  <rect width="{w}" height="{h}" rx="18" fill="url(#glow)"/>
  <rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="18" fill="none" stroke="{TEAL_LIGHT}" stroke-opacity=".2"/>
{inner}
</svg>
"""


def heading(x, y, text, right=None, right_x=None):
    out = f'  <text x="{x}" y="{y}" class="mono" font-size="12" letter-spacing="2.5" fill="{TEAL_LIGHT}">{escape(text)}</text>'
    if right:
        out += f'\n  <text x="{right_x}" y="{y}" text-anchor="end" class="mono" font-size="11" letter-spacing="2" fill="{MUTED}">{escape(right)}</text>'
    return out


def smooth(pts):
    """Catmull-Rom spline through the points, as an SVG path. Control points stay within the data range."""
    lo, hi = min(y for _, y in pts), max(y for _, y in pts)
    clamp = lambda y: min(max(y, lo), hi)
    d = f"M{pts[0][0]:.1f} {pts[0][1]:.1f}"
    for i in range(len(pts) - 1):
        p0, p1, p2 = pts[max(i - 1, 0)], pts[i], pts[i + 1]
        p3 = pts[min(i + 2, len(pts) - 1)]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, clamp(p1[1] + (p2[1] - p0[1]) / 6))
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, clamp(p2[1] - (p3[1] - p1[1]) / 6))
        d += f" C{c1[0]:.1f} {c1[1]:.1f} {c2[0]:.1f} {c2[1]:.1f} {p2[0]:.1f} {p2[1]:.1f}"
    return d


def arc(cx, cy, r, start, end):
    """SVG arc path between two angles in degrees (0 = 12 o'clock, clockwise)."""
    a0, a1 = math.radians(start - 90), math.radians(end - 90)
    x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
    x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
    large = 1 if end - start > 180 else 0
    return f"M{x0:.2f} {y0:.2f} A{r} {r} 0 {large} 1 {x1:.2f} {y1:.2f}"


# --------------------------------------------------------------------------- cards

def stats_svg(s, current, longest, active):
    all_time = sum(s["days"].values())
    years = (s["today"] - s["created"].date()).days // 365

    weeks = weekly(s["recent_days"])
    series = [sum(weeks[i:i + 2]) for i in range(0, len(weeks), 2)]
    peak = max(series) or 1
    x0, x1, top, bottom = 330, 560, 70, 132
    step = (x1 - x0) / (len(series) - 1)
    pts = [(x0 + i * step, bottom - (bottom - top) * n / peak) for i, n in enumerate(series)]
    line = smooth(pts)
    area = f"{line} L{x1} {bottom} L{x0} {bottom} Z"
    lx, ly = pts[-1]

    tiles = [
        ("COMMITS · 12M", fmt(s["commits"]), ""),
        ("PULL REQUESTS · 12M", fmt(s["prs"]), ""),
        ("ACTIVE DAYS · 12M", fmt(active), ""),
        ("CURRENT STREAK", f"{current}", "DAYS"),
        ("LONGEST STREAK", f"{longest}", "DAYS"),
        ("ON GITHUB", f"{years}", "YEARS"),
    ]
    cells = []
    for i, (label, value, unit) in enumerate(tiles):
        x = 40 + (i % 3) * 176
        y = 172 + (i // 3) * 66
        cells.append(f"""  <rect x="{x}" y="{y}" width="164" height="56" rx="10" fill="{CREAM}" fill-opacity=".03" stroke="{TEAL_LIGHT}" stroke-opacity=".14"/>
  <text x="{x + 14}" y="{y + 22}" class="mono" font-size="9.5" letter-spacing="1.5" fill="{MUTED}">{label}</text>
  <text x="{x + 14}" y="{y + 45}" class="serif" font-size="22" fill="{CREAM}">{value}<tspan class="mono" font-size="10" letter-spacing="1.5" fill="{MUTED}" dx="6">{unit}</tspan></text>""")

    defs = f"""
    <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{TEAL_LIGHT}" stop-opacity=".35"/><stop offset="1" stop-color="{TEAL_LIGHT}" stop-opacity="0"/>
    </linearGradient>"""
    style = """
  .trace { stroke-dasharray: 10 400; animation: trace 4s linear infinite; }
  @keyframes trace { from { stroke-dashoffset: 0; } to { stroke-dashoffset: -410; } }
"""
    inner = f"""{heading(40, 48, "BY THE NUMBERS", "LAST 52 WEEKS", 560)}
  <text x="40" y="118" class="serif" font-size="60" fill="{CREAM}">{fmt(all_time)}<tspan fill="{ORANGE}">.</tspan></text>
  <text x="40" y="144" class="mono" font-size="10.5" letter-spacing="2" fill="{MUTED}">SINCE {s['created'].year} · PRIVATE INCLUDED</text>
  <path d="{area}" fill="url(#area)"/>
  <path d="{line}" fill="none" stroke="{TEAL_LIGHT}" stroke-width="1.8" stroke-linejoin="round"/>
  <path d="{line}" fill="none" stroke="{CREAM}" stroke-width="2.6" stroke-linecap="round" class="trace"/>
  <circle cx="{lx:.1f}" cy="{ly:.1f}" r="8" fill="{ORANGE}" fill-opacity=".25" class="pulse"/>
  <circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.5" fill="{ORANGE}"/>
{chr(10).join(cells)}"""
    return frame(600, 320, "Contribution stats", inner, defs, style)


def languages_svg(s):
    total = sum(s["languages"].values()) or 1
    top = s["languages"].most_common(5)
    rest = total - sum(n for _, n in top)
    entries = top + ([("Other", rest)] if rest else [])

    cx, cy, r = 150, 186, 74
    segments, legend, angle = [], [], 0.0
    for i, (name, n) in enumerate(entries):
        color = LANGUAGE_PALETTE[i % len(LANGUAGE_PALETTE)] if name != "Other" else MUTED
        sweep = 360 * n / total
        gap = 2.5 if len(entries) > 1 else 0
        if sweep - gap > 0.4:
            segments.append(f'  <path d="{arc(cx, cy, r, angle + gap / 2, angle + sweep - gap / 2)}" fill="none" stroke="{color}" stroke-width="18" stroke-linecap="butt"/>')
        angle += sweep
        if i < 5:
            y = 112 + i * 40
            pct = 100 * n / total
            legend.append(f"""  <circle cx="300" cy="{y - 5}" r="5" fill="{color}"/>
  <text x="316" y="{y}" class="serif" font-size="18" fill="{CREAM}">{escape(name)}</text>
  <text x="560" y="{y}" text-anchor="end" class="serif" font-size="18" fill="{CREAM}">{pct:.0f}<tspan class="mono" font-size="11" fill="{MUTED}">%</tspan></text>
  <rect x="316" y="{y + 10}" width="244" height="3" rx="1.5" fill="{TEAL_LIGHT}" fill-opacity=".1"/>
  <rect x="316" y="{y + 10}" width="{max(244 * pct / 100, 3):.1f}" height="3" rx="1.5" fill="{color}"/>""")

    style = f"""
  .orbit {{ transform-origin: {cx}px {cy}px; animation: orbit 9s linear infinite; }}
  @keyframes orbit {{ to {{ transform: rotate(360deg); }} }}
"""
    inner = f"""{heading(40, 48, "LANGUAGES", "BY COMMITS", 560)}
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{TEAL_LIGHT}" stroke-opacity=".08" stroke-width="18"/>
{chr(10).join(segments)}
  <circle cx="{cx}" cy="{cy}" r="{r + 20}" fill="none" stroke="{TEAL_LIGHT}" stroke-opacity=".15" stroke-dasharray="2 6"/>
  <g class="orbit"><circle cx="{cx}" cy="{cy - r - 20}" r="4" fill="{ORANGE}"/></g>
  <text x="{cx}" y="{cy + 8}" text-anchor="middle" class="serif" font-size="40" fill="{CREAM}">{len(s['languages'])}</text>
  <text x="{cx}" y="{cy + 28}" text-anchor="middle" class="mono" font-size="9.5" letter-spacing="2" fill="{MUTED}">LANGUAGES</text>
{chr(10).join(legend)}"""
    return frame(600, 320, "Top languages", inner, style=style)


def activity_svg(months, previous_total):
    peak = max((n for _, n in months), default=1) or 1
    total = sum(n for _, n in months)
    avg = total / len(months)
    w, h = 1200, 350
    left, right, base, height = 96, 1136, 278, 160
    slot = (right - left) / len(months)
    scale = lambda n: base - height * n / peak

    grid = []
    for frac in (0, .5, 1):
        y = base - height * frac
        grid.append(f'  <line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="{TEAL_LIGHT}" stroke-opacity="{.25 if frac == 0 else .08}"/>')
        grid.append(f'  <text x="{left - 14}" y="{y + 4:.1f}" text-anchor="end" class="mono" font-size="10" fill="{MUTED}">{round(peak * frac)}</text>')

    bars = []
    for i, (label, n) in enumerate(months):
        bh = max(height * n / peak, 4)
        bw = slot * .5
        x = left + i * slot + (slot - bw) / 2
        best = n == peak
        bars.append(f'  <rect x="{x:.1f}" y="{base - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="6" fill="url(#{"best" if best else "bar"})" class="bar" style="animation-delay:{i * .12:.2f}s"/>')
        if best:
            px = x + bw / 2
            bars.append(f"""  <g>
    <rect x="{px - 62:.1f}" y="{base - bh - 40:.1f}" width="124" height="26" rx="13" fill="{ORANGE}" fill-opacity=".15" stroke="{ORANGE}" stroke-opacity=".6"/>
    <text x="{px:.1f}" y="{base - bh - 22.5:.1f}" text-anchor="middle" class="mono" font-size="11" letter-spacing="1.5" fill="{CREAM}">BEST · {n}</text>
  </g>""")
        else:
            bars.append(f'  <text x="{x + bw / 2:.1f}" y="{base - bh - 10:.1f}" text-anchor="middle" class="mono" font-size="11" fill="{MUTED}">{n}</text>')
        bars.append(f'  <text x="{x + bw / 2:.1f}" y="{base + 26}" text-anchor="middle" class="mono" font-size="11" letter-spacing="1.5" fill="{CREAM if best else MUTED}">{label}</text>')

    ay = scale(avg)
    trend = ""
    if previous_total:
        change = (total - previous_total) / previous_total * 100
        arrow, color = ("▲", TEAL_LIGHT) if change >= 0 else ("▼", ORANGE)
        trend = f'<tspan fill="{color}" dx="14">{arrow} {abs(change):.0f}% VS PRIOR YEAR</tspan>'

    defs = f"""
    <linearGradient id="bar" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{TEAL_LIGHT}"/><stop offset="1" stop-color="{TEAL}" stop-opacity=".55"/>
    </linearGradient>
    <linearGradient id="best" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#F2A066"/><stop offset="1" stop-color="{ORANGE}" stop-opacity=".6"/>
    </linearGradient>"""
    style = """
  .bar { transform-box: fill-box; transform-origin: bottom; animation: wave 2.8s ease-in-out infinite; }
  @keyframes wave { 0%, 100% { transform: scaleY(1); } 50% { transform: scaleY(.9); } }
  .avg { stroke-dasharray: 6 6; animation: march 1.5s linear infinite; }
  @keyframes march { to { stroke-dashoffset: -12; } }
"""
    inner = f"""  <text x="64" y="52" class="mono" font-size="12" letter-spacing="2.5" fill="{TEAL_LIGHT}">LAST 12 MONTHS</text>
  <text x="1136" y="52" text-anchor="end" class="mono" font-size="12" letter-spacing="2" fill="{MUTED}">{fmt(total)} CONTRIBUTIONS{trend}</text>
{chr(10).join(grid)}
{chr(10).join(bars)}
  <line x1="{left}" y1="{ay:.1f}" x2="{right}" y2="{ay:.1f}" stroke="{ORANGE}" stroke-opacity=".7" stroke-width="1.5" class="avg"/>
  <rect x="{left + 6}" y="{ay - 24:.1f}" width="118" height="18" rx="9" fill="{NAVY}" stroke="{ORANGE}" stroke-opacity=".5"/>
  <text x="{left + 65}" y="{ay - 11.5:.1f}" text-anchor="middle" class="mono" font-size="9.5" letter-spacing="1.5" fill="{ORANGE}">AVG {avg:.0f} / MONTH</text>"""
    return frame(w, h, "Monthly contributions", inner, defs, style)


# --------------------------------------------------------------------------- trophies

ICONS = {
    "spark": '<path d="M0 -15 L4.5 -4.5 L15 0 L4.5 4.5 L0 15 L-4.5 4.5 L-15 0 L-4.5 -4.5 Z"/>',
    "commit": '<circle r="6.5"/><rect x="-17" y="-1.75" width="9" height="3.5" rx="1.5"/><rect x="8" y="-1.75" width="9" height="3.5" rx="1.5"/>',
    "merge": '<circle cx="-7" cy="-11" r="4.5"/><circle cx="-7" cy="11" r="4.5"/><circle cx="9" cy="0" r="4.5"/><rect x="-8.75" y="-7" width="3.5" height="14"/><path d="M-7 -6 Q-7 0 5 0" fill="none" stroke-width="3.5"/>',
    "flame": '<path d="M0 -16 C7 -6 12 -2 12 5 A12 12 0 0 1 -12 5 C-12 -1 -6 -3 -4 -10 C-2 -4 0 -3 2 -1 C3 -7 1 -12 0 -16 Z"/>',
    "calendar": '<rect x="-13" y="-10" width="26" height="23" rx="3.5" fill="none" stroke-width="3"/><rect x="-13" y="-10" width="26" height="7" rx="2"/><rect x="-7" y="-16" width="3.5" height="8" rx="1.5"/><rect x="3.5" y="-16" width="3.5" height="8" rx="1.5"/>',
    "clock": '<circle r="13" fill="none" stroke-width="3"/><path d="M0 -7 V0 L5 4" fill="none" stroke-width="3" stroke-linecap="round"/>',
    "code": '<path d="M-6 -10 L-15 0 L-6 10 M6 -10 L15 0 L6 10" fill="none" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>',
}


def grade(value, thresholds):
    level = sum(value >= t for t in thresholds) - 1
    if level < 0:
        return None
    if level == len(thresholds) - 1:
        return level, 1.0, None
    lo, hi = thresholds[level], thresholds[level + 1]
    return level, (value - lo) / (hi - lo), hi


def trophies_svg(s, longest, active):
    years = (s["today"] - s["created"].date()).days // 365
    all_time = sum(s["days"].values())
    items = [
        ("CONTRIBUTOR", all_time, fmt(all_time), "all-time", [250, 1000, 2000, 5000], "spark", fmt),
        ("COMMITTER", s["commits"], fmt(s["commits"]), "commits / yr", [100, 300, 700, 1500], "commit", fmt),
        ("SHIPPER", s["prs"], fmt(s["prs"]), "PRs / yr", [10, 50, 150, 400], "merge", fmt),
        ("ON FIRE", longest, f"{longest}d", "best streak", [7, 14, 30, 60], "flame", lambda n: f"{n}d"),
        ("CONSISTENT", active, fmt(active), "active days / yr", [50, 100, 200, 300], "calendar", fmt),
        ("VETERAN", years, f"{years}y", "on GitHub", [1, 3, 5, 8], "clock", lambda n: f"{n}y"),
        ("POLYGLOT", len(s["languages"]), str(len(s["languages"])), "languages", [2, 4, 6, 8], "code", str),
    ]
    graded = [(t, v, d, c, grade(v, th), icon, f) for t, v, d, c, th, icon, f in items]
    graded = [g for g in graded if g[4]]

    defs = []
    for i, (name, light, dark) in enumerate(TIERS):
        defs.append(f"""
    <linearGradient id="t{i}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{light}"/><stop offset="1" stop-color="{dark}"/>
    </linearGradient>
    <radialGradient id="f{i}" cx=".5" cy=".35" r=".7">
      <stop offset="0" stop-color="{light}" stop-opacity=".28"/><stop offset="1" stop-color="{dark}" stop-opacity=".04"/>
    </radialGradient>""")
    defs.append("""
    <linearGradient id="shine" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".35"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>
    </linearGradient>
    <clipPath id="hex"><polygon points="0,-34 29.4,-17 29.4,17 0,34 -29.4,17 -29.4,-17"/></clipPath>""")

    slot = 1120 / len(graded)
    r = 46
    circ = 2 * math.pi * r
    cards = []
    for n, (title, value, shown, caption, (level, progress, nxt), icon, f) in enumerate(graded):
        name, light, dark = TIERS[level]
        cx = 40 + slot * n + slot / 2
        next_line = f"NEXT · {f(nxt)}" if nxt else "MAX TIER"
        cards.append(f"""  <g transform="translate({cx:.1f} 0)">
    <g transform="translate(0 120)">
      <circle r="{r}" fill="none" stroke="{TEAL_LIGHT}" stroke-opacity=".1" stroke-width="4"/>
      <circle r="{r}" fill="none" stroke="url(#t{level})" stroke-width="4" stroke-linecap="round" stroke-dasharray="{circ * max(progress, .02):.1f} {circ:.1f}" transform="rotate(-90)"/>
      <g class="medal" style="animation-delay:{n * .3:.1f}s">
        <polygon points="0,-34 29.4,-17 29.4,17 0,34 -29.4,17 -29.4,-17" fill="url(#f{level})" stroke="url(#t{level})" stroke-width="2"/>
        <g fill="url(#t{level})" stroke="url(#t{level})">{ICONS[icon]}</g>
        <g clip-path="url(#hex)"><rect x="-90" y="-40" width="34" height="80" fill="url(#shine)" transform="skewX(-20)" class="shine" style="animation-delay:{n * .45:.2f}s"/></g>
      </g>
    </g>
    <text y="206" text-anchor="middle" class="serif" font-size="28" fill="{CREAM}">{shown}</text>
    <text y="226" text-anchor="middle" class="mono" font-size="9.5" letter-spacing="1.5" fill="{MUTED}">{escape(caption.upper())}</text>
    <text y="256" text-anchor="middle" class="mono" font-size="11.5" letter-spacing="2.5" fill="{TEAL_LIGHT}">{title}</text>
    <rect x="-38" y="268" width="76" height="20" rx="10" fill="url(#f{level})" stroke="url(#t{level})" stroke-width="1"/>
    <text y="282" text-anchor="middle" class="mono" font-size="9.5" letter-spacing="2" fill="{light}">{name}</text>
    <text y="308" text-anchor="middle" class="mono" font-size="8.5" letter-spacing="1.5" fill="{MUTED}" fill-opacity=".8">{next_line}</text>
  </g>""")

    style = """
  .medal { animation: float 3.4s ease-in-out infinite; }
  @keyframes float { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-4px); } }
  .shine { animation: shine 4.5s ease-in-out infinite; }
  @keyframes shine { 0%, 60% { transform: skewX(-20deg) translateX(0); } 100% { transform: skewX(-20deg) translateX(190px); } }
"""
    inner = f"""{heading(40, 44, "ACHIEVEMENTS", "RING = PROGRESS TO NEXT TIER", 1160)}
{chr(10).join(cards)}"""
    return frame(1200, 340, "Achievements", inner, "".join(defs), style)


# --------------------------------------------------------------------------- main

def main():
    if not TOKEN:
        raise SystemExit("Set STATS_TOKEN or GITHUB_TOKEN")
    s = fetch()
    current, longest = streaks(s["days"], s["today"])
    active = sum(1 for n in s["recent_days"].values() if n > 0)
    previous = sum(n for _, n in monthly(s["days"], s["today"], offset=1))
    OUT.mkdir(exist_ok=True)
    (OUT / "stats.svg").write_text(stats_svg(s, current, longest, active))
    (OUT / "languages.svg").write_text(languages_svg(s))
    (OUT / "activity.svg").write_text(activity_svg(monthly(s["days"], s["today"]), previous))
    (OUT / "trophies.svg").write_text(trophies_svg(s, longest, active))
    print(f"all-time={sum(s['days'].values())} commits={s['commits']} prs={s['prs']} current={current} "
          f"longest={longest} active={active} previous_year={previous} languages={dict(s['languages'].most_common(6))}")


if __name__ == "__main__":
    main()
