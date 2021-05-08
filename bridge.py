"""
Provides direct communication between the El Gato Streamdeck and the Material Deck module.
"""

import copy
import json
import logging
from pathlib import Path
import math
from queue import Queue
from typing import Callable, Optional, Union
from urllib import request

from streamdeck_ui import api as deck_api, gui as deck_gui
from streamdeck_ui.ui_main import Ui_MainWindow

CONNECTED_PAYLOAD = json.dumps({'target': 'MD', 'type': 'connected', 'data': 'SD'})
INITIALIZE_PAYLOAD = json.dumps({'source': 'SD', 'type': 'version', 'version': '1.4.2'})
CONFIG_PATH = f'{Path.home()}/.stream-deck-ui-md-bridge'
IMAGE_CACHE_PATH = f'{CONFIG_PATH}/image_cache'
DECK_CONFIG_FILE = f'{Path.home()}/.streamdeck_ui.json'
MATERIAL_FOUNDRY_IMAGE = f'{CONFIG_PATH}/MaterialFoundry512x512.png'
DECK_COLUMNS = 8
DECK_ROWS = 4

log = logging.getLogger(__name__)
_deck_id: str = ''
_bridge_file: str = ''
_output_queue: Queue
_ui: Ui_MainWindow
_initialized: bool = False


def _init_required(default_value: Optional[Union[str, int]] = None) -> Callable:
    global _initialized  # pylint: disable=global-statement,invalid-name

    def decorator(func: Callable) -> Callable:

        def wrapper(*args, **kwargs):
            if _initialized:
                return func(*args, **kwargs)

            return default_value

        return wrapper

    return decorator


def init(bridge_file: str, output_queue: Queue, ui: Ui_MainWindow) -> None:
    """
    Initializes and chooses the Stream Deck to use
    """
    global _deck_id, _bridge_file, _output_queue, _ui, _initialized  # pylint: disable=global-statement,invalid-name
    _bridge_file = bridge_file
    _output_queue = output_queue
    _ui = ui

    Path(IMAGE_CACHE_PATH).mkdir(parents=True, exist_ok=True)
    while not _deck_id:
        deck_ids = list(deck_api.decks.keys())
        if deck_ids:
            _deck_id = deck_ids[0]

    log.info(f'Loaded with deck ID: {_deck_id}')
    _initialized = True


def disconnect() -> None:
    """
    Replaces all buttons configured with Material Foundry with placeholders.
    """
    button_states = deck_api.state[_deck_id]['buttons']
    for page, buttons in button_states.items():
        for button_index, button_info in buttons.items():
            if 'material_deck' in button_info:
                _reset_button(button_index, MATERIAL_FOUNDRY_IMAGE, page)


def analyze_md_message(message: Union[str, bytes]) -> str:
    """
    Handles the message coming from Material Deck.
    """
    global _ui  # pylint: disable=global-statement,invalid-name
    log.info(message)
    data = json.loads(message)
    if data.get('target') == 'server':
        return CONNECTED_PAYLOAD

    if data.get('target') == 'SD':
        if data.get('type') == 'init':
            return INITIALIZE_PAYLOAD

        if data.get('event') == 'setTitle':
            _handle_set_tile(data)
        elif data.get('event') == 'setImage':
            _handle_set_image(data)
        elif data.get('event') == 'setBufferImage':
            _handle_set_buffer_image(data)

        deck_gui.redraw_buttons(_ui)

    return ''


def next_message() -> Optional[str]:
    """
    Gets the next message that should be sent to FoundryVTT. None is returned if it's empty.
    """
    global _output_queue  # pylint: disable=global-statement,invalid-name
    if _output_queue.empty():
        return None
    return _output_queue.get(block=False)  # type: ignore


@_init_required()
def key_up_callback(deck_id: str, key: int, state: bool) -> None:
    """
    Handles key up events by sending the necessary information to the output queue.
    """
    if state:
        log.warning('Released callback called while the state boolean is true')
    button_state = deck_api._button_state(deck_id, deck_api.get_page(_deck_id), key)  # pylint: disable=protected-access
    md_info = button_state.get('material_deck')
    if md_info:
        _write_message(json.dumps(_create_command_payload(
                    md_info['init_data']['action'],
                    'keyUp',
                    key,
                    deck_api.get_page(_deck_id)
                )
            )
        )


