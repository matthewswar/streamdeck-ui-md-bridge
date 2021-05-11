"""
Listens to MaterialDeck for FoundryVTT.
"""
import asyncio
import json
import logging
import threading
from typing import Optional
import websockets
from websockets.exceptions import ConnectionClosed

import bridge

log = logging.getLogger(__name__)
_stop_event = threading.Event()
_disconnect_timer: Optional[threading.Timer] = None
_server: websockets.WebSocketServer


async def start(port: int) -> None:
    """
    Starts listening to the websocket
    """
    global _server  # pylint: disable=global-statement,invalid-name
    log.info(f'Starting websocket on 127.0.0.1:{port}')
    _server = await websockets.serve(_listener, '127.0.0.1', port)
    log.info('Websocket listener started')
    await _server.wait_closed()
    log.info('Listeners closed')


def stop() -> None:
    """
    Stops listening to MaterialDeck.
    """
    global _server, _disconnect_timer  # pylint: disable=global-statement,invalid-name
    if _server:
        _server.close()

    if _disconnect_timer and _disconnect_timer.is_alive():
        _disconnect_timer.cancel()
        _disconnect_timer = None

    bridge.disconnect()
    _stop_event.set()


async def _listener(socket: websockets.WebSocketServerProtocol, _path: str) -> None:
    """
    Listens for commands coming from MaterialDeck.
    """
    global _disconnect_timer  # pylint: disable=global-statement,invalid-name
    if _disconnect_timer and _disconnect_timer.is_alive():
        _disconnect_timer.cancel()
        _disconnect_timer = None
    log.info(f'Connection received: {socket.remote_address}')
    bridge.load_md_buttons()
    try:
        await asyncio.gather(
            _listen_to_socket(socket),
            _send_messages(socket),
        )
    except ConnectionClosed:
        log.info(f'Shutting down websocket with {socket.remote_address}')
        if _disconnect_timer and _disconnect_timer.is_alive():
            _disconnect_timer.cancel()
            _disconnect_timer = None
        _disconnect_timer = threading.Timer(60.0, bridge.disconnect)
        _disconnect_timer.start()


async def _listen_to_socket(socket: websockets.WebSocketServerProtocol) -> None:
    while not _stop_event.is_set():
        try:
            message = await asyncio.wait_for(socket.recv(), timeout=2.0)
        except asyncio.TimeoutError:
            await socket.send(json.dumps({'T': 'P'}))
            continue

        response = bridge.analyze_md_message(message)
        if response:
            log.info(response)
            await socket.send(response)


async def _send_messages(socket: websockets.WebSocketServerProtocol) -> None:
    while not _stop_event.is_set():
        next_message = await bridge.next_message()
        if next_message:
            log.info(next_message)
            await socket.send(next_message)
        else:
            await asyncio.sleep(0.5)
