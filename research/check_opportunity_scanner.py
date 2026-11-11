"""Regression checks for completed-bar timing, overlapping rules and alert review gates."""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]/'cache'/'tech-scanner'/'deps'))
import exchange_calendars as xc
import numpy as np
import pandas as pd
from opportunity_scanner import evaluate_event, apply_reviews, ACTIVE_RULES, SELECTED_LEVERAGE

calendar=xc.get_calendar('XNYS',start='2026-10-01',end='2027-01-31')
schedule=calendar.schedule
days=schedule.index.strftime('%Y-%m-%d').to_numpy()
rx=12
close=np.full(len(days),100.)
close[rx:rx+3]=[95.5,96.,100.]
bars=pd.DataFrame({'open':close,'close':close},index=days)
event=dict(event_id='TEST_'+days[rx-1],ticker='TEST',sector='Information Technology',reaction=days[rx],grade_date=days[rx-1])
asof=schedule.iloc[rx+2]['close']+pd.Timedelta(minutes=5)
rows=evaluate_event(event,bars,days,schedule,rx+2,asof)
tech=next(r for r in rows if r.get('method')=='SMA5')
assert set(tech['rules'])=={'TECH1_SMA5','TECH3_SMA5'}
assert tech['entry']==days[rx+3] and tech['exit']==days[rx+22] and tech['status']=='Next opening'
assert next(r for r in rows if r.get('method')=='Next session')['status']=='Opening passed'
selected=evaluate_event(event,bars,days,schedule,rx+2,asof,ACTIVE_RULES)
assert len(selected)==1 and selected[0]['rules']==['TECH3_SMA5'] and selected[0]['selected_leverage']==5
small=bars.copy();small.loc[days[rx],'close']=98.
assert evaluate_event(event,small,days,schedule,rx+2,asof,ACTIVE_RULES)[0]['status']=='Below threshold'
assert ACTIVE_RULES==('TECH3_SMA5',) and SELECTED_LEVERAGE==5
# A currently unfinished bar cannot generate a confirmation even if the provider supplied it.
unfinished=evaluate_event(event,bars,days,schedule,rx+1,schedule.iloc[rx+2]['open'])
assert next(r for r in unfinished if r.get('method')=='SMA5')['status']=='Waiting for SMA5'
gap=bars.copy();gap.loc[days[rx+1],'close']=np.nan
assert next(r for r in evaluate_event(event,gap,days,schedule,rx+2,asof) if r.get('method')=='SMA5')['status']=='Price data delayed'
prices={'SPY':pd.DataFrame({'close':np.full(len(days),100.)},index=days),'XLK':pd.DataFrame({'close':np.full(len(days),100.)},index=days)}
incomplete={event['event_id']:dict(verdict='downgrade_attributed',evidence_url='https://example.com/story',explanation='Analyst story')}
apply_reviews(rows,incomplete,prices,days,schedule,asof)
assert all(r['attribution']!='Downgrade attribution supported' for r in rows)
review={event['event_id']:dict(**incomplete[event['event_id']],publication_utc=schedule.iloc[rx]['open'].isoformat(),competing_news_checked=True)}
apply_reviews(rows,review,prices,days,schedule,asof)
assert all(r['attribution']=='Downgrade attribution supported' for r in rows)
future={event['event_id']:dict(**incomplete[event['event_id']],publication_utc=(asof+pd.Timedelta(days=1)).isoformat(),competing_news_checked=True)}
apply_reviews(rows,future,prices,days,schedule,asof)
assert all(r['attribution']!='Downgrade attribution supported' for r in rows)
pending=[dict(event,decline=None)]
apply_reviews(pending,{event['event_id']:dict(verdict='excluded',evidence_url='https://example.com/earnings',explanation='Competing earnings')},prices,days,schedule,asof)
assert pending[0]['attribution']=='Competing news excluded'
prices['SPY'].loc[days[rx],'close']=97.
apply_reviews(rows,review,prices,days,schedule,asof)
assert all(r['attribution']=='Market or sector shock excluded' for r in rows)
assert not calendar.is_session('2026-11-26')
assert calendar.session_close('2026-11-27').tz_convert('America/New_York').hour==13
print('Completed bars, confirmation delay, missing prices, overlapping rules, attribution gates and holiday schedule verified.')
