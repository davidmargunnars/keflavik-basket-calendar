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
TARGET_SEASON = "2026-2027"
SOURCE = (
    "https://www.kki.is/motamal/leikir-og-urslit/"
    "motayfirlit/Leikir?league_id=190&season_id=undefined"
)


def clean(value):
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).replace("\xa0", " ").split())


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
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass

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


def extract_team_links(row):
    """Return team names linked from one KKÍ game row, in display order."""
    teams = []
    anchors = re.findall(
        r"<a\b([^>]*)>(.*?)</a>", row, flags=re.I | re.S
    )

    for attrs, body in anchors:
        href_match = re.search(
            r"href\s*=\s*[\"']([^\"']+)", attrs, flags=re.I
        )
        if not href_match:
            continue

        href = html.unescape(href_match.group(1)).lower()
        if "team_id=" not in href and "eitt-lid" not in href:
            continue

        name = clean(body).strip()
        if name and (not teams or teams[-1] != name):
            teams.append(name)

    return teams


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

rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", page, flags=re.I | re.S)
events = []
keflavik_debug = []

for row in rows:
    row_text = clean(row)
    if "Keflavík" not in row_text:
        continue

    cells = [
        clean(cell)
        for cell in re.findall(
            r"<t[dh]\b[^>]*>(.*?)</t[dh]>",
            row,
            flags=re.I | re.S,
        )
    ]

    date_match = re.search(
        r"(\d{2})[-.](\d{2})[-.](20\d{2})\s+(\d{1,2}):(\d{2})",
        row_text,
    )
    if not date_match:
        continue

    teams = extract_team_links(row)
    keflavik_debug.append((cells, teams))

    # The team pages are the most stable identifiers in KKÍ's rendered rows.
    # A normal game row contains the home-team link first and away-team link second.
    if len(teams) < 2:
        continue

    home = teams[0].strip()
    away = teams[1].strip()

    # We have already verified this is Bónus deild karla, so any Keflavík
    # team link on this page is the men's first team.
    if "Keflavík" not in home and "Keflavík" not in away:
        continue

    # Normalize the exact calendar display name while retaining opponent names.
    if "Keflavík" in home:
        home = "Keflavík"
    if "Keflavík" in away:
        away = "Keflavík"

    venue = cells[-1].strip() if cells else ""
    if venue in {home, away, "Sýnishorn"}:
        venue = ""

    day, month, year, hour, minute = map(int, date_match.groups())
    start = datetime.datetime(
        year,
        month,
        day,
        hour,
        minute,
        tzinfo=datetime.timezone.utc,
    )

    uid_source = f"{year}-{month}-{day}-{hour}-{minute}-{home}-{away}"
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

unique = {}
for event in events:
    key = (event["start"], event["home"], event["away"])
    unique[key] = event

events = sorted(unique.values(), key=lambda event: event["start"])

if not events:
    print("Found table rows:", len(rows))
    for cells, teams in keflavik_debug[:8]:
        print("KEFLAVIK ROW CELLS:", repr(cells))
        print("KEFLAVIK TEAM LINKS:", repr(teams))
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
