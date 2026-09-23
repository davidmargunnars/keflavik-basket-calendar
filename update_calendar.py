import urllib.request
import datetime
import pathlib
import re
import html
import hashlib

OUT = pathlib.Path("keflavik-basket.ics")
BASE = "https://www.kki.is/motamal/leikir-og-urslit/motayfirlit"
LEAGUE_ID = 190  # Bónus deild karla
TARGET_SEASON = "2026-2027"
BOOTSTRAP = (
    f"{BASE}/Tolfraedi-leikmanna?"
    f"league_id={LEAGUE_ID}&season_id=undefined"
)


def fetch(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/153 Safari/537.36"
            ),
            "Accept-Language": "is-IS,is;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def clean(value):
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(
        html.unescape(value).replace("\xa0", " ").split()
    )


def ical_escape(value):
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def fold(line):
    data = line.encode("utf-8")
    output = []

    while len(data) > 73:
        cut = 73
        while cut > 0:
            try:
                part = data[:cut].decode("utf-8")
                break
            except UnicodeDecodeError:
                cut -= 1
        output.append(part)
        data = data[cut:]

    output.append(data.decode("utf-8"))
    return "\r\n ".join(output)


def season_candidates(page):
    candidates = []

    # Season links used around the KKÍ competition pages.
    candidates.extend(
        re.findall(r"season_id=(\d+)", page, flags=re.I)
    )

    # Season dropdown option containing the target season label.
    for option in re.findall(
        r"<option\b[^>]*>.*?</option>",
        page,
        flags=re.I | re.S,
    ):
        if TARGET_SEASON not in clean(option):
            continue
        match = re.search(
            r"\bvalue\s*=\s*[\"']?(\d+)",
            option,
            flags=re.I,
        )
        if match:
            candidates.insert(0, match.group(1))

    # Preserve order while removing duplicates and clearly invalid ids.
    unique = []
    seen = set()
    for value in candidates:
        if value in seen:
            continue
        seen.add(value)
        if int(value) > 1000:
            unique.append(value)
    return unique


def find_current_games_page():
    bootstrap = fetch(BOOTSTRAP)
    bootstrap_text = clean(bootstrap)

    if "Bónus deild karla" not in bootstrap_text:
        raise SystemExit(
            "Could not confirm Bónus deild karla on KKÍ. "
            "Calendar will NOT be overwritten."
        )

    candidates = season_candidates(bootstrap)
    if not candidates:
        raise SystemExit(
            "Could not discover a KKÍ season_id. "
            "Calendar will NOT be overwritten."
        )

    for season_id in candidates:
        url = (
            f"{BASE}/Leikir?league_id={LEAGUE_ID}"
            f"&season_id={season_id}"
        )
        try:
            page = fetch(url)
        except Exception as exc:
            print(f"Skipping season_id={season_id}: {exc}")
            continue

        page_text = clean(page)
        correct_competition = "Bónus deild karla" in page_text
        correct_season = TARGET_SEASON in page_text
        has_keflavik = "Keflavík" in page_text

        if correct_competition and correct_season and has_keflavik:
            print(
                f"Using KKÍ season_id={season_id} "
                f"for Bónus deild karla {TARGET_SEASON}"
            )
            return url, page

    raise SystemExit(
        "Could not find the current Bónus deild karla games page. "
        "Calendar will NOT be overwritten."
    )


SOURCE, page = find_current_games_page()
rows = re.findall(
    r"<tr\b[^>]*>(.*?)</tr>",
    page,
    flags=re.I | re.S,
)

events = []

for row in rows:
    cells = [
        clean(cell)
        for cell in re.findall(
            r"<t[dh]\b[^>]*>(.*?)</t[dh]>",
            row,
            flags=re.I | re.S,
        )
    ]

    if not cells:
        continue

    # KKÍ game rows are Date | Home | Score/Preview | Away | Venue.
    date_index = None
    date_match = None
    for i, cell in enumerate(cells):
        match = re.search(
            r"(\d{2})[-.](\d{2})[-.](20\d{2})"
            r"(?:\s+(\d{1,2}):(\d{2}))?",
            cell,
        )
        if match:
            date_index = i
            date_match = match
            break

    if date_index is None or date_match is None:
        continue

    # We need Home, middle status/score, Away after the date column.
    if len(cells) <= date_index + 3:
        continue

    home = cells[date_index + 1].strip()
    away = cells[date_index + 3].strip()
    venue = (
        cells[date_index + 4].strip()
        if len(cells) > date_index + 4
        else ""
    )

    # Only the Keflavík men's first team. Exact name prevents b/youth teams.
    if home != "Keflavík" and away != "Keflavík":
        continue

    day, month, year = map(int, date_match.group(1, 2, 3))
    hour = int(date_match.group(4) or 0)
    minute = int(date_match.group(5) or 0)

    # A game without a published tip-off time is not safe to add yet.
    if date_match.group(4) is None:
        continue

    start = datetime.datetime(
        year,
        month,
        day,
        hour,
        minute,
        tzinfo=datetime.timezone.utc,
    )

    uid_source = (
        f"{year}-{month}-{day}-{hour}-{minute}-{home}-{away}"
    )
    uid = hashlib.sha1(
        uid_source.encode("utf-8")
    ).hexdigest()[:16]

    events.append(
        {
            "start": start,
            "home": home,
            "away": away,
            "venue": venue,
            "uid": uid,
        }
    )

# Remove duplicates.
unique = {}
for event in events:
    key = (
        event["start"],
        event["home"],
        event["away"],
    )
    unique[key] = event

events = sorted(
    unique.values(),
    key=lambda event: event["start"],
)

# Never overwrite a working calendar with an empty one if KKÍ changes HTML.
if not events:
    raise SystemExit(
        "No Keflavík MEN Bónus deild games found. "
        "Calendar will NOT be overwritten."
    )

now = datetime.datetime.now(
    datetime.timezone.utc
).strftime("%Y%m%dT%H%M%SZ")

lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Keflavik Basket Calendar//IS",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "X-WR-CALNAME:Keflavík – Bónus deild karla",
    "X-WR-TIMEZONE:Atlantic/Reykjavik",
    "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
    "X-PUBLISHED-TTL:PT6H",
]

for event in events:
    start = event["start"]
    end = start + datetime.timedelta(hours=2)

    lines += [
        "BEGIN:VEVENT",
        (
            f"UID:kki-{event['uid']}"
            "@keflavik-basket-calendar"
        ),
        f"DTSTAMP:{now}",
        f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}",
        f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}",
        (
            "SUMMARY:🏀 "
            f"{ical_escape(event['home'])} – "
            f"{ical_escape(event['away'])}"
        ),
        (
            "DESCRIPTION:Bónus deild karla – "
            "opinber leikjadagskrá KKÍ"
        ),
    ]

    if event["venue"]:
        lines.append(
            f"LOCATION:{ical_escape(event['venue'])}"
        )

    lines += [
        f"URL:{SOURCE}",
        "STATUS:CONFIRMED",
        "END:VEVENT",
    ]

lines.append("END:VCALENDAR")

OUT.write_text(
    "\r\n".join(fold(line) for line in lines)
    + "\r\n",
    encoding="utf-8",
)

print(
    f"Wrote {len(events)} Keflavík MEN "
    f"Bónus deild games from KKÍ to {OUT}"
)
