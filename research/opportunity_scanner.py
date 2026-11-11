"""Find the selected downgrade-reversal setup and maintain a reviewed alert queue."""
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html import escape, unescape
from io import StringIO
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / 'cache' / 'tech-scanner' / 'deps'))
import exchange_calendars as calendars
import numpy as np
import pandas as pd
import requests

from rating_table_parser import article_rows
from opportunity_push import deliver as deliver_phone

CACHE = ROOT / 'cache' / 'opportunity-scanner'
OUT = ROOT / 'outputs' / 'opportunity-scanner'
NY = ZoneInfo('America/New_York')
BERLIN = ZoneInfo('Europe/Berlin')
RULES = {
    'TECH3_SMA5': 'Technology, decline ≥3%, SMA5, next US open, 20 sessions',
    'TECH1_SMA5': 'Technology, decline ≥1%, SMA5, next US open, 20 sessions',
    'ALL4_5_OPEN': 'All sectors, decline 4–<5%, next US open, 20 sessions',
}
CONFIG = json.loads((ROOT / 'research' / 'opportunity_monitor_protocol.json').read_bytes())
ACTIVE_RULES = tuple(CONFIG.get('active_rules', ['TECH3_SMA5']))
SELECTED_LEVERAGE = int(CONFIG.get('selected_leverage', 5))
ALLOW_UNREVIEWED = CONFIG.get('allow_unreviewed_candidate_alerts', False) is True
if not ACTIVE_RULES or not set(ACTIVE_RULES) <= RULES.keys() or SELECTED_LEVERAGE not in range(1, 6):
    raise ValueError('Invalid active rule or selected leverage in opportunity_monitor_protocol.json')


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n', encoding='utf8')
    temp.replace(path)


def get_json(url, params=None):
    headers={'User-Agent': 'DowngradeResearchScanner/1.0','Accept': 'application/json'}
    if url.startswith('https://api.github.com/') and os.environ.get('GITHUB_TOKEN'):
        headers['Authorization']='Bearer '+os.environ['GITHUB_TOKEN']
    response = requests.get(url, params=params, headers=headers, timeout=(8, 55))
    response.raise_for_status()
    return response.json(), response.headers


def fetch_articles(begin, asof, offline):
    path = CACHE / 'articles.json'
    if offline:
        if path.exists():
            data = json.loads(path.read_bytes())
        else:
            data = []
            for file in (ROOT / 'cache' / 'post-crash').glob('fly-valid-*.json'):
                content = json.loads(file.read_bytes())
                if isinstance(content, list):
                    data.extend(content)
            data.extend(json.loads((ROOT / 'cache' / 'post-crash' / 'fly-08.json').read_bytes()))
    else:
        data = []
        for page in range(1, 5):
            records, headers = get_json('https://dailytradealert.com/wp-json/wp/v2/posts', {
                'search': 'Analyst Upgrades and Downgrades', 'after': begin + 'T00:00:00',
                'before': asof.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'),
                'per_page': 50, 'page': page, '_fields': 'date,date_gmt,link,title,content'})
            if not isinstance(records, list):
                raise ValueError('The publisher returned an invalid article list')
            data.extend(records)
            if page >= int(headers.get('X-WP-TotalPages', 1)):
                break
        atomic_json(path, data)
    selected = {}
    for article in data:
        title = unescape(article['title']['rendered']).lower()
        day = article['date'][:10]
        published = pd.Timestamp(article['date_gmt'], tz='UTC')
        if title.startswith('analyst upgrades and downgrades') and begin <= day and published <= asof:
            selected[day] = article
    actions, coverage = [], []
    for day, article in sorted(selected.items()):
        rows, counts = article_rows(day, article)
        actions.extend(rows)
        coverage.append(dict(date=day, source_url=article['link'], **counts))
    cols = 'ticker grade_date firm action from_grade to_grade source source_url'.split()
    return pd.DataFrame(actions, columns=cols).drop_duplicates(), coverage


