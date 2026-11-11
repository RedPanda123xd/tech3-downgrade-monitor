"""Check portable cloud state handling without publishing or modifying a repository."""
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from base64 import b64decode
import json
import os
import opportunity_push as push
import cloud_opportunity_runner as cloud

folder=Path(__file__).resolve().parents[1]/'qa'/'cloud-state-tests'/uuid4().hex
folder.mkdir(parents=True)
old={'attribution_reviews':{'TEST':{'verdict':'excluded'}},'push_delivery':{'already_sent':{'message_id':'example'}}}
with patch.object(cloud,'CACHE',folder):
    cloud.restore(old)
    assert cloud.snapshot(old)==old
    with patch.object(cloud,'api') as api:
        cloud.save_remote('example/test',old,old,'sha')
        api.assert_not_called()
        new=dict(old,notified=['new-key'])
        cloud.save_remote('example/test',new,old,'sha')
        assert api.call_args.args==('PUT','example/test')
        payload=api.call_args.kwargs['json']
        assert payload['sha']=='sha' and json.loads(b64decode(payload['content']))==new
with patch.dict(os.environ,{'NTFY_TOPIC':'example-private-topic-for-test-only'}):
    assert push.config()['topic']=='example-private-topic-for-test-only'
print('Cloud state restoration, no-op suppression, optimistic concurrency and environment-only push configuration verified.')
