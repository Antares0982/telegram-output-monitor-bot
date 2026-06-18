#!/usr/bin/env -S python3 -O
import asyncio
import logging
import os
import signal
import sys
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Coroutine

from aio_pika import ExchangeType, connect_robust
from telegram import Bot, MessageEntity
from telegram.error import RetryAfter, TelegramError

if TYPE_CHECKING:
    from aio_pika.abc import AbstractIncomingMessage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("monitor")

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
SEND_MAX_RETRIES = 5
SEND_BACKOFF_CAP = 30

# A single, reused Bot instance. Initialized in main() once the event loop is
# running and the network is ready; reused for every send so the underlying
# HTTP connection pool is shared instead of rebuilt per message.
bot = Bot(token=TOKEN)


def _log_task_exception(task: "asyncio.Task[Any]") -> None:
    """Done-callback so fire-and-forget tasks don't swallow their exceptions."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("background task failed", exc_info=exc)


def spawn(coro: Coroutine[Any, Any, Any]) -> "asyncio.Task[Any]":
    """Schedule a background task and make sure its failures get logged."""
    task = asyncio.create_task(coro)
    task.add_done_callback(_log_task_exception)
    return task


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
    exchange_name: str,
    handler: Callable[["AbstractIncomingMessage"], Awaitable[Any]],
    **connection_kwargs,
) -> Callable[[], Awaitable[None]]:
    """Start consuming in the background.

    Must be called from within a running event loop. Returns an async stop
    handle; awaiting it tells the consumer to stop, waits for it to drain, and
    closes the connection.
    """
    stop_event = asyncio.Event()

    async def listen_task():
        connection = await connect_robust(**connection_kwargs)
        async with connection:
            channel = await connection.channel()
            # Process one message at a time: gives chronological delivery order
            # and natural backpressure so a burst of logs can't pile up faster
            # than Telegram accepts them.
            await channel.set_qos(prefetch_count=1)

            exchange = await channel.declare_exchange(exchange_name, ExchangeType.TOPIC)
            queue = await channel.declare_queue(exchange_name, exclusive=True)
            await queue.bind(exchange, routing_key=f"{exchange_name}.#")

            async def consume(msg: "AbstractIncomingMessage"):
                async with msg.process():
                    await handler(msg)

            await queue.consume(consume)
            logger.info("Start listening: %s.#", exchange_name)
            await stop_event.wait()
            logger.info("Stopped listening: %s.#", exchange_name)

    task = spawn(listen_task())

    async def stop_handle() -> None:
        stop_event.set()
        await task

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
    delay = 1
    last_exc: Exception | None = None
    for attempt in range(1, SEND_MAX_RETRIES + 1):
        try:
            await bot.send_message(*args, **kwargs)
            return
        except RetryAfter as e:
            # Telegram flood control: honor the server-specified wait.
            last_exc = e
            retry_after = e.retry_after
            if isinstance(retry_after, timedelta):
                retry_after = retry_after.total_seconds()
            wait = retry_after + 1
            logger.warning(
                "flood control on attempt %d/%d, waiting %ss",
                attempt,
                SEND_MAX_RETRIES,
                wait,
            )
            await asyncio.sleep(wait)
        except TelegramError as e:
            last_exc = e
            logger.warning(
                "send_message failed on attempt %d/%d: %s",
                attempt,
                SEND_MAX_RETRIES,
                e,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, SEND_BACKOFF_CAP)
    assert last_exc is not None
    raise last_exc


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
    # Await the send so the surrounding msg.process() only acks once the log
    # has actually been delivered. A failure here re-raises and the message is
    # nacked/redelivered instead of being silently lost.
    await send_log(key, message.body)


async def scheduled_heartbeat():
    while True:
        await asyncio.sleep(3600)
        text = f"[{NODENAME}] monitor is alive"
        entities_utf8 = [
            MessageEntity(type=MessageEntity.CODE, offset=1, length=len(NODENAME))
        ]
        entities = MessageEntity.adjust_message_entities_to_utf_16(text, entities_utf8)
        spawn(bot_send_message(MYID, text, entities=entities))


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


async def async_main():
    # Bring up the shared Bot's HTTP client once before any send.
    await bot.initialize()
    stop_listening = listen_to("logging", on_message)
    heartbeat = spawn(scheduled_heartbeat())

    text = f"[{NODENAME}] monitor started"
    entities_utf8 = [
        MessageEntity(type=MessageEntity.CODE, offset=1, length=len(NODENAME))
    ]
    entities = MessageEntity.adjust_message_entities_to_utf_16(text, entities_utf8)
    spawn(bot_send_message(MYID, text, entities=entities))

    # Block here until a termination signal asks us to stop.
    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown.set)
    await shutdown.wait()

    logger.info("shutting down...")
    heartbeat.cancel()
    try:
        await heartbeat
    except asyncio.CancelledError:
        pass
    await stop_listening()
    await bot.shutdown()


def main():
    wait_until_network_ready()
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
