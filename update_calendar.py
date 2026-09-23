import json, urllib.request, datetime, pathlib, time
TEAM_ID=233885
OUT=pathlib.Path('keflavik-basket.ics')

def get_json(url):
    req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as r: return json.load(r)

def esc(s): return str(s or '').replace('\\','\\\\').replace(';','\\;').replace(',','\\,').replace('\n','\\n')

def fold(line):
    b=line.encode('utf-8'); out=[]
    while len(b)>73:
        cut=73
        while cut>0:
            try: part=b[:cut].decode('utf-8'); break
            except UnicodeDecodeError: cut-=1
        out.append(part); b=b[cut:]
    out.append(b.decode('utf-8'))
    return '\r\n '.join(out)

events={}
for page in range(0,10):
    try: data=get_json(f'https://www.sofascore.com/api/v1/team/{TEAM_ID}/events/next/{page}')
    except Exception as e:
        print('Fetch failed page',page,e); break
    batch=data.get('events',[])
    if not batch: break
    for e in batch:
        tournament=((e.get('tournament') or {}).get('uniqueTournament') or {}).get('name','')
        if 'Iceland Basketball Premier League' not in tournament: continue
        if TEAM_ID not in [(e.get('homeTeam') or {}).get('id'),(e.get('awayTeam') or {}).get('id')]: continue
        events[e['id']]=e
    if not data.get('hasNextPage',False): break

if not events:
    raise SystemExit('No Bónus deild events found; refusing to overwrite calendar.')
now=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Keflavik Basket Calendar//IS','CALSCALE:GREGORIAN','METHOD:PUBLISH','X-WR-CALNAME:Keflavík – Bónus deild karla','X-WR-TIMEZONE:Atlantic/Reykjavik','REFRESH-INTERVAL;VALUE=DURATION:PT6H','X-PUBLISHED-TTL:PT6H']
for e in sorted(events.values(), key=lambda x:x.get('startTimestamp',0)):
    home=(e.get('homeTeam') or {}).get('name',''); away=(e.get('awayTeam') or {}).get('name','')
    dt=datetime.datetime.fromtimestamp(e['startTimestamp'], datetime.timezone.utc)
    end=dt+datetime.timedelta(hours=2)
    venue=((e.get('venue') or {}).get('name') or '')
    rnd=(e.get('roundInfo') or {}).get('round')
    desc='Bónus deild karla' + (f' – umferð {rnd}' if rnd else '')
    url=f'https://www.sofascore.com/event/{e["id"]}'
    lines += ['BEGIN:VEVENT',f'UID:sofascore-{e["id"]}@keflavik-basket-calendar',f'DTSTAMP:{now}',f'DTSTART:{dt.strftime("%Y%m%dT%H%M%SZ")}',f'DTEND:{end.strftime("%Y%m%dT%H%M%SZ")}',f'SUMMARY:🏀 {esc(home)} – {esc(away)}',f'DESCRIPTION:{esc(desc)}',f'URL:{url}']
    if venue: lines.append(f'LOCATION:{esc(venue)}')
    lines += ['STATUS:CONFIRMED','END:VEVENT']
lines.append('END:VCALENDAR')
OUT.write_text('\r\n'.join(fold(x) for x in lines)+'\r\n',encoding='utf-8')
print(f'Wrote {len(events)} events to {OUT}')
