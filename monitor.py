import json
import sys
from configparser import ConfigParser
from typing import List

from telegram.ext import Updater

cfgparser = ConfigParser()

thispath = sys.path[0]
if thispath.find("/") != -1:
    cfgparser.read(thispath+"/cfg.ini")
else:
    cfgparser.read(thispath+"\\cfg.ini")

filename = cfgparser.get("PATH", "FILEPATH")
keywordfile = cfgparser.get("PATH", "KEYWORDPATH")

token = cfgparser.get("BOT", "TOKEN")
myid = cfgparser.getint("BOT", "MYID")

use_proxy = cfgparser.getboolean("PROXY", "USE_PROXY")
if use_proxy:
    proxy_url = cfgparser.get("PROXY", "PROXY_URL")
    updater = Updater(token=token, request_kwargs={
                      'proxy_url': proxy_url}, use_context=True)
else:
    updater = Updater(token=token, use_context=True)

with open(filename, 'r', encoding="utf-8") as f:
    txt: str = f.read()
with open(keywordfile, 'r', encoding="utf-8") as f:
    KEYWORDS: List[str] = json.load(f)


def haskeyword(s: str, keywords: List[str]) -> bool:
    for keyword in keywords:
        if s.find(keyword) != -1:
            return True
    return False


if txt != "":
    ind = txt.find("\n")
    while ind != -1:
        if not haskeyword(txt[:ind], KEYWORDS):
            try:
                updater.bot.send_message(chat_id=myid, text=txt[:ind])
            except:
                pass
        txt = txt[ind+1:]
        ind = txt.find("\n")
    if txt != "":
        updater.bot.send_message(chat_id=myid, text=txt)
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("")
