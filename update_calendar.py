import datetime
import hashlib
import html
import pathlib
import re
import time
from urllib.parse import urljoin

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options

OUT = pathlib.Path("keflavik-basket.ics")
TARGET_SEASON = "2026-2027"
LEAGUE_URL = (
    "https://www.kki.is/motamal/leikir-og-urslit/"
    "motayfirlit/Leikir?league_id=190&season_id=undefined"
)


def clean(value):
    # Script/style contents can sit inside table cells on KKÍ; remove the
    # entire elements before stripping the remaining HTML tags.
    value = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        " ",
        value,
        flags=re.I | re.S,
    )
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).replace("\xa0", " ").split())


def make_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1440,1600")
    options.add_argument("--lang=is-IS")
    options.page_load_strategy = "eager"

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(25)
    return driver


def load_and_wait(driver, url, required_strings):
    try:
        driver.get(url)
    except TimeoutException:
        try:
            driver.execute_script("window.stop();")
        except Exception:
            pass

    page = ""
    last_date_count = -1
    stable_count = 0

    for _ in range(30):
        page = driver.page_source
        text = clean(page)
        date_count = len(
            re.findall(r"\d{2}[-.]\d{2}[-.]20\d{2}\s+\d{1,2}:\d{2}", text)
        )

        ready = all(required in text for required in required_strings)
        if ready and date_count > 0:
            # Give KKÍ's JS enough time to finish adding rows. Returning only
            # when the number of dated rows has stopped changing avoids taking
            # a partial snapshot of the schedule.
            try:
                driver.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight);"
                )
            except Exception:
                pass

            if date_count == last_date_count:
                stable_count += 1
            else:
                stable_count = 0

            if stable_count >= 3:
                return page

        last_date_count = date_count
        time.sleep(1)

    print("Failed URL:", driver.current_url)
    print("Page title:", driver.title)
    print("Text sample:", clean(page)[:1800])
    raise SystemExit(
        "KKÍ page did not finish rendering. Calendar will NOT be overwritten."
    )


def find_keflavik_team_url(league_page):
    anchors = re.findall(
        r"<a\b([^>]*)>(.*?)</a>", league_page, flags=re.I | re.S
    )

    for attrs, body in anchors:
        href_match = re.search(
            r"href\s*=\s*[\"']([^\"']+)", attrs, flags=re.I
        )
        if not href_match:
            continue

        href = html.unescape(href_match.group(1))
        name = clean(body).strip()

        if "eitt-lid" in href.lower() and "Keflavík" in name:
            return urljoin(LEAGUE_URL, href)

    raise SystemExit(
        "Could not find the current Keflavík men's team link on KKÍ. "
        "Calendar will NOT be overwritten."
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


driver = make_driver()
try:
    league_page = load_and_wait(
        driver,
        LEAGUE_URL,
        ["Bónus deild karla", TARGET_SEASON, "Keflavík"],
    )
    team_url = find_keflavik_team_url(league_page)
    print("Current Keflavík team page:", team_url)

    team_page = load_and_wait(
        driver,
        team_url,
        ["Bónus deild karla", TARGET_SEASON, "Keflavík", "Leikjaplan og úrslit"],
    )
finally:
    driver.quit()

team_text = clean(team_page)
if (
    "Bónus deild karla" not in team_text
    or TARGET_SEASON not in team_text
    or "Keflavík" not in team_text
):
    raise SystemExit(
        "Wrong KKÍ team/competition/season. Calendar will NOT be overwritten."
    )

rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", team_page, flags=re.I | re.S)
events = []
parsed_rows = []

for row in rows:
    row_text = clean(row)
    date_match = re.search(
        r"(\d{2})[-.](\d{2})[-.](20\d{2})\s+(\d{1,2}):(\d{2})",
        row_text,
    )
    if not date_match:
        continue

    cells = [
        clean(cell)
        for cell in re.findall(
            r"<t[dh]\b[^>]*>(.*?)</t[dh]>",
            row,
            flags=re.I | re.S,
        )
    ]
    parsed_rows.append(cells)

    # On a KKÍ team page, the opponent column is displayed as either
    # "gegn Opponent" (home) or "@ Opponent" (away).
    matchup = None
    for cell in cells:
        stripped = cell.strip()
        if stripped.startswith("@") or stripped.lower().startswith("gegn "):
            matchup = stripped
            break

    if not matchup:
        continue

    if matchup.startswith("@"):
        opponent = matchup[1:].strip()
        home = opponent
        away = "Keflavík"
    else:
        opponent = re.sub(r"^gegn\s+", "", matchup, flags=re.I).strip()
        home = "Keflavík"
        away = opponent

    if not opponent:
        continue

    # Venue is normally the last useful cell. Ignore score/preview cells.
    venue = ""
    for cell in reversed(cells):
        candidate = cell.strip()
        if not candidate or candidate == matchup:
            continue
        if re.fullmatch(r"-", candidate):
            continue
        if re.fullmatch(r"\d+\s*[:\-]\s*\d+", candidate):
            continue
        if re.search(r"\d{2}[-.]\d{2}[-.]20\d{2}", candidate):
            continue
        if candidate.lower() in {"sýnishorn", "úrslit"}:
            continue
        venue = candidate
        break

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
    print("Dated team rows found:", len(parsed_rows))
    for cells in parsed_rows[:10]:
        print("TEAM ROW:", repr(cells))
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
    "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
    "X-PUBLISHED-TTL:PT1H",
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
        f"URL:{team_url}",
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
