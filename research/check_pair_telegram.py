"""Verify pairing selects only a unique, recent private chat matching the code."""
from unittest.mock import patch
import io
import os
from contextlib import redirect_stdout
import pair_telegram as pair

code='verbinden-'+'a'*24
base={'message':{'chat':{'id':123456789,'type':'private'},'text':code,'date':1000}}
assert pair.recipient([base],code,1010)=='123456789'
assert pair.recipient([{'message':dict(base['message'],text=' '+code+'\n')}],code,1010)=='123456789'
for updates in [[],[{'message':dict(base['message'],text='/start')}],
                [{'message':dict(base['message'],date=1)}],
                [{'message':dict(base['message'],chat={'id':123,'type':'group'})}],
                [base,{'message':dict(base['message'],chat={'id':456,'type':'private'})}]]:
    try:pair.recipient(updates,code,2000);raise AssertionError('Expected rejected pairing')
    except ValueError:pass
with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'123456789:TEST_ONLY_TOKEN_NOT_A_REAL_CREDENTIAL','TELEGRAM_PAIR_CODE':code}),\
        patch.object(pair.time,'time',return_value=1010),\
        patch.object(pair,'api',side_effect=[{'username':'ExampleTestBot'},[base],{'message_id':1}]) as api:
    output=io.StringIO()
    with redirect_stdout(output):pair.main()
    assert api.call_args.args[1]=='sendMessage'
    assert api.call_args.args[2]['chat_id']=='123456789'
    assert '123456789' not in output.getvalue().replace('::add-mask::123456789','')
    assert 'TEST_ONLY_TOKEN' not in output.getvalue()
print('Unique private pairing, freshness, exact code and redacted output verified.')
