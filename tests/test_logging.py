import logging

from sayitship.__main__ import AccessLogFilter


def record(msg, *args):
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, msg, args, None)


def test_polling_lines_are_dropped():
    f = AccessLogFilter()
    assert not f.filter(record('%s - "%s %s"', "1.2.3.4", "GET", "/internal/approvals/abc"))
    assert f.filter(record('%s - "%s %s"', "1.2.3.4", "POST", "/task"))


def test_one_time_keys_are_redacted():
    r = record('%s - "%s %s"', "1.2.3.4", "POST", "/approvals/abc/allow?key=SECRET123")
    assert AccessLogFilter().filter(r)
    assert "SECRET123" not in r.getMessage() and "key=***" in r.getMessage()
