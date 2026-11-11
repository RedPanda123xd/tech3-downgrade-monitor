"""Phone delivery through Telegram or ntfy with retry and deduplication state."""
from argparse import ArgumentParser
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import urlencode
import json
import os
import re
import secrets
import time

ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'cache'/'opportunity-scanner'
CONFIG=CACHE/'notification_config.json'
LEDGER=CACHE/'push_delivery.json'
SETUP=ROOT/'outputs'/'phone-setup'

def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,indent=2)+'\n',encoding='utf8')
    temp.replace(path)

def config():
    token=os.environ.get('TELEGRAM_BOT_TOKEN','').strip()
    chat=os.environ.get('TELEGRAM_CHAT_ID','').strip()
    if token or chat:
        if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{20,}',token) or not re.fullmatch(r'[1-9][0-9]*',chat):
            raise ValueError('Complete Telegram bot token and private chat ID are required')
        return {'enabled':True,'provider':'telegram','token':token,'chat_id':chat}
    topic=os.environ.get('NTFY_TOPIC')
    if topic:
        value={'enabled':True,'server':'https://ntfy.sh','topic':topic}
    elif CONFIG.exists():
        value=json.loads(CONFIG.read_bytes())
    else:return None
    if value.get('server')!='https://ntfy.sh' or not re.fullmatch(r'[A-Za-z0-9_-]{20,120}',value.get('topic','')):
        raise ValueError('Invalid ntfy notification configuration')
    return value if value.get('enabled') else None

def publish(settings,title,message,click=None):
    import requests
    if settings.get('provider')=='telegram':
        body=title+'\n\n'+message
        if click and click.startswith('https://') and click not in body:body+='\n'+click
        if len(body)>4096:raise ValueError('Telegram message exceeds the delivery limit')
        try:
            response=requests.post('https://api.telegram.org/bot'+settings['token']+'/sendMessage',
                json={'chat_id':settings['chat_id'],'text':body,'disable_notification':False,
                      'link_preview_options':{'is_disabled':True}},timeout=(8,20))
            if not response.ok:raise ValueError(f'Telegram rejected the notification (HTTP {response.status_code})')
            receipt=response.json()
            result=receipt.get('result',{})
            if not receipt.get('ok') or not result.get('message_id'):
                raise ValueError('Telegram returned no message receipt')
            # The public cloud state must never contain the token or private chat ID.
            return {'message_id':str(result['message_id']),'provider':'telegram',
                    'accepted_utc':datetime.now(timezone.utc).isoformat()}
        except requests.RequestException as exc:
            raise ValueError('Telegram request failed: '+type(exc).__name__) from None
    headers={'Title':title,'Priority':'4','Tags':'chart_with_upwards_trend',
             'Content-Type':'text/plain; charset=utf-8'}
    if click and click.startswith('https://'):headers['Click']=click
    try:
        response=requests.post(settings['server']+'/'+settings['topic'],data=message.encode('utf8'),
                               headers=headers,timeout=(8,20))
        if not response.ok:raise ValueError(f'ntfy rejected the notification (HTTP {response.status_code})')
        receipt=response.json()
        if not receipt.get('id'):raise ValueError('ntfy returned no message receipt')
        return {'message_id':receipt['id'],'accepted_utc':datetime.now(timezone.utc).isoformat()}
    except requests.RequestException as exc:
        # Connection exceptions can contain the secret subscription URL.
        raise ValueError('ntfy request failed: '+type(exc).__name__) from None

def message_for(row,reviewed=True):
    if not reviewed:
        source=row.get('evidence_url') or next(iter(row.get('source_urls',[])),'')
        return '\n'.join([
            'TECHNISCHER TREFFER - NACHRICHTENPRUEFUNG AUSSTEHEND',
            f"{row['ticker']} - {row.get('company','')} | TECH3_SMA5",
            f"Downgrade-Tabelle: {row.get('grade_date',row['reaction'])}; Reaktion {row['reaction']}: -{100*row['decline']:.2f}%.",
            'Analystenhaus: '+', '.join(row.get('firms',[])),
            f"Taeglicher SMA5-Cross bestaetigt: {row['confirmation']}.",
            'Naechster US-Open: '+row['entry_berlin']+' (09:30 New York).',
            f"Geplanter Ausstieg: {row['exit']} zum Schlusskurs; 20 Sitzungen inklusive Einstieg.",
            f"Ausgewaehltes Papierszenario: {row.get('selected_leverage',5)}x; Sektorvergleich XLK.",
            'Nicht bestaetigt, dass allein die Analystenmeinung den Rueckgang verursacht hat. Nachrichten vor einer Entscheidung selbst pruefen.',
            'Quelle: '+source])
    return '\n'.join([
        f"{row['ticker']} - {row.get('company','')} | TECH3_SMA5",
        f"Downgrade-linked reaction: {row['reaction']}; decline {100*row['decline']:.2f}%.",
        'Firm: '+', '.join(row.get('firms',[])),
        f"SMA5 confirmed: {row['confirmation']}.",
        'Next US opening: '+row['entry_berlin']+' (09:30 New York).',
        f"Planned exit: {row['exit']} regular close (20 sessions including entry).",
        f"Selected paper scenario: {row.get('selected_leverage',5)}x leverage with fixed debt; XLK benchmark.",
        'News attribution reviewed; market/sector shock screens passed.',
        'Research signal. '+row.get('evidence_url','')])

