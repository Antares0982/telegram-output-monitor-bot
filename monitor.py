from telegram.ext import Updater
from configparser import ConfigParser

cfgparser = ConfigParser()
cfgparser.read("cfg.ini")

use_proxy = cfgparser.getboolean("PROXY", "USE_PROXY")

filename = cfgparser.get("PATH", "FILEPATH")

token = cfgparser.get("BOT", "TOKEN")

myid = cfgparser.getint("BOT", "MYID")

if use_proxy:
    proxy_url = cfgparser.get("PROXY", "PROXY_URL")
    updater = Updater(token=token, request_kwargs={'proxy_url': proxy_url}, use_context=True)
else:
    updater = Updater(token=token, use_context=True)

with open(filename, 'r', encoding="utf-8") as f:
    txt = f.read()
    
if txt!="":
    updater.bot.send_message(chat_id=myid, text=txt)
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("")
