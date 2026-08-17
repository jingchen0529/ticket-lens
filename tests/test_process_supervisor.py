from __future__ import annotations

import io

from app.utils.process_supervisor import start_parent_pipe_watchdog


class _Server:
    should_exit = False


def test_parent_pipe_eof_requests_server_shutdown():
    server = _Server()

    thread = start_parent_pipe_watchdog(server, io.BytesIO(b""))
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert server.should_exit is True


def test_parent_pipe_ignores_data_until_eof():
    server = _Server()

    thread = start_parent_pipe_watchdog(server, io.BytesIO(b"keepalive"))
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert server.should_exit is True
