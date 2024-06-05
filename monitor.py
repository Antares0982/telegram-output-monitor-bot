#!/usr/bin/env -S python3 -O
import asyncio
import os
import sys
import time
from typing import TYPE_CHECKING

from telegram import Bot

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
    prefix = f"\[{markdown_escape(nodename)}]\[{markdown_escape(cur_time)}]\[{markdown_escape(key)}]"
    return prefix, message


async def bot_send_message(text):
    for i in range(5):
        try:
            await Bot(token=TOKEN).send_message(MYID, text, parse_mode="Markdown")
            break
        except Exception as e:
            if i == 4:
                raise type(e) from e
            print(e)
            await asyncio.sleep(2)
        except BaseException as e:
            print(e)


async def send_log(key: str, message: bytes):
    # log_text = f"[{key}]: {message.decode()}"
    prefix, log_text = format_message(key, message.decode())
    texts = longtext_split(log_text)
    loop = asyncio.get_event_loop()

    for i, text in enumerate(texts):
        send_text = f"```\n{text}\n```"
        if i == 0:
            send_text = prefix + send_text
        co = bot_send_message(send_text)
        loop.create_task(co)


async def on_message(message: "AbstractIncomingMessage"):
    key = message.routing_key.partition(".")[2] if message.routing_key is not None else "default"
    await send_log(key, message.body)


import signal


def _exit_func(*args):
    print("exiting...")
    sys.exit(0)


async def scheduled_heartbeat():
    loop = asyncio.get_event_loop()
    while True:
        await asyncio.sleep(3600)
        loop.create_task(bot_send_message(f"\[{nodename}] monitor is alive"))


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


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _exit_func)
    wait_until_network_ready()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    canceller = listen_to(loop, "logging", on_message)
    loop.create_task(bot_send_message(f"\[{nodename}] monitor started"))
    loop.run_until_complete(scheduled_heartbeat())
