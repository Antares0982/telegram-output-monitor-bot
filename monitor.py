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
    logger.critical("ANTARES_MONITOR_MYID or ANTARES_MONITOR_TOKEN not set or invalid.")
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


def _hard_split_line(line: str, limit: int) -> list[str]:
    """Break a single over-long line into pieces of at most `limit` chars."""
    return [line[i : i + limit] for i in range(0, len(line), limit)]


def _pack_lines(lines: list[str], limit: int) -> list[str]:
    """Greedily group lines into chunks whose joined length stays below `limit`.

    Lines that are too long to fit on their own are hard-split. Pure function:
    the input list is never mutated.
    """
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0  # length of "\n".join(current)

    def flush() -> None:
        nonlocal current, current_len
        if current:
            chunks.append("\n".join(current))
            current = []
            current_len = 0

    for line in lines:
        if len(line) >= limit:
            # Can't fit even alone: emit what we have, then hard-split it.
            flush()
            chunks.extend(_hard_split_line(line, limit))
            continue
        sep = 1 if current else 0  # the "\n" that would join this line on
        if current_len + sep + len(line) < limit:
            current.append(line)
            current_len += sep + len(line)
        else:
            flush()
            current.append(line)
            current_len = len(line)
    flush()
    return chunks


def _find_code_block(lines: list[str]) -> "tuple[int, int] | None":
    """Return (start, end) indices of the first ```-fenced block, or None."""
    start = -1
    for i, line in enumerate(lines):
        if line.startswith("```"):
            if start == -1:
                start = i
            else:
                return start, i
    return None


def longtext_split(txt: str, limit: int = TEXT_LENGTH_LIMIT) -> list[str]:
    """Split text into Telegram-sized chunks, keeping a fenced code block intact
    when it doesn't span the whole message."""
    if len(txt) < limit:
        return [txt]

    lines = txt.split("\n")
    block = _find_code_block(lines)
    if block is None:
        return _pack_lines(lines, limit)

    start, end = block
    if start == 0 and end == len(lines) - 1:
        # The whole text is one code block; it can't be kept intact.
        return _pack_lines(lines, limit)

    before, fenced, after = lines[:start], lines[start : end + 1], lines[end + 1 :]
    chunks: list[str] = []
    if before:
        chunks.extend(_pack_lines(before, limit))
    if fenced:
        chunks.extend(longtext_split("\n".join(fenced), limit))
    if after:
        chunks.extend(longtext_split("\n".join(after), limit))
    return chunks


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


def format_message(key: str, message: str) -> "tuple[str, str, list[MessageEntity]]":
    cur_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    message = message.strip()

    # Build "[node][time][key]" incrementally, recording a CODE entity for each
    # bracketed field so offsets stay correct regardless of field lengths.
    prefix = ""
    first_entities: list[MessageEntity] = []
    for field in (NODENAME, cur_time, key):
        prefix += "["
        first_entities.append(
            MessageEntity(MessageEntity.CODE, len(prefix), len(field))
        )
        prefix += field + "]"
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


NETWORK_PROBE_INTERVAL = 3.0


async def wait_for(
    name: str,
    probe: Callable[[], Awaitable[Any]],
    interval: float = NETWORK_PROBE_INTERVAL,
) -> None:
    """Retry an async readiness probe until it succeeds.

    Probes the real dependency rather than a generic host, so it works
    regardless of region/proxy setup. Retries indefinitely: at boot the network
    may take a while to come up, and giving up would just hand control to the
    supervisor for a restart loop with no benefit.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            await probe()
        except Exception as e:
            logger.warning("%s not ready (attempt %d): %s", name, attempt, e)
            await asyncio.sleep(interval)
        else:
            logger.info("%s is ready", name)
            return


async def _probe_rabbitmq() -> None:
    conn = await connect_robust()
    await conn.close()


async def async_main():
    # Wait for the real dependencies before doing anything else, reusing this
    # one event loop. Telegram readiness is established by retrying the Bot's
    # own initialize() (which performs a getMe through the configured client).
    await wait_for("RabbitMQ", _probe_rabbitmq)
    await wait_for("Telegram", bot.initialize)
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
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
