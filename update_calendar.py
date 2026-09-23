import urllib.request
import datetime
import pathlib
import re
import html
import hashlib

OUT = pathlib.Path("keflavik-basket.ics")

# KKÍ: Bónus deild karla
SOURCE = (
    "https://www.kki.is/motamal/leikir-og-urslit/"
    "motayfirlit/Leikir?league_id=190&season_id=undefined"
)


def fetch(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/140 Safari/537.36"
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


page = fetch(SOURCE)
page_text = clean(page)

# ÖRYGGI:
# Dagatalið má ALDREI sækja kvennadeild eða aðra keppni.
if "Bónus deild karla" not in page_text:
    raise SystemExit(
        "KKÍ page is not Bónus deild karla. "
        "Calendar will NOT be overwritten."
    )

rows = re.findall(
    r"<tr\b[^>]*>(.*?)</tr>",
    page,
    flags=re.I | re.S,
)

events = []

for row in rows:
    row_text = clean(row)

    # Bara Keflavík
    if "Keflavík" not in row_text:
        continue

    # Ekki Keflavík b, yngri flokkar o.s.frv.
    if re.search(
        r"Keflavík\s+(?:b\b|c\b|\d+\.fl|MB\d|U\d)",
        row_text,
        re.I,
    ):
        continue

    # Finna dagsetningu og tíma
    match = re.search(
        r"(\d{2})[-.](\d{2})[-.](20\d{2})\s+"
        r"(\d{1,2}):(\d{2})",
        row_text,
    )

    if not match:
        continue

    day, month, year, hour, minute = map(
        int, match.groups()
    )

    cells = [
        clean(cell)
        for cell in re.findall(
            r"<t[dh]\b[^>]*>(.*?)</t[dh]>",
            row,
            flags=re.I | re.S,
        )
    ]

    # Leita að Keflavík sem nákvæmu liðsnafni
    keflavik_positions = [
        i for i, cell in enumerate(cells)
        if cell.strip() == "Keflavík"
    ]

    if not keflavik_positions:
        continue

    # Finna líkleg liðsnöfn í röðinni
    team_cells = []

    for cell in cells:
        cell = cell.strip()

        if not cell:
            continue

        # Sleppa dagsetningum
        if re.fullmatch(
            r"\d{2}[-.]\d{2}[-.]20\d{2}\s+\d{1,2}:\d{2}",
            cell,
        ):
            continue

        # Sleppa úrslitatölum
        if re.fullmatch(r"\d+\s*[-:]\s*\d+", cell):
            continue

        if re.search(
            r"[A-Za-zÁÉÍÓÚÝÞÆÖÐáéíóúýþæöð]",
            cell,
        ):
            team_cells.append(cell)

    try:
        k = team_cells.index("Keflavík")
    except ValueError:
        continue

    # KKÍ röðin á að innihalda bæði liðin.
    if k > 0:
        home = team_cells[k - 1]
        away = "Keflavík"
    elif len(team_cells) > 1:
        home = "Keflavík"
        away = team_cells[1]
    else:
        continue

    bad_labels = {
        "Dagskrá",
        "Leikir",
        "Bónus deild karla",
        "Deildarkeppni",
    }

    if home in bad_labels or away in bad_labels:
        continue

    # Ísland er UTC allt árið.
    start = datetime.datetime(
        year,
        month,
        day,
        hour,
        minute,
        tzinfo=datetime.timezone.utc,
    )

    uid_source = (
        f"{year}-{month}-{day}-{home}-{away}"
    )

    uid = hashlib.sha1(
        uid_source.encode("utf-8")
    ).hexdigest()[:16]

    events.append(
        {
            "start": start,
            "home": home,
            "away": away,
            "uid": uid,
        }
    )


# Fjarlægja duplicates
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


# Mjög mikilvægt:
# Ekki skrifa tómt dagatal ef KKÍ breytir vefsíðunni.
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
