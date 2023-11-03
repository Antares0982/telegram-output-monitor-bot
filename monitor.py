import os
import subprocess
import sys

from telegram import Bot


def setup():
    _cwd = os.path.dirname(os.path.realpath(__file__))
    _PIP = "pip3" if sys.platform != "win32" else "pip"
    subprocess.run([_PIP, "install", "-r", "requirements.txt"])
    subprocess.run(["./setup.sh"], shell=True, cwd=_cwd)


setup()

import asyncio
import time

from cfg import MYID, TOKEN
from rabbitmq_interface import NoLogInterface, listen_to

bot = Bot(token=TOKEN)


def send_log(key: str, message: bytes):
    log_text = f"[{key}]: {message.decode()}"
    asyncio.create_task(bot.send_message(chat_id=MYID, text=log_text))


def cb(routing_key: str, message, deliver, properties):
    try:
        key = routing_key.partition(".")[2]
        send_log(key, message)
    except Exception as e:
        print(e)


consumer = listen_to(
    "logging",
    {"monitor": "logging.#"},
    cb,
    NoLogInterface()
)

import signal


def _exit_func(*args):
    consumer.stop()
    sys.exit(0)


signal.signal(signal.SIGINT, _exit_func)

while True:
    # suspend the main thread
    time.sleep(10000)
