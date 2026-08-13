"""The WebSocket protocol library must actually be installed.

This is the one test in the real-time suite that does not exercise app
code, and it is the most important one. Starlette's TestClient implements
`websocket_connect` against the ASGI app directly -- it never opens a
socket and never imports a protocol library. So every other socket test
here passes whether or not uvicorn can serve a real handshake.

Without `websockets` (or `wsproto`), uvicorn logs "Unsupported upgrade
request" and closes. The suite stays green; production has no real-time
layer at all. This test is what makes that state impossible to ship.
"""


def test_uvicorn_websocket_implementation_is_importable():
    from uvicorn.protocols.websockets.websockets_impl import (
        WebSocketProtocol,
    )

    assert WebSocketProtocol is not None


def test_websockets_is_declared_in_requirements():
    from pathlib import Path

    requirements = (
        Path(__file__).resolve().parent.parent / "requirements.txt"
    ).read_text(encoding="utf-8")

    assert "websockets==" in requirements, (
        "websockets must be pinned in requirements.txt -- uvicorn cannot "
        "serve a WebSocket handshake without a protocol library, and no "
        "other test in this suite can detect its absence."
    )


def test_container_entrypoint_pins_websocket_transport_policy():
    """Production must not inherit Uvicorn's changing WebSocket defaults."""
    from pathlib import Path

    entrypoint = (
        Path(__file__).resolve().parent.parent / "entrypoint.sh"
    ).read_text(encoding="utf-8")

    assert "--ws-max-size 65536" in entrypoint
    assert "--ws-ping-interval 30" in entrypoint
    assert "--ws-ping-timeout 30" in entrypoint