def dated_universe(days, asof, offline):
    repo = ROOT / 'cache' / 'industry'
    git = ['git', '-c', f'safe.directory={repo.as_posix()}', '-C', str(repo)]
    metadata = CACHE / 'universe_revisions.json'
    if offline and metadata.exists():
        revisions = [(r['date'],r['commit']) for r in json.loads(metadata.read_bytes()) if r['date']<=asof.date().isoformat()]
        read = lambda commit: (CACHE / 'universes' / (commit + '.csv')).read_text(encoding='utf8')
    elif offline:
        log = subprocess.check_output([*git, 'log', '--reverse', f'--until={asof.date()}', '--format=%as %H',
                                       '--', 'data/constituents.csv']).decode()
        revisions = sorted(dict(line.split() for line in log.splitlines()).items())
        read = lambda commit: subprocess.check_output([*git, 'show', f'{commit}:data/constituents.csv']).decode()
    else:
        first = min(days)
        url = 'https://api.github.com/repos/datasets/s-and-p-500-companies/commits'
        prior, _ = get_json(url, {'path': 'data/constituents.csv', 'until': first + 'T00:00:00Z', 'per_page': 1})
        recent, _ = get_json(url, {'path': 'data/constituents.csv', 'since': first + 'T00:00:00Z',
                                  'until': asof.astimezone(timezone.utc).isoformat(), 'per_page': 100})
        if not isinstance(prior, list) or not isinstance(recent, list) or not prior:
            raise ValueError('Dated universe history is unavailable')
        revisions = sorted(dict((r['commit']['committer']['date'][:10], r['sha']) for r in [*prior, *reversed(recent)]).items())
        atomic_json(metadata, [dict(date=d,commit=c) for d,c in revisions])

        def read(commit):
            path = CACHE / 'universes' / (commit + '.csv')
            if path.exists():
                return path.read_text(encoding='utf8')
            response = requests.get(f'https://raw.githubusercontent.com/datasets/s-and-p-500-companies/{commit}/data/constituents.csv', timeout=20)
            response.raise_for_status()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(response.text, encoding='utf8')
            return response.text

    snapshots = {}
    result = {}
    for day in sorted(set(days)):
        available = [(d, c) for d, c in revisions if d <= day]
        if not available:
            raise ValueError(f'No dated industry snapshot for {day}')
        stamp, commit = available[-1]
        if commit not in snapshots:
            frame = pd.read_csv(StringIO(read(commit)))
            required = {'Symbol', 'Security', 'GICS Sector'}
            if not required <= set(frame):
                raise ValueError('The universe CSV changed its columns')
            snapshots[commit] = frame.set_index('Symbol').to_dict(orient='index')
        result[day] = (stamp, snapshots[commit])
    return result


def price_series(ticker, begin, end, offline):
    path = CACHE / 'prices' / (ticker + '.json')
    if offline:
        candidates = [path, ROOT / 'cache' / 'post-crash' / 'nasdaq_current' / path.name,
                      ROOT / 'cache' / 'post-crash' / 'nasdaq' / path.name]
        source = next((p for p in candidates if p.exists()), None)
        if source is None:
            raise ValueError(f'No cached daily prices for {ticker}')
        records = json.loads(source.read_bytes())
    else:
        payload, _ = get_json(f'https://api.nasdaq.com/api/quote/{quote(ticker, safe="")}/historical', {
            'assetclass': 'etf' if ticker in {'SPY', 'XLK', 'RSPT'} else 'stocks',
            'fromdate': begin, 'todate': end, 'limit': 3000})
        if payload.get('status', {}).get('rCode') != 200 or not payload.get('data'):
            raise ValueError(f'Price request failed for {ticker}')
        records = payload['data']['tradesTable']['rows'] or []
        if payload['data']['totalRecords'] != len(records):
            raise ValueError(f'Incomplete price response for {ticker}')
        atomic_json(path, records)
    if not records:
        raise ValueError(f'No daily price history for {ticker}')
    frame = pd.DataFrame(records)
    frame['date'] = pd.to_datetime(frame.date, format='%m/%d/%Y').dt.strftime('%Y-%m-%d')
    for col in ['open', 'close', 'volume']:
        frame[col] = pd.to_numeric(frame[col].str.replace(r'[$,]', '', regex=True), errors='coerce')
    frame = frame.set_index('date').sort_index()
    if not frame.index.is_unique:
        raise ValueError(f'Duplicate daily bars for {ticker}')
    return frame.loc[(frame[['open', 'close', 'volume']] > 0).all(axis=1) & (frame.index <= end), ['open', 'close']]


