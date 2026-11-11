"""Verify entry-time push delivery gates, retries, and deduplication without sending."""
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
import json
import os
import requests
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

telegram={'enabled':True,'provider':'telegram','token':'123456789:TEST_ONLY_TOKEN_NOT_A_REAL_CREDENTIAL',
          'chat_id':'123456789'}
with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':telegram['token'],'TELEGRAM_CHAT_ID':telegram['chat_id']}):
    assert push.config()==telegram
with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':telegram['token'],'TELEGRAM_CHAT_ID':''}):
    try:push.config();raise AssertionError('Incomplete Telegram config must not fall back to ntfy')
    except ValueError:pass
with patch('requests.post') as post:
    post.return_value.ok=True
    post.return_value.json.return_value={'ok':True,'result':{'message_id':17,'chat':{'id':123456789}}}
    receipt=push.publish(telegram,'TEST','Test body','https://example.com/report')
    payload=post.call_args.kwargs['json']
    assert payload['disable_notification'] is False and 'parse_mode' not in payload
    assert payload['chat_id']==telegram['chat_id'] and 'https://example.com/report' in payload['text']
    assert receipt['provider']=='telegram' and receipt['message_id']=='17'
    assert telegram['token'] not in json.dumps(receipt) and telegram['chat_id'] not in json.dumps(receipt)
    post.side_effect=requests.ConnectionError('URL containing '+telegram['token'])
    try:push.publish(telegram,'TEST','body');raise AssertionError('Expected failure')
    except ValueError as exc:assert telegram['token'] not in str(exc)
with patch.object(push,'CACHE',folder),patch.object(push,'LEDGER',folder/'ledger.json'),patch.object(push,'config',return_value=telegram):
    with patch.object(push,'publish',side_effect=ValueError('simulated Telegram outage')):
        assert push.deliver([row])['status']=='error'
    with patch.object(push,'publish',return_value={'message_id':'telegram-retry','provider':'telegram'}) as sender:
        assert push.deliver([row])['sent']==1
        assert push.deliver([row])['sent']==0 and sender.call_count==1
print('Telegram notifications, secret redaction, incomplete configuration, independent channel deduplication and retry verified.')
