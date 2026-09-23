import datetime
import hashlib
import html
import pathlib
import re
import time

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options

OUT = pathlib.Path("keflavik-basket.ics")
LEAGUE_ID = 190  # Bónus deild karla
TARGET_SEASON = "2026-2027"
SOURCE = (
    "https://www.kki.is/motamal/leikir-og-urslit/"
    "motayfirlit/Leikir?league_id=190&season_id=undefined"
)


def clean(value):
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(
        html.unescape(value).replace("\xa0", " ").split()
    )


def render_current_games_page():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1440,1200")
    options.add_argument("--lang=is-IS")
    options.page_load_strategy = "eager"

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(25)

    try:
        try:
            driver.get(SOURCE)
        except TimeoutException:
            # KKÍ can keep background requests open. The useful DOM may still
            # be fully rendered, so stop navigation and inspect it ourselves.
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass

        # Wait for KKÍ's competition widget to populate. We deliberately
        # validate both competition and season before writing anything.
        page = ""
        for _ in range(20):
            page = driver.page_source
            text = clean(page)
            if (
                "Bónus deild karla" in text
                and TARGET_SEASON in text
                and "Keflavík" in text
                and re.search(r"\d{2}[-.]\d{2}[-.]20\d{2}", text)
            ):
                return page
            time.sleep(1)

        print("Rendered page title:", driver.title)
        print("Rendered URL:", driver.current_url)
        print("Rendered text sample:", clean(page)[:1500])
        raise SystemExit(
            "KKÍ did not render current Bónus deild karla games. "
            "Calendar will NOT be overwritten."
        )
    finally:
        driver.quit()


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


page = render_current_games_page()
page_text = clean(page)

if "Bónus deild karla" not in page_text or TARGET_SEASON not in page_text:
    raise SystemExit(
        "Wrong KKÍ competition or season. Calendar will NOT be overwritten."
    )

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

    date_index = None
    date_match = None
    for index, cell in enumerate(cells):
        match = re.search(
            r"(\d{2})[-.](\d{2})[-.](20\d{2})\s+"
            r"(\d{1,2}):(\d{2})",
            cell,
        )
        if match:
            date_index = index
            date_match = match
            break

    if date_index is None or date_match is None:
        continue

    # KKÍ's games table is Date | Home | Score/Preview | Away | Venue.
    if len(cells) <= date_index + 3:
        continue

    home = cells[date_index + 1].strip()
    away = cells[date_index + 3].strip()
    venue = (
        cells[date_index + 4].strip()
        if len(cells) > date_index + 4
        else ""
    )

    # Exact team name is intentional: only Keflavík men's first team,
    # never Keflavík b, youth teams, or women's teams.
    if home != "Keflavík" and away != "Keflavík":
        continue

    day, month, year, hour, minute = map(int, date_match.groups())
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
    uid = hashlib.sha1(uid_source.encode("utf-8")).hexdigest()[:16]

    events.append(
        {
            "start": start,
            "home": home,
            "away": away,
            "venue": venue,
            "uid": uid,
        }
    )

# Remove duplicate rows if KKÍ includes the same game in multiple sections.
unique = {}
for event in events:
    key = (event["start"], event["home"], event["away"])
    unique[key] = event

events = sorted(unique.values(), key=lambda event: event["start"])

if not events:
    print("Found rows:", len(rows))
    raise SystemExit(
        "No Keflavík MEN Bónus deild games found. "
        "Calendar will NOT be overwritten."
    )

now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

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
        f"UID:kki-{event['uid']}@keflavik-basket-calendar",
        f"DTSTAMP:{now}",
        f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}",
        f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}",
        (
            "SUMMARY:🏀 "
            f"{ical_escape(event['home'])} – "
            f"{ical_escape(event['away'])}"
        ),
        "DESCRIPTION:Bónus deild karla – opinber leikjadagskrá KKÍ",
    ]

    if event["venue"]:
        lines.append(f"LOCATION:{ical_escape(event['venue'])}")

    lines += [
        f"URL:{SOURCE}",
        "STATUS:CONFIRMED",
        "END:VEVENT",
    ]

lines.append("END:VCALENDAR")

OUT.write_text(
    "\r\n".join(fold(line) for line in lines) + "\r\n",
    encoding="utf-8",
)

print(
    f"Wrote {len(events)} Keflavík MEN "
    f"Bónus deild games from KKÍ to {OUT}"
)