def evaluate_event(event, bars, dates, schedule, last, asof, enabled_rules=None):
    """Classify a candidate using completed session closes and the first valid confirmation."""
    rx = dates.searchsorted(event['reaction'])
    row = dict(event, decline=None, confirmation='', entry='', exit='', entry_berlin='', detail='', selected_leverage=SELECTED_LEVERAGE)
    if rx > last:
        row.update(status='Awaiting reaction close', detail='The first full reaction session has not completed.')
        return [row]
    aligned = bars.reindex(dates)
    closes = aligned.close.to_numpy()
    if rx == 0 or not np.isfinite(closes[rx - 1:rx + 1]).all():
        row.update(status='Price data delayed', detail='The reaction close or previous close is missing.')
        return [row]
    decline = 1 - closes[rx] / closes[rx - 1]
    row['decline'] = float(decline)
    rules = []
    if event['sector'] == 'Information Technology' and decline >= .01 - 1e-12:
        rules.append('TECH1_SMA5')
        if decline >= .03 - 1e-12:
            rules.append('TECH3_SMA5')
    if .04 - 1e-12 <= decline < .05 - 1e-12:
        rules.append('ALL4_5_OPEN')
    if enabled_rules is not None:
        rules = [r for r in rules if r in enabled_rules]
    if not rules:
        row.update(status='Below threshold', detail='The completed reaction decline did not meet any frozen rule.')
        return [row]
    results = []
    for method, codes in [('SMA5', [r for r in rules if r.startswith('TECH')]),
                           ('Next session', [r for r in rules if r == 'ALL4_5_OPEN'])]:
        if not codes:
            continue
        r = dict(row, rules=codes, method=method)
        en = rx + 1
        if method == 'SMA5':
            trigger = None
            unavailable = False
            for i in range(rx + 1, min(rx + 5, last) + 1):
                window = closes[i - 5:i + 1]
                if len(window) != 6 or not np.isfinite(window).all():
                    unavailable = True
                    break
                if window[-2] <= window[:-1].mean() and window[-1] > window[1:].mean():
                    trigger = i
                    break
            if trigger is None:
                status = 'Price data delayed' if unavailable else 'Expired without confirmation' if last >= rx + 5 else 'Waiting for SMA5'
                r.update(status=status, detail='Needs the first completed close crossing above SMA5 within five sessions.')
                results.append(r)
                continue
            r['confirmation'] = dates[trigger]
            en = trigger + 1
        opening = schedule.iloc[en]['open']
        r.update(entry=dates[en], exit=dates[en + 19], entry_berlin=opening.tz_convert('Europe/Berlin').strftime('%Y-%m-%d %H:%M %Z'))
        r['status'] = 'Next opening' if asof < opening else 'Opening passed'
        r['detail'] = 'Attribution review required before an opportunity alert.'
        results.append(r)
    return results


def apply_reviews(rows, reviews, prices, dates, schedule, asof):
    for row in rows:
        row['rules'] = row.get('rules', [])
        row['attribution'] = 'Unreviewed'
        review = reviews.get(row['event_id'], {})
        verdict = review.get('verdict', 'unreviewed')
        row['evidence_url'] = review.get('evidence_url', '')
        row['review_note'] = review.get('explanation', '')
        if row.get('decline') is None:
            if verdict == 'excluded':
                row['attribution'] = 'Competing news excluded'
            elif verdict == 'unverifiable':
                row['attribution'] = 'Attribution unverifiable'
            continue
        rx = dates.searchsorted(row['reaction'])
        for ticker, cutoff in [('SPY', .02), ('XLK', .03 if row['sector'] == 'Information Technology' else np.inf)]:
            close = prices[ticker].close.reindex(dates)
            move = close.iloc[rx] / close.iloc[rx - 1] - 1
            if not np.isfinite(move):
                row.update(attribution='Market data delayed')
                break
            if abs(move) >= cutoff:
                row.update(attribution='Market or sector shock excluded')
                break
        if row['attribution'] != 'Unreviewed':
            continue
        if verdict == 'downgrade_attributed' and review.get('evidence_url') and review.get('explanation'):
            publication = pd.to_datetime(review.get('publication_utc'), utc=True, errors='coerce')
            if (review.get('competing_news_checked') is True and pd.notna(publication) and publication <= asof
                    and publication <= schedule.iloc[rx]['close']):
                row['attribution'] = 'Downgrade attribution supported'
            else:
                row['attribution'] = 'Attribution timing or news check incomplete'
        elif verdict == 'excluded':
            row['attribution'] = 'Competing news excluded'
        elif verdict == 'unverifiable':
            row['attribution'] = 'Attribution unverifiable'