def deliver(rows,offline=False,allow_unreviewed=False):
    if offline:return {'status':'offline','sent':0,'errors':[]}
    settings=config()
    if not settings:return {'status':'not_configured','sent':0,'errors':[]}
    CACHE.mkdir(parents=True,exist_ok=True)
    lock=CACHE/'push_delivery.lock'
    if lock.exists() and time.time()-lock.stat().st_mtime>900:lock.unlink(missing_ok=True)
    try:
        fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:
        return {'status':'busy','sent':0,'errors':['Push delivery is already running; retry on the next check.']}
    os.close(fd)
    sent=0;errors=[]
    try:
        ledger=json.loads(LEDGER.read_bytes()) if LEDGER.exists() else {}
        for row in rows:
            reviewed=row.get('attribution')=='Downgrade attribution supported'
            pending=row.get('attribution') in {'Unreviewed','Attribution unverifiable','Attribution timing or news check incomplete'}
            if (row.get('status')!='Next opening' or row.get('rules')!=['TECH3_SMA5']
                    or not (reviewed or (allow_unreviewed and pending))):continue
            channel='telegram:' if settings.get('provider')=='telegram' else ''
            key=channel+('' if reviewed else 'candidate:')+row['event_id']+'_'+row['entry']
            if key in ledger:continue
            try:
                title=row['ticker']+' downgrade-reversal setup' if reviewed else 'UNGEPRUEFT: '+row['ticker']+' SMA5-Setup'
                source=row.get('evidence_url') or next(iter(row.get('source_urls',[])),'')
                receipt=publish(settings,title,message_for(row,reviewed),source)
                ledger[key]=dict(**receipt,ticker=row['ticker'],entry=row['entry'],kind='reviewed' if reviewed else 'candidate')
                save(LEDGER,ledger)
                sent+=1
            except ValueError as exc:
                errors.append(row['ticker']+': '+str(exc))
    finally:
        lock.unlink(missing_ok=True)
    return {'status':'error' if errors else 'enabled','sent':sent,'errors':errors}

def setup():
    if CONFIG.exists():settings=json.loads(CONFIG.read_bytes())
    else:
        settings={'enabled':True,'server':'https://ntfy.sh','topic':'codex-tech3-'+secrets.token_hex(20),
                  'phone_receipt_verified':False,'created_utc':datetime.now(timezone.utc).isoformat()}
        save(CONFIG,settings)
    SETUP.mkdir(parents=True,exist_ok=True)
    link='ntfy://ntfy.sh/'+settings['topic']+'?'+urlencode({'display':'Technology downgrade alerts'})
    # Generate a QR locally; the subscription is never sent to a QR service.
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from PIL import Image,ImageDraw
    qr=QrCodeWidget(link);qr.qr.make();n=qr.qr.getModuleCount();scale=9;border=4
    im=Image.new('RGB',((n+2*border)*scale,)*2,'white');draw=ImageDraw.Draw(im)
    for y in range(n):
        for x in range(n):
            if qr.qr.isDark(y,x):
                draw.rectangle(((x+border)*scale,(y+border)*scale,(x+border+1)*scale-1,(y+border+1)*scale-1),fill='black')
    im.save(SETUP/'subscribe.png')
    html=f'''<!doctype html><html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Connect Android alerts</title>
<style>body{{font:18px/1.6 Segoe UI,sans-serif;max-width:780px;margin:40px auto;padding:20px;color:#17343f}}img{{width:330px;max-width:90%}}code{{overflow-wrap:anywhere}}a{{color:#136f69}}</style>
<h1>Connect Android alerts</h1><ol><li>Install <a href="https://play.google.com/store/apps/details?id=io.heckel.ntfy">ntfy for Android</a> and allow notifications.</li>
<li>Scan this QR with your phone, or <a href="{escape(link,quote=True)}">open the subscription in ntfy</a>.</li>
<li>Enable Instant delivery in ntfy. Allow background operation if Android asks.</li><li>Run <b>Send phone test.cmd</b> on your PC to check delivery.</li></ol>
<img src="subscribe.png" alt="Private ntfy subscription QR"><p>Manual server: <code>https://ntfy.sh</code><br>Topic: <code>{escape(settings['topic'])}</code></p>
<p>The topic is an unguessable subscription address, not an authenticated private account. Keep this page and QR to yourself; anyone with the address can read or post messages. Alerts contain public ticker/news details, not account balances or positions.</p>
<p>The scanner runs on your PC. Keep it awake, online and Codex running. Delivery also depends on market-data availability, news review, ntfy and your phone's connection.</p></html>'''
    (SETUP/'index.html').write_text(html,encoding='utf8')
    print('Android ntfy configuration saved. Open outputs/phone-setup/index.html to subscribe.')

def main():
    parser=ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--setup',action='store_true')
    group.add_argument('--test',action='store_true')
    args=parser.parse_args()
    if args.setup:setup();return
    settings=config()
    if not settings:raise ValueError('Android push is not configured')
    receipt=publish(settings,'TEST - technology opportunity alerts',
                    'Test notification only: no trading opportunity has been identified. Your selected monitor is technology >=3% decline, SMA5 confirmation, next US open, 20 sessions, 5x paper leverage. Reply in Codex when you receive this on your phone.')
    save(CACHE/'last_push_test.json',receipt)
    print('Test accepted by ntfy; phone receipt still needs your confirmation. Message ID: '+receipt['message_id'])

if __name__=='__main__':main()
