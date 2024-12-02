#!/usr/bin/env -S python3 -O
import asyncio
import os
import sys
import time
from typing import TYPE_CHECKING
from aio_pika import connect_robust
from telegram import Bot
from telegram import MessageEntity
from cfg import MYID, TOKEN
from pika_interface import listen_to
from text_splitter import longtext_split


if TYPE_CHECKING:
    from aio_pika.message import AbstractIncomingMessage
nodename = os.uname().nodename


def markdown_escape(text: str) -> str:
    return text.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("`", "\\`")


def format_message(key: str, message: str):
    cur_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    message = message.strip()
    prefix = f"[{nodename}][{cur_time}][{key}]"
    first_entities = [
        MessageEntity(MessageEntity.CODE, 1, len(nodename)),
        MessageEntity(MessageEntity.CODE, 3 + len(nodename), len(cur_time)),
        MessageEntity(MessageEntity.CODE, 5 + len(nodename) + len(cur_time), len(key)),
    ]
    return prefix, message, first_entities


async def bot_send_message(*args, **kwargs):
    for i in range(5):
        try:
            await Bot(token=TOKEN).send_message(*args, **kwargs)
            break
        except Exception as e:
            if i == 4:
                raise type(e) from e
            print(e)
            await asyncio.sleep(2)
        except BaseException as e:
            print(e)


async def send_log(key: str, message: bytes):
    prefix, log_text, first_entities = format_message(key, message.decode())
    texts = longtext_split(log_text)

    for i, text in enumerate(texts):
        if i == 0:
            entity_utf8 = first_entities + [MessageEntity(type=MessageEntity.PRE, offset=len(prefix), length=len(text))]
            send_text = prefix + text
        else:
            entity_utf8 = [MessageEntity(type=MessageEntity.PRE, offset=0, length=len(text))]
            send_text = text
        entities = MessageEntity.adjust_message_entities_to_utf_16(send_text, entity_utf8)
        await bot_send_message(MYID, send_text, entities=entities)


async def on_message(message: "AbstractIncomingMessage"):
    key = message.routing_key.partition(".")[2] if message.routing_key is not None else "default"
    loop = asyncio.get_event_loop()
    loop.create_task(send_log(key, message.body))


import signal


def _exit_func(*args):
    print("exiting...")
    sys.exit(0)


async def scheduled_heartbeat():
    loop = asyncio.get_event_loop()
    while True:
        await asyncio.sleep(3600)
        text = f"[{nodename}] monitor is alive"
        entities_utf8 = [MessageEntity(type=MessageEntity.CODE, offset=1, length=len(nodename))]
        entities = MessageEntity.adjust_message_entities_to_utf_16(text, entities_utf8)
        loop.create_task(bot_send_message(MYID, text, entities=entities))


def wait_until_network_ready():
    print("wait until network ready...")
    import urllib.request as rq
    last = time.time()

    while True:
        try:
            r = rq.urlopen('https://www.google.com')
            r.read()
            if 200 <= r.status < 300:
                break
        except Exception as e:
            print(e, file=sys.stderr)

        now = time.time()
        if now - last < 3:
            time.sleep(3)
        last = now

    loop = asyncio.new_event_loop()
    while True:
        try:
            conn = loop.run_until_complete(connect_robust())
        except:
            time.sleep(3)
        else:
            try:
                conn.close()
            except:
                pass
            break
    try:
        loop.close()
    except:
        pass


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _exit_func)
    wait_until_network_ready()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    canceller = listen_to(loop, "logging", on_message)
    text = f"[{nodename}] monitor started"
    entities_utf8 = [MessageEntity(type=MessageEntity.CODE, offset=1, length=len(nodename))]
    entities = MessageEntity.adjust_message_entities_to_utf_16(text, entities_utf8)
    loop.create_task(bot_send_message(MYID, text, entities=entities))
    loop.run_until_complete(scheduled_heartbeat())
