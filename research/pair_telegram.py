"""One-time private Telegram pairing; never print or publicly store recipient details."""
import os
import re
import time
import requests


def api(token,method,payload):
    try:
        response=requests.post('https://api.telegram.org/bot'+token+'/'+method,
                               json=payload,timeout=(8,20))
        if not response.ok:raise ValueError(f'Telegram {method} failed (HTTP {response.status_code})')
        value=response.json()
        if not value.get('ok'):raise ValueError('Telegram rejected '+method)
        return value.get('result')
    except requests.RequestException as exc:
        raise ValueError('Telegram connection failed: '+type(exc).__name__) from None


def recipient(updates,code,now):
    matches=set()
    for update in updates:
        message=update.get('message',{})
        chat=message.get('chat',{})
        if (chat.get('type')=='private' and message.get('text') in {code,'/start '+code}
                and 0<=now-message.get('date',0)<=1800 and isinstance(chat.get('id'),int)
                and chat['id']>0):
            matches.add(str(chat['id']))
    if len(matches)!=1:
        raise ValueError('No unique recent pairing message found. Send the exact pairing code to your bot and retry.')
    return matches.pop()


def main():
    token=os.environ.get('TELEGRAM_BOT_TOKEN','').strip()
    code=os.environ.get('TELEGRAM_PAIR_CODE','').strip()
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{20,}',token):raise ValueError('TELEGRAM_BOT_TOKEN secret is missing or invalid')
    if not re.fullmatch(r'verbinden-[0-9a-f]{24}',code):raise ValueError('Invalid one-time pairing code')
    updates=api(token,'getUpdates',{'timeout':0,'limit':100,'allowed_updates':['message']})
    chat=recipient(updates,code,time.time())
    print('::add-mask::'+chat,flush=True)
    result=api(token,'sendMessage',{
        'chat_id':chat,'disable_notification':False,
        'text':'TEST - Telegram-Cloud-Verbindung\n\n'
               'Diese Nachricht kommt von deinem GitHub-Scanner. Kein Handelssignal.\n\n'
               'Deine private Chat-ID: '+chat+'\n\n'
               'Speichere nur diese Zahl als GitHub-Actions-Secret TELEGRAM_CHAT_ID in '
               'RedPanda123xd/tech3-downgrade-monitor. Danach kann der Scanner Telegram verwenden. '
               'Token und Chat-ID werden nicht in den oeffentlichen Logs gespeichert.'})
    if not isinstance(result,dict) or not result.get('message_id'):raise ValueError('Telegram returned no pairing message receipt')
    print('Private pairing instructions sent through Telegram; recipient details omitted from logs.')


if __name__=='__main__':
    try:main()
    except ValueError as exc:raise SystemExit(str(exc)) from None
