# -*- coding: utf-8 -*-
import urllib.request as u, re, sys
url=sys.argv[1]
req=u.Request(url, headers={'User-Agent':'Mozilla/5.0'})
html=u.urlopen(req,timeout=30).read().decode('utf-8','ignore')
print('HTML_LEN', len(html))
for kw in ['js_content','rich_media_content','data-src','msg_title']:
    print(kw, '->', html.find(kw))
# print around js_content occurrences
idx=html.find('js_content')
print('--- around js_content ---')
print(html[idx-200:idx+300])
