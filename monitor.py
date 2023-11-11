import os
import subprocess
import sys

from telegram import Bot


def setup():
    _cwd = os.path.dirname(os.path.realpath(__file__))
    _PIP = "pip3" if sys.platform != "win32" else "pip"
    subprocess.run([_PIP, "install", "-r", "requirements.txt"])
    subprocess.run(["./setup.sh"], shell=True, cwd=_cwd)
    sys.path.append(_cwd)


setup()

import asyncio
import time

from cfg import MYID, TOKEN
from rabbitmq_interface import NoLogInterface, listen_to, send_message
from text_splitter import longtext_split

bot = Bot(token=TOKEN)


def format_message(key: str, message: str):
    cur_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    message = message.strip()
    if '\n' in message:
        return f"[{cur_time}][{key}]\n{message}"
    return f"[{cur_time}][{key}]: {message}"


def send_log(key: str, message: bytes):
    # log_text = f"[{key}]: {message.decode()}"
    log_text = format_message(key, message.decode())
    texts = longtext_split(log_text)
    for text in texts:
        asyncio.create_task(bot.send_message(MYID, text))


def cb(routing_key: str, message: bytes, deliver, properties):
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
    print("exiting...")
    sys.exit(0)


signal.signal(signal.SIGINT, _exit_func)

loop = asyncio.new_event_loop()
loop.run_until_complete(bot.send_message(MYID, "[monitor] started"))

while True:
    # suspend the main thread
    time.sleep(3600)
    send_message("logging.monitor", "monitor is alive")
