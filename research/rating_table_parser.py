"""Parse public daily rating-change tables; no historic research inputs required."""
import re
from bs4 import BeautifulSoup

def article_rows(day, article):
    tables=BeautifulSoup(article['content']['rendered'],'lxml').find_all('table')
    if len(tables)!=2:raise ValueError(f'Expected two ratings tables on {day}, found {len(tables)}')
    rows=[];counts={}
    for action,table in zip(['up','down'],tables):
        count=0
        for tr in table.select('tr'):
            cells=[td.get_text(' ',strip=True) for td in tr.find_all('td')]
            if len(cells)!=4:continue
            _,ticker,firm,call=cells
            grade=[x.strip() for x in call.split('→')]
            if not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,9}',ticker) or not firm or len(grade)!=2:continue
            old,new=grade
            if not old or not new or old.lower()==new.lower():continue
            rows.append([ticker.replace('-','.'),day,firm,action,old,new,'The Fly via Daily Trade Alert',article['link']])
            count+=1
        counts[action]=count
    return rows,counts