@_init_required()
def md_data_changed(button_index: int, text: str) -> None:
    """
    Handles when data is changed within the md data box.
    """
    try:
        json.loads(text)
    except Exception:  # pylint: disable=broad-except
        return

    page = deck_api.get_page(_deck_id)
    button_state = deck_api._button_state(_deck_id, page, button_index)  # pylint: disable=protected-access

    deck_info = button_state.setdefault('material_deck', {})
    deck_info['action_settings'] = json.loads(text)

    _write_message(json.dumps(_create_will_display_payload(deck_info, button_index, page)))


@_init_required()
def md_action_changed(button_index: int, action: str) -> None:
    """
    Handles changing the type of action Material Deck listens for.
    """
    global _ui  # pylint: disable=global-statement,invalid-name
    button_state = deck_api._button_state(  # pylint: disable=protected-access
        _deck_id,
        deck_api.get_page(_deck_id),
        button_index
    )
    page = deck_api.get_page(_deck_id)
    if action:
        deck_info: dict = button_state.setdefault('material_deck', {})
        init_data = deck_info.setdefault('init_data', {
            'event': 'willAppear',
            'payload': {
                'settings': {
                    'displayName': True,
                    'displayIcon': True,
                },
            },
        })
        init_data['action'] = action
        command = _create_command_payload(action, 'keyDown', button_index, page)
        deck_api.set_button_command(
            _deck_id,
            page,
            button_index,
            f"{CONFIG_PATH}/pipe_writer.sh '{_bridge_file}' '{json.dumps(command)}'"
        )

        _write_message(json.dumps(_create_will_display_payload(deck_info, button_index, page)))
    elif 'material_deck' in button_state:
        previous_action = button_state['material_deck'].get('init_data', {}).get('action', '')
        del button_state['material_deck']
        _reset_button(button_index, '', page)
        _write_message(json.dumps({
            'event': 'willDisappear',
            'action': previous_action,
            'payload': {
                'coordinates': {
                    'column': button_index % DECK_COLUMNS,
                    'row': math.floor(button_index / DECK_COLUMNS),
                },
            },
            'context': _to_context(button_index, page),
            'device': _deck_id,
        }))
    deck_api.export_config(DECK_CONFIG_FILE)
    deck_gui.redraw_buttons(_ui)


@_init_required(default_value='')
def get_md_action(button_index: int) -> str:
    """
    Returns the md_action for the specified button.
    """
    button_state = deck_api._button_state(  # pylint: disable=protected-access
        _deck_id,
        deck_api.get_page(_deck_id),
        button_index
    )
    return button_state.get('material_deck', {}).get('init_data', {}).get('action', '')  # type: ignore


@_init_required(default_value='')
def get_md_data(button_index: int) -> str:
    """
    Returns the md_data for the specified button
    """
    button_state = deck_api._button_state(  # pylint: disable=protected-access
        _deck_id,
        deck_api.get_page(_deck_id),
        button_index
    )
    return json.dumps(button_state.setdefault('material_deck', {}).setdefault('action_settings', {}))


def load_md_buttons(page: Optional[int] = None) -> None:
    """
    Reads the buttons configured for use with MaterialDeck and sends willAppear events.
    """
    if _deck_id not in deck_api.state:
        return

    if page is None:
        page = deck_api.get_page(_deck_id)

    button_states = deck_api.state[_deck_id]['buttons']
    for button_index, button_info in button_states[page].items():
        if 'material_deck' in button_info:
            deck_info = button_info['material_deck']
            if 'init_data' in deck_info:
                init_data = _create_will_display_payload(deck_info, button_index, page)
                command = _create_command_payload(init_data['action'], 'keyDown', button_index, page)
                deck_api.set_button_command(
                    _deck_id,
                    page,
                    button_index,
                    f"{CONFIG_PATH}/pipe_writer.sh '{_bridge_file}' '{json.dumps(command)}'"
                )
                _write_message(json.dumps(init_data))


def _unload_md_buttons(page: int) -> None:
    """
    Reads the buttons configured for use with MaterialDeck and sends willDisappear events.
    """
    if _deck_id not in deck_api.state:
        return

    button_states = deck_api.state[_deck_id]['buttons']
    for button_index, button_info in button_states[page].items():
        if 'material_deck' in button_info:
            deck_info = button_info['material_deck']
            if 'init_data' in deck_info:
                init_data = _create_will_display_payload(deck_info, button_index, page, 'willDisappear')
                _reset_button(button_index, '', page)
                _write_message(json.dumps(init_data))


@_init_required()
def _on_page_changed(old_page: int, new_page: int) -> None:
    _unload_md_buttons(old_page)
    load_md_buttons(new_page)