def write_report(rows, info, new_alerts):
    OUT.mkdir(parents=True, exist_ok=True)
    atomic_json(OUT / 'latest.json', dict(**info, candidates=rows, new_alerts=new_alerts))
    pd.DataFrame(rows).to_csv(OUT / 'candidates.csv', index=False)
    active = [r for r in rows if r['status'] in {'Next opening', 'Waiting for SMA5', 'Awaiting reaction close', 'Price data delayed'}]
    order = {'Next opening': 0, 'Price data delayed': 1, 'Waiting for SMA5': 2, 'Awaiting reaction close': 3}
    active.sort(key=lambda r: (order[r['status']], r['ticker'], r['reaction']))

    def table(records):
        body = []
        for r in records:
            decline = 'Pending' if r['decline'] is None else f'{100*r["decline"]:.2f}%'
            cells=[escape(str(v)) for v in [r['ticker'], r['status'],', '.join(r['rules']) or 'Pending',
                decline,r['reaction'],r['entry_berlin'] or 'Pending',r['attribution']]]
            url=r.get('evidence_url') or next(iter(r.get('source_urls',[])),'')
            if url.startswith(('https://','http://')):
                cells[-1]+='<br><a href="'+escape(url,quote=True)+'" target="_blank" rel="noopener noreferrer">Read evidence</a>'
            body.append('<tr>' + ''.join('<td>'+v+'</td>' for v in cells) + '</tr>')
        if not body:
            body = ['<tr><td colspan="7">No candidates in this section.</td></tr>']
        return '<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{x}</th>' for x in ['Stock','Signal','Rules','Drop','Reaction','Opening in Berlin','News review']) + '</tr></thead><tbody>' + ''.join(body) + '</tbody></table></div>'

    notices = ''.join(f'<p class="notice">{escape(w)}</p>' for w in info['warnings'])
    html = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Downgrade opportunities</title><style>body{{font-family:Inter,Segoe UI,sans-serif;background:#f3f6f5;color:#16343d;margin:0}}main{{max-width:1400px;margin:auto;padding:32px}}h1{{font-size:32px;margin-bottom:8px}}p{{line-height:1.6}}.summary{{background:white;padding:20px 24px;border-radius:10px;margin:24px 0}}.notice{{background:#fff1d5;padding:12px 16px}}table{{border-collapse:collapse;background:white;width:100%;font-size:14px}}th{{background:#195c5a;color:white;text-align:left}}td,th{{padding:13px;border-bottom:1px solid #dde7e5}}.scroll{{overflow-x:auto}}details{{margin-top:30px}}small{{color:#536b72}}a{{color:#116c69}}code{{font-size:12px}}li{{margin:9px 0}}</style>
<main><h1>Downgrade opportunities</h1><small>Checked {escape(info['asof_berlin'])} · Prices through {escape(info['latest_price'])} · Ratings through {escape(info['latest_ratings'])}</small>
{notices}<div class="summary"><b>{len(new_alerts)} new reviewed openings</b><p>Selected setup: technology, decline at least 3%, SMA5 confirmation, next regular US open. Selected paper scenario: {info['selected_leverage']}× leverage with fixed debt, held for 20 trading sessions. Compare with XLK on the same windows; SPY and QQQ are supplementary comparisons. Each trade has equal starting equity.</p></div>
<h2>Upcoming and waiting</h2>{table(active)}<details><summary>All checked events and expired signals</summary>{table(rows)}</details>
<h2>Active alert rule</h2><ul>{''.join('<li><code>'+escape(k)+'</code> — '+escape(v)+'</li>' for k,v in info['rules'].items())}</ul>
<p>A reviewed opening requires contemporaneous reporting linking the decline to a downgrade and a check of competing company news. Market or sector shock days are excluded. The source reports daily analyst tables and daily closes, so a delayed feed can delay discovery.</p>
<p>Refresh by running <code>Run opportunity scanner.cmd</code>. Review details and source links are saved in <code>latest.json</code>.</p></main></html>'''
    temp = OUT / 'index.tmp'
    temp.write_text(html, encoding='utf8')
    temp.replace(OUT / 'index.html')


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--as-of', help='Timezone-aware ISO timestamp for reproducible replay')
    parser.add_argument('--days', type=int, default=35)
    parser.add_argument('--scheduled', action='store_true', help='Skip NYSE non-trading dates in scheduled runs')
    parser.add_argument('--mark-notified', nargs='+', help='Acknowledge alert keys after preparing their notification')
    args = parser.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    if args.mark_notified:
        path = CACHE / 'notified.json'
        previous = json.loads(path.read_bytes()) if path.exists() else []
        atomic_json(path, sorted(set(previous) | set(args.mark_notified)))
        return
    asof = pd.Timestamp(args.as_of) if args.as_of else pd.Timestamp.now(tz='UTC')
    if asof.tzinfo is None:
        parser.error('--as-of requires an explicit UTC offset')
    begin = (asof.tz_convert(NY).date() - timedelta(days=args.days)).isoformat()
    calendar_start = (pd.Timestamp(begin)-pd.Timedelta(days=25)).strftime('%Y-%m-%d')
    calendar = calendars.get_calendar('XNYS', start=calendar_start, end=(asof.date()+timedelta(days=70)).isoformat())
    schedule = calendar.schedule
    if args.scheduled and not calendar.is_session(asof.tz_convert(NY).date().isoformat()):
        with (CACHE / 'check_history.jsonl').open('a',encoding='utf8') as history:
            history.write(json.dumps({'asof_utc':asof.tz_convert('UTC').isoformat(),'status':'NYSE non-trading date; scheduled scan skipped'})+'\n')
        print('NYSE non-trading date: scheduled scan skipped.')
        return
    dates = schedule.index.strftime('%Y-%m-%d').to_numpy()
    complete = np.flatnonzero((schedule['close'] <= asof).to_numpy())
    last = int(complete[-1])
    actions, coverage = fetch_articles(begin, asof, args.offline)
    if actions.empty:
        raise ValueError('No published ratings available in the requested window')
    universe = dated_universe(actions.grade_date, asof, args.offline)
    review_path = CACHE / 'attribution_reviews.json'
    reviews = json.loads(review_path.read_bytes()) if review_path.exists() else {}
    events = []
    actions['reaction'] = [dates[dates.searchsorted(day, side='right')] for day in actions.grade_date]
    for (ticker, reaction), group in actions.groupby(['ticker', 'reaction']):
        down = group[group.action == 'down']
        if down.empty:
            continue
        day = down.grade_date.min()
        snapshot_date, snapshot = universe[day]
        if ticker not in snapshot:
            continue
        record = snapshot[ticker]
        if 'ALL4_5_OPEN' not in ACTIVE_RULES and record['GICS Sector'] != 'Information Technology':
            continue
        event_id = f'{ticker}_{day}'
        reviewed_reaction = reviews.get(event_id, {}).get('reaction_session', reaction)
        if reviewed_reaction not in dates or reviewed_reaction < day:
            raise ValueError(f'Invalid reviewed reaction session for {event_id}')
        events.append(dict(event_id=event_id, ticker=ticker, grade_date=day, reaction=reviewed_reaction,
                           sector=record['GICS Sector'], company=record['Security'], universe_asof=snapshot_date,
                           source_urls=sorted(down.source_url.unique()), firms=sorted(down.firm.unique()),
                           mixed=bool((group.action=='up').any())))
    begin_prices = (pd.Timestamp(begin)-pd.Timedelta(days=25)).strftime('%Y-%m-%d')
    tickers = sorted({'SPY','XLK',*[r['ticker'] for r in events]})
    prices, failures = {}, []

    def fetch(ticker):
        try:
            return ticker, price_series(ticker, begin_prices, dates[last], args.offline), None
        except (ValueError, KeyError, requests.RequestException) as exc:
            return ticker, None, str(exc)

    with ThreadPoolExecutor(max_workers=5) as pool:
        for ticker, frame, error in pool.map(fetch, tickers):
            if error:
                failures.append(error)
            else:
                prices[ticker] = frame
    if not {'SPY','XLK'} <= prices.keys():
        raise ValueError('Broad-market and sector prices are required for the competing-market screen')
    rows = []
    for event in events:
        if event['mixed']:
            rows.append(dict(event, rules=[], status='Conflicting upgrade excluded', decline=None, confirmation='', entry='', exit='', entry_berlin='', detail='Upgrade and downgrade share a reaction session.'))
        elif event['ticker'] not in prices:
            rows.append(dict(event, rules=[], status='Price data delayed', decline=None, confirmation='', entry='', exit='', entry_berlin='', detail='Daily history unavailable.'))
        else:
            rows.extend(evaluate_event(event, prices[event['ticker']], dates, schedule, last, asof, ACTIVE_RULES))
    apply_reviews(rows, reviews, prices, dates, schedule, asof)
    warnings = list(failures)
    missing = sorted(set(dates[(dates >= begin) & (dates <= dates[last])]) - {r['date'] for r in coverage})
    if missing:
        warnings.append('Ratings source missing completed-session dates: '+', '.join(missing))
    if prices['SPY'].index[-1] < dates[last]:
        warnings.append(f'Daily price feed is delayed. Expected {dates[last]}, received {prices["SPY"].index[-1]}.')
    notified_path = CACHE / 'notified.json'
    notified = set(json.loads(notified_path.read_bytes())) if notified_path.exists() else set()
    alerts = {}
    phone_candidates = {}
    for row in rows:
        if row['status'] == 'Next opening' and row['attribution'] == 'Downgrade attribution supported':
            key = row['event_id']+'_'+row['entry']
            row['alert_key'] = key
            phone_candidates[key] = row
            if key not in notified:
                alerts[key] = row
    info = dict(asof_utc=asof.tz_convert('UTC').isoformat(), asof_berlin=asof.tz_convert(BERLIN).strftime('%Y-%m-%d %H:%M %Z'),
                latest_price=prices['SPY'].index[-1], latest_ratings=max(r['date'] for r in coverage),
                expected_completed_session=dates[last], offline=args.offline, warnings=warnings,
                rules={r:RULES[r] for r in ACTIVE_RULES}, selected_leverage=SELECTED_LEVERAGE,
                source_coverage=coverage, candidate_count=len(rows))
    delivery_rows = rows if ALLOW_UNREVIEWED else list(phone_candidates.values())
    push = deliver_phone(delivery_rows, offline=args.offline, allow_unreviewed=ALLOW_UNREVIEWED)
    info['phone_push'] = push
    info['notification_policy'] = 'Technical candidates require user news review' if ALLOW_UNREVIEWED else 'Reviewed openings only'
    warnings.extend(push['errors'])
    evidence_path = CACHE / 'alert_evidence.json'
    evidence = json.loads(evidence_path.read_bytes()) if evidence_path.exists() else {}
    for key, row in alerts.items():
        evidence.setdefault(key, dict(first_detected_utc=info['asof_utc'], signal=row))
    atomic_json(evidence_path, evidence)
    write_report(rows, info, list(alerts.values()))
    with (CACHE / 'check_history.jsonl').open('a', encoding='utf8') as history:
        history.write(json.dumps(dict(asof_utc=info['asof_utc'], offline=args.offline,
                                      candidate_count=len(rows), new_alert_keys=list(alerts),
                                      latest_price=info['latest_price'],latest_ratings=info['latest_ratings'],
                                      warnings=warnings))+'\n')
    (OUT / 'failure.json').unlink(missing_ok=True)
    print(json.dumps(dict(asof=info['asof_berlin'], candidates=len(rows), new_reviewed_openings=len(alerts),
                          statuses=pd.Series([r['status'] for r in rows]).value_counts().to_dict(), warnings=warnings), indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, requests.RequestException, KeyError) as exc:
        OUT.mkdir(parents=True, exist_ok=True)
        atomic_json(OUT / 'failure.json', {'failed_at':datetime.now(timezone.utc).isoformat(), 'error':str(exc)})
        print(f'Scanner failed: {exc}', file=sys.stderr)
        sys.exit(1)
