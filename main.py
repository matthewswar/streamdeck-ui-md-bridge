"""
This module wraps the streamdeck-ui library to provide rudimentary functionality with MaterialDeck for FoundryVTT.
"""
import asyncio
from concurrent.futures.thread import ThreadPoolExecutor
import logging
from queue import Queue
import signal
import sys
from types import FrameType

import click
from qasync import QEventLoop
from streamdeck_ui.ui_main import Ui_MainWindow

import bridge
import deck_listener
import md_listener
import ui_proxy

NAMED_PIPE_PATH = '/tmp/md_bridge_pipe'

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
log = logging.getLogger(__name__)


def signal_handler(sig_num: int, _frame: FrameType) -> None:
    """
    Handles incoming signals
    """
    md_listener.stop()
    deck_listener.stop()
    log.info(f'Handled signal {signal.strsignal(sig_num)}')


async def _setup_listeners(port: int, ui: Ui_MainWindow) -> None:
    output_queue: Queue = Queue(1024)
    with ThreadPoolExecutor(3) as executor:
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        await asyncio.wait([
            loop.run_in_executor(executor, deck_listener.start, output_queue, NAMED_PIPE_PATH),
            loop.run_in_executor(executor, bridge.init, NAMED_PIPE_PATH, output_queue, ui),
            md_listener.start(port),
        ])


@click.command()
@click.option('-p', '--port', type=int, default=3001)
def _main(port: int) -> None:
    for sig in [signal.SIGINT]:
        signal.signal(sig, signal_handler)

    app, main_window = ui_proxy.create_app(bridge.key_up_callback)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    with loop:
        main_window.show()
        loop.run_until_complete(_setup_listeners(port, main_window.ui))
    sys.exit(0)


if __name__ == '__main__':
    _main()  # pylint: disable=no-value-for-parameter
