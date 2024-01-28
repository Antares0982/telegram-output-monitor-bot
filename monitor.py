#!/usr/bin/env -S python3 -O
import os
import subprocess
import sys
from typing import TYPE_CHECKING

from cfg import MYID, TOKEN


try:
    from cfg import SKIP_SETUP  # type: ignore
except ImportError:
    SKIP_SETUP = False

nodename = os.uname().nodename


def setup():
    if SKIP_SETUP:
        return
    _cwd = os.path.dirname(os.path.realpath(__file__))
    _PIP = "pip3" if sys.platform != "win32" else "pip"
    subprocess.run([_PIP, "install", "-r", "requirements.txt"])
    subprocess.run(["./setup.sh"], shell=True, cwd=_cwd)
    sys.path.append(_cwd)


setup()

import asyncio
import time

from telegram import Bot

from rabbitmq_interface import listen_to
from text_splitter import longtext_split


if TYPE_CHECKING:
    from aio_pika.message import AbstractIncomingMessage


bot = Bot(token=TOKEN)


def format_message(key: str, message: str):
    cur_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    message = message.strip()
    return f"[{nodename}][{cur_time}][{key}]\n{message}"


async def bot_send_message(text):
    for i in range(5):
        try:
            await bot.send_message(MYID, text)
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
    log_text = format_message(key, message.decode())
    texts = longtext_split(log_text)
    loop = asyncio.get_event_loop()
    for text in texts:
        co = bot_send_message(text)
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
        loop.create_task(bot_send_message(f"[{nodename}] monitor is alive"))


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _exit_func)
    loop = asyncio.get_event_loop()
    canceller = listen_to(loop, "logging", on_message)
    loop.create_task(bot_send_message(f"[{nodename}] monitor started"))
    loop.run_until_complete(scheduled_heartbeat())
