"""Tests for the pure text-handling helpers in monitor.py.

Run with pytest, or directly: ``python3 test_monitor.py``.
"""

import os

# monitor.py reads these at import time and exits if they're missing.
os.environ.setdefault("ANTARES_MONITOR_MYID", "1")
os.environ.setdefault("ANTARES_MONITOR_TOKEN", "123456789:TEST-test_token")

from monitor import (  # noqa: E402
    TEXT_LENGTH_LIMIT,
    format_message,
    longtext_split,
)


def test_short_text_unchanged():
    assert longtext_split("hello") == ["hello"]


def test_just_under_limit_is_single_chunk():
    txt = "a" * (TEXT_LENGTH_LIMIT - 1)
    assert longtext_split(txt) == [txt]


def test_all_chunks_within_limit():
    txt = "\n".join(f"line {i} " + "x" * 50 for i in range(500))
    chunks = longtext_split(txt)
    assert len(chunks) > 1
    assert all(len(c) <= TEXT_LENGTH_LIMIT for c in chunks)


def test_lines_reconstruct_when_no_hard_split():
    # Every line fits under the limit, so packing only drops the separators it
    # reinserts on rejoin -> the content round-trips exactly.
    txt = "\n".join("x" * 100 for _ in range(200))
    chunks = longtext_split(txt)
    assert len(chunks) > 1
    assert "\n".join(chunks) == txt


def test_super_long_single_line_is_hard_split():
    txt = "y" * (TEXT_LENGTH_LIMIT * 3)
    chunks = longtext_split(txt)
    assert all(len(c) <= TEXT_LENGTH_LIMIT for c in chunks)
    assert "".join(chunks) == txt


def test_code_block_kept_intact_when_not_spanning_whole():
    head = "\n".join("h" * 100 for _ in range(50))  # forces an overall split
    block = (
        "```\n" + "\n".join("c" * 100 for _ in range(30)) + "\n```"
    )  # fits one chunk
    txt = head + "\n" + block
    chunks = longtext_split(txt)
    assert len(chunks) > 1
    assert all(len(c) <= TEXT_LENGTH_LIMIT for c in chunks)
    # exactly one chunk holds the whole fenced block (both ``` fences together)
    assert sum(c.count("```") == 2 for c in chunks) == 1


def test_code_block_spanning_whole_is_force_split():
    body = "\n".join("z" * 100 for _ in range(60))
    txt = "```\n" + body + "\n```"
    chunks = longtext_split(txt)
    assert len(chunks) > 1
    assert all(len(c) <= TEXT_LENGTH_LIMIT for c in chunks)


def test_format_message_entity_offsets():
    prefix, msg, entities = format_message("mykey", "  hello  ")
    assert msg == "hello"
    assert len(entities) == 3
    # Each entity must slice out exactly its bracketed field from the prefix.
    fields = [prefix[e.offset : e.offset + e.length] for e in entities]
    assert fields[2] == "mykey"
    assert prefix == f"[{fields[0]}][{fields[1]}][mykey]"


if __name__ == "__main__":
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for fn in funcs:
        try:
            fn()
        except AssertionError as e:
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
        else:
            print(f"ok   {fn.__name__}")
    print(f"\n{len(funcs) - failures}/{len(funcs)} passed")
    raise SystemExit(1 if failures else 0)
