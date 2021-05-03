"""
Listens to events coming from the El Gato Streamdeck.
"""

import errno
import logging
import os
from queue import Queue
import threading

BUFFER_SIZE = 1024

log = logging.getLogger(__name__)

_stop_event = threading.Event()


def start(output_queue: Queue, pipe_path: str) -> None:
    """
    Starts listening to the Streamdeck.
    """
    log.info(f'Listening on pipe {pipe_path}')

    _make_named_pipe(pipe_path)

    fifo = os.open(pipe_path, os.O_RDONLY | os.O_NONBLOCK)
    while not _stop_event.is_set():
        try:
            buf = os.read(fifo, BUFFER_SIZE)
            if not buf:
                continue
            line = buf.decode('utf-8').strip()
            parsed_line = _parse_piped_line(line)
            if parsed_line:
                log.info(parsed_line)
                output_queue.put(parsed_line)
        except OSError as err:
            if err.errno != errno.EWOULDBLOCK:
                raise

    os.close(fifo)
    os.remove(pipe_path)
    log.info('Pipe done')


def stop() -> None:
    """
    Stops listening to the Streamdeck and allows cleanup.
    """
    _stop_event.set()


def _parse_piped_line(line: str) -> str:
    return line


def _make_named_pipe(named_pipe_path: str) -> None:
    try:
        os.mkfifo(named_pipe_path)
    except OSError as err:
        if err.errno != errno.EEXIST:
            log.exception(f'Making pipe failed: {err}')
            raise
