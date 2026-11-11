"""Verify entry-time push delivery gates, retries, and deduplication without sending."""
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
import json
import opportunity_push as push

folder=Path(__file__).resolve().parents[1]/'qa'/'push-tests'/uuid4().hex
folder.mkdir(parents=True)
row=dict(event_id='TEST_2026-11-11',ticker='TEST',company='Example',rules=['TECH3_SMA5'],
         status='Next opening',attribution='Downgrade attribution supported',entry='2026-11-12',
         reaction='2026-11-10',decline=.04,confirmation='2026-11-11',
         entry_berlin='2026-11-12 15:30 CET',exit='2026-12-10',firms=['Example Research'],
         selected_leverage=5,evidence_url='https://example.com/report')
with patch.object(push,'CACHE',folder),patch.object(push,'LEDGER',folder/'ledger.json'),patch.object(push,'config',return_value={'enabled':True}):
    with patch.object(push,'publish',return_value={'message_id':'test-only','accepted_utc':'2026-11-11T22:00:00Z'}) as sender:
        assert push.deliver([row],offline=True)['sent']==0
        assert push.deliver([dict(row,attribution='Unreviewed')])['sent']==0
        assert push.deliver([dict(row,status='Opening passed')])['sent']==0
        assert push.deliver([dict(row,rules=['TECH1_SMA5'])])['sent']==0
        assert sender.call_count==0
        assert push.deliver([row])['sent']==1
        assert sender.call_count==1
        # Exit lies in the future: no realized return or profitability is required.
        assert '2026-12-10' in sender.call_args.args[2]
        assert push.deliver([row])['sent']==0 and sender.call_count==1
    another=dict(row,event_id='SECOND_2026-11-11',ticker='SECOND')
    with patch.object(push,'publish',side_effect=ValueError('simulated outage')):
        assert push.deliver([another])['status']=='error'
    assert another['event_id']+'_'+another['entry'] not in json.loads((folder/'ledger.json').read_bytes())
    with patch.object(push,'publish',return_value={'message_id':'retry-only','accepted_utc':'2026-11-11T22:00:00Z'}):
        assert push.deliver([another])['sent']==1
    candidate=dict(row,event_id='CANDIDATE_2026-11-11',attribution='Unreviewed')
    with patch.object(push,'publish',return_value={'message_id':'candidate-only','accepted_utc':'2026-11-11T22:00:00Z'}) as sender:
        assert push.deliver([candidate])['sent']==0
        assert push.deliver([candidate],allow_unreviewed=True)['sent']==1
        assert 'UNGEPRUEFT' in sender.call_args.args[1]
        assert 'NACHRICHTENPRUEFUNG AUSSTEHEND' in sender.call_args.args[2]
        assert push.deliver([candidate],allow_unreviewed=True)['sent']==0
        excluded=dict(candidate,event_id='EXCLUDED',attribution='Competing news excluded')
        shock=dict(candidate,event_id='SHOCK',attribution='Market or sector shock excluded')
        assert push.deliver([excluded,shock],allow_unreviewed=True)['sent']==0
print('Entry-time alerts, no profit dependency, strict gates, offline safety, deduplication and failed-delivery retry verified.')
