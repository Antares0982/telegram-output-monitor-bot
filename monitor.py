#!/usr/bin/env -S python3 -O
import asyncio
import os
import signal
import sys
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from aio_pika import ExchangeType, connect_robust
from telegram import Bot, MessageEntity

if TYPE_CHECKING:
    from aio_pika.abc import AbstractIncomingMessage

try:
    MYID = int(os.environ["ANTARES_MONITOR_MYID"])
    TOKEN = os.environ["ANTARES_MONITOR_TOKEN"]
except (KeyError, ValueError):
    print(
        "ANTARES_MONITOR_MYID or ANTARES_MONITOR_TOKEN not set or invalid.",
        file=sys.stderr,
    )
    sys.exit(1)


NODENAME = os.uname().nodename
TEXT_LENGTH_LIMIT = 4000


def force_longtext_split(txt: list[str]) -> list[str]:
    counting = 0
    i = 0
    ans: list[str] = []
    sep_len = 0
    while i < len(txt):
        if counting + len(txt[i]) < TEXT_LENGTH_LIMIT - sep_len:
            counting += len(txt[i])
            sep_len = 1
            i += 1
        else:
            if i == 0:
                # too long, must split
                super_long_line = txt[0]
                _end = min(1000, len(super_long_line))
                part = super_long_line[:_end]
                txt[0] = super_long_line[_end:]
                ans.append(part)
                continue
            else:
                ans.append("\n".join(txt[:i]))
                txt = txt[i:]
                i = 0
                sep_len = 0
                counting = 0
    if len(txt) > 0:
        ans.append("\n".join(txt))
    return ans


def longtext_split(txt: str) -> list[str]:
    if len(txt) < TEXT_LENGTH_LIMIT:
        return [txt]
    txts = txt.split("\n")
    ans: list[str] = []
    # search for ``` of markdown block
    dotsss_start = -1
    dotsss_end = -1
    for i in range(len(txts)):
        if txts[i].startswith("```"):
            if dotsss_start == -1:
                dotsss_start = i
            else:
                dotsss_end = i
                break
    if dotsss_start != -1 and dotsss_end != -1:
        if dotsss_start == 0 and dotsss_end == len(txts) - 1:
            # cannot keep markdown block!!!
            return force_longtext_split(txts)
        parts = (
            txts[:dotsss_start],
            txts[dotsss_start : dotsss_end + 1],
            txts[dotsss_end + 1 :],
        )
        for i, part in enumerate(parts):
            if len(part) > 0:
                if i == 0:
                    ans.extend(force_longtext_split(part))
                else:
                    this_text = "\n".join(part)
                    ans.extend(longtext_split(this_text))
        return ans
    #
    return force_longtext_split(txts)


def listen_to(
    loop: asyncio.AbstractEventLoop,
    exchange_name: str,
    handler: Callable[["AbstractIncomingMessage"], Awaitable[Any]],
    **connection_kwargs,
):
    """
    Returns: a stop handle to stop listening.
    """
    condition = asyncio.Condition()
    loop.run_until_complete(condition.acquire())

    async def listen_task():
        connection = await connect_robust(**connection_kwargs)
        async with connection:
            channel = await connection.channel()

            exchange = await channel.declare_exchange(exchange_name, ExchangeType.TOPIC)
            queue = await channel.declare_queue(exchange_name, exclusive=True)
            await queue.bind(exchange, routing_key=f"{exchange_name}.#")

            async def consume(msg: "AbstractIncomingMessage"):
                async with msg.process():
                    await handler(msg)

            await queue.consume(consume)
            print(f"Start listening: {exchange_name}.#")
            await condition.wait()
            print(f"Stopped listening: {exchange_name}.#")
            await connection.close()

    async def stop_handle():
        async with condition:
            condition.notify()

    loop.create_task(listen_task())
    return stop_handle


def markdown_escape(text: str) -> str:
    return (
        text.replace("_", "\\_")
        .replace("*", "\\*")
        .replace("[", "\\[")
        .replace("`", "\\`")
    )


def format_message(key: str, message: str):
    cur_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    message = message.strip()
    prefix = f"[{NODENAME}][{cur_time}][{key}]"
    first_entities = [
        MessageEntity(MessageEntity.CODE, 1, len(NODENAME)),
        MessageEntity(MessageEntity.CODE, 3 + len(NODENAME), len(cur_time)),
        MessageEntity(MessageEntity.CODE, 5 + len(NODENAME) + len(cur_time), len(key)),
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
            entity_utf8 = first_entities + [
                MessageEntity(
                    type=MessageEntity.PRE, offset=len(prefix), length=len(text)
                )
            ]
            send_text = prefix + text
        else:
            entity_utf8 = [
                MessageEntity(type=MessageEntity.PRE, offset=0, length=len(text))
            ]
            send_text = text
        entities = MessageEntity.adjust_message_entities_to_utf_16(
            send_text, entity_utf8
        )
        await bot_send_message(MYID, send_text, entities=entities)


async def on_message(message: "AbstractIncomingMessage"):
    key = (
        message.routing_key.partition(".")[2]
        if message.routing_key is not None
        else "default"
    )
    loop = asyncio.get_event_loop()
    loop.create_task(send_log(key, message.body))


def _exit_func(*args):
    print("exiting...")
    sys.exit(0)


async def scheduled_heartbeat():
    loop = asyncio.get_event_loop()
    while True:
        await asyncio.sleep(3600)
        text = f"[{NODENAME}] monitor is alive"
        entities_utf8 = [
            MessageEntity(type=MessageEntity.CODE, offset=1, length=len(NODENAME))
        ]
        entities = MessageEntity.adjust_message_entities_to_utf_16(text, entities_utf8)
        loop.create_task(bot_send_message(MYID, text, entities=entities))


def wait_until_network_ready():
    print("wait until network ready...")
    import urllib.request as rq

    last = time.time()

    while True:
        try:
            r = rq.urlopen("https://www.google.com")
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
                loop.run_until_complete(conn.close())
            except:
                pass
            break
    try:
        loop.close()
    except:
        pass


def main():
    signal.signal(signal.SIGINT, _exit_func)
    wait_until_network_ready()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    canceller = listen_to(loop, "logging", on_message)
    text = f"[{NODENAME}] monitor started"
    entities_utf8 = [
        MessageEntity(type=MessageEntity.CODE, offset=1, length=len(NODENAME))
    ]
    entities = MessageEntity.adjust_message_entities_to_utf_16(text, entities_utf8)
    loop.create_task(bot_send_message(MYID, text, entities=entities))
    loop.run_until_complete(scheduled_heartbeat())


if __name__ == "__main__":
    main()