def _to_context(button_index: int, page: int) -> int:
    return button_index + (page * DECK_COLUMNS * DECK_ROWS)


def _to_button_index(context: int, page: int) -> int:
    return context - (page * DECK_COLUMNS * DECK_ROWS)


def _to_page(context: int) -> int:
    return int(context / (DECK_ROWS * DECK_COLUMNS))


def _create_will_display_payload(deck_info: dict, button_index: int, page: int, event: str = 'willAppear') -> dict:
    init_data = copy.deepcopy(deck_info['init_data'])
    init_data['context'] = _to_context(button_index, page)
    init_data['size'] = {'columns': DECK_COLUMNS, 'rows': DECK_ROWS}
    init_data['event'] = event
    payload = init_data['payload']
    payload['coordinates'] = {
        'column': button_index % DECK_COLUMNS,
        'row': math.floor(button_index / DECK_COLUMNS),
    }
    action = init_data['action']
    settings = payload['settings']
    action_settings = _get_settings_for_action(action, button_index, page)
    for setting_name, setting_value in action_settings.items():
        settings[setting_name] = setting_value
    init_data['deviceIteration'] = page
    init_data['device'] = _deck_id

    return init_data  # type: ignore


def _create_command_payload(action: str, event: str, button_index: int, page: int) -> dict:
    return {
        'action': action,
        'event': event,
        'context': _to_context(button_index, page),
        'payload': {
            'coordinates': {
                'column': button_index % DECK_COLUMNS,
                'row': math.floor(button_index / DECK_COLUMNS),
            },
            'settings': _get_settings_for_action(action, button_index, page),
            'deviceIteration': page,
            'device': _deck_id,
        },
    }


def _get_settings_for_action(action: str, button_index: int, page: int) -> dict:
    button_state = deck_api._button_state(_deck_id, page, button_index)  # pylint: disable=protected-access
    action_settings: dict = button_state.setdefault('material_deck', {}).setdefault('action_settings', {})
    if not action_settings:
        if action == 'soundboard':
            action_settings['soundNr'] = _to_context(button_index + 1, page)
        if action == 'macro':
            action_settings['macroMode'] = 'macroBoard'
            action_settings['macroNumber'] = _to_context(button_index + 1, page)

    return action_settings


def _reset_button(button_index: int, image_path: str, page: int) -> None:
    deck_api.set_button_text(_deck_id, page, button_index, '')
    deck_api.set_button_command(_deck_id, page, button_index, '')
    deck_api.set_button_icon(_deck_id, page, button_index, image_path)


def _write_message(message: str) -> None:
    global _output_queue  # pylint: disable=global-statement,invalid-name
    _output_queue.put(message)


def _handle_set_tile(data: dict) -> None:
    payload = data['payload']
    title = payload.get('title')
    page = _to_page(data['context'])
    if title != deck_api.get_button_text(_deck_id, page, _to_button_index(data['context'], page)):
        deck_api.set_button_text(_deck_id, page, _to_button_index(data['context'], page), title)


def _handle_set_buffer_image(data: dict) -> None:
    payload = data['payload']
    cache_path = _get_path_from_image_id(payload['id'])
    page = _to_page(data['context'])
    if cache_path != deck_api.get_button_icon(_deck_id, page, _to_button_index(data['context'], page)) and\
            Path(cache_path).exists():
        deck_api.set_button_icon(_deck_id, page, _to_button_index(data['context'], page), cache_path)


def _handle_set_image(data: dict) -> None:
    payload = data['payload']
    image_id = payload['id']
    cache_path = _get_path_from_image_id(image_id)
    page = _to_page(data['context'])
    if cache_path != deck_api.get_button_icon(_deck_id, page, _to_button_index(data['context'], page)) and \
            not Path(cache_path).exists():
        Path(Path(cache_path).parent).mkdir(parents=True, exist_ok=True)
        with request.urlopen(payload['image']) as response:
            with open(cache_path, 'wb') as image_file:
                image_file.write(response.read())
    deck_api.set_button_icon(_deck_id, page, _to_button_index(data['context'], page), cache_path)


def _get_path_from_image_id(image_id: str) -> str:
    file_name = image_id
    return f'{IMAGE_CACHE_PATH}/{file_name}'


_original_set_page = deck_api.set_page


def _set_page_override(deck_id: str, page: int) -> None:
    original_page = deck_api.get_page(deck_id)
    _original_set_page(deck_id, page)
    _on_page_changed(original_page, page)


deck_api.set_page = _set_page_override
