"""
Provides direct communication between the El Gato Streamdeck and the Material Deck module.
"""

import copy
import json
import logging
from pathlib import Path
import math
from queue import Queue
from typing import Optional, Union
from urllib import request

from streamdeck_ui import api as deck_api, gui as deck_gui
from streamdeck_ui.ui_main import Ui_MainWindow

CONNECTED_PAYLOAD = json.dumps({'target': 'MD', 'type': 'connected', 'data': 'SD'})
INITIALIZE_PAYLOAD = json.dumps({'source': 'SD', 'type': 'version', 'version': '1.4.2'})
CONFIG_PATH = f'{Path.home()}/.stream-deck-ui-md-bridge'
IMAGE_CACHE_PATH = f'{CONFIG_PATH}/image_cache'
DECK_CONFIG_FILE = f'{Path.home()}/.streamdeck_ui.json'
MATERIAL_FOUNDRY_IMAGE = f'{CONFIG_PATH}/MaterialFoundry512x512.png'
FOUNDRY_PAGE = 0
DECK_COLUMNS = 8
DECK_ROWS = 4

log = logging.getLogger(__name__)
_deck_id: str = ''
_bridge_file: str = ''
_output_queue: Queue
_ui: Ui_MainWindow


def init(bridge_file: str, output_queue: Queue, ui: Ui_MainWindow) -> None:
    """
    Initializes and chooses the Stream Deck to use
    """
    global _deck_id, _bridge_file, _output_queue, _ui  # pylint: disable=global-statement,invalid-name
    _bridge_file = bridge_file
    _output_queue = output_queue
    _ui = ui

    Path(IMAGE_CACHE_PATH).mkdir(parents=True, exist_ok=True)
    while not _deck_id:
        deck_ids = list(deck_api.decks.keys())
        if deck_ids:
            _deck_id = deck_ids[0]

    log.info(f'Loaded with deck ID: {_deck_id}')


def disconnect() -> None:
    """
    Replaces all buttons configured with Material Foundry with placeholders.
    """
    button_states = deck_api.state[_deck_id]['buttons']
    for _page, buttons in button_states.items():
        for button_index, button_info in buttons.items():
            if 'material_deck' in button_info:
                _reset_button(button_index, MATERIAL_FOUNDRY_IMAGE)


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


def key_up_callback(deck_id: str, key: int, state: bool) -> None:
    """
    Handles key up events by sending the necessary information to the output queue.
    """
    if state:
        log.warning('Released callback called while the state boolean is true')
    button_state = deck_api._button_state(deck_id, FOUNDRY_PAGE, key)  # pylint: disable=protected-access
    md_info = button_state.get('material_deck')
    if md_info:
        _write_message(json.dumps(_create_command_payload(md_info['init_data']['action'], 'keyUp', key)))


def md_action_changed(button_index: int, action: str) -> None:
    """
    Handles changing the type of action Material Deck listens for.
    """
    global _ui  # pylint: disable=global-statement,invalid-name
    button_state = deck_api._button_state(_deck_id, FOUNDRY_PAGE, button_index)  # pylint: disable=protected-access
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
        command = _create_command_payload(action, 'keyDown', button_index)
        deck_api.set_button_command(
            _deck_id,
            FOUNDRY_PAGE,
            button_index,
            f"{CONFIG_PATH}/pipe_writer.sh '{_bridge_file}' '{json.dumps(command)}'"
        )

        _write_message(json.dumps(_create_will_appear_payload(deck_info, button_index)))
    elif 'material_deck' in button_state:
        previous_action = button_state['material_deck'].get('init_data', {}).get('action', '')
        del button_state['material_deck']
        _reset_button(button_index, '')
        _write_message(json.dumps({
            'event': 'willDisappear',
            'action': previous_action,
            'payload': {
                'coordinates': {
                    'column': button_index % DECK_COLUMNS,
                    'row': math.floor(button_index / DECK_COLUMNS),
                },
            },
            'context': button_index,
            'device': _deck_id,
        }))
    deck_api.export_config(DECK_CONFIG_FILE)
    deck_gui.redraw_buttons(_ui)


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


def load_md_buttons() -> None:
    """
    Reads the buttons configured for use with MaterialDeck and sends willAppear events.
    """
    if _deck_id not in deck_api.state:
        return

    button_states = deck_api.state[_deck_id]['buttons']
    for _page, buttons in button_states.items():
        for button_index, button_info in buttons.items():
            if 'material_deck' in button_info:
                deck_info = button_info['material_deck']
                if 'init_data' in deck_info:
                    init_data = _create_will_appear_payload(deck_info, button_index)
                    command = _create_command_payload(init_data['action'], 'keyDown', button_index)
                    deck_api.set_button_command(
                        _deck_id,
                        FOUNDRY_PAGE,
                        button_index,
                        f"{CONFIG_PATH}/pipe_writer.sh '{_bridge_file}' '{json.dumps(command)}'"
                    )
                    _write_message(json.dumps(init_data))


def _create_will_appear_payload(deck_info: dict, button_index: int) -> dict:
    init_data = copy.deepcopy(deck_info['init_data'])
    init_data['context'] = button_index
    init_data['size'] = {'columns': DECK_COLUMNS, 'rows': DECK_ROWS}
    payload = init_data['payload']
    payload['coordinates'] = {
        'column': button_index % DECK_COLUMNS,
        'row': math.floor(button_index / DECK_COLUMNS),
    }
    action = init_data['action']
    settings = payload['settings']
    action_settings = _get_settings_for_action(action, button_index)
    for setting_name, setting_value in action_settings.items():
        settings[setting_name] = setting_value
    init_data['deviceIteration'] = 0
    init_data['device'] = _deck_id

    return init_data  # type: ignore


def _create_command_payload(action: str, event: str, button_index: int) -> dict:
    return {
        'action': action,
        'event': event,
        'context': button_index,
        'payload': {
            'coordinates': {
                'column': button_index % DECK_COLUMNS,
                'row': math.floor(button_index / DECK_COLUMNS),
            },
            'settings': _get_settings_for_action(action, button_index),
            'deviceIteration': 0,
            'device': _deck_id,
        },
    }


def _get_settings_for_action(action: str, button_index: int) -> dict:
    action_settings: dict = {}
    if action == 'soundboard':
        action_settings['soundNr'] = button_index + 1
    if action == 'macro':
        action_settings['macroMode'] = 'macroBoard'
        action_settings['macroNumber'] = button_index + 1

    return action_settings


def _reset_button(button_index: int, image_path: str) -> None:
    deck_api.set_button_text(_deck_id, FOUNDRY_PAGE, button_index, '')
    deck_api.set_button_command(_deck_id, FOUNDRY_PAGE, button_index, '')
    deck_api.set_button_icon(_deck_id, FOUNDRY_PAGE, button_index, image_path)


def _write_message(message: str) -> None:
    global _output_queue  # pylint: disable=global-statement,invalid-name
    _output_queue.put(message)


def _handle_set_tile(data: dict) -> None:
    payload = data['payload']
    title = payload.get('title')
    if title != deck_api.get_button_text(_deck_id, FOUNDRY_PAGE, data['context']):
        deck_api.set_button_text(_deck_id, FOUNDRY_PAGE, data['context'], title)


def _handle_set_buffer_image(data: dict) -> None:
    payload = data['payload']
    cache_path = _get_path_from_image_id(payload['id'])
    if cache_path != deck_api.get_button_icon(_deck_id, FOUNDRY_PAGE, data['context']) and Path(cache_path).exists():
        deck_api.set_button_icon(_deck_id, FOUNDRY_PAGE, data['context'], cache_path)


def _handle_set_image(data: dict) -> None:
    payload = data['payload']
    image_id = payload['id']
    cache_path = _get_path_from_image_id(image_id)
    if cache_path != deck_api.get_button_icon(_deck_id, FOUNDRY_PAGE, data['context']) and \
            not Path(cache_path).exists():
        Path(Path(cache_path).parent).mkdir(parents=True, exist_ok=True)
        with request.urlopen(payload['image']) as response:
            with open(cache_path, 'wb') as image_file:
                image_file.write(response.read())
    deck_api.set_button_icon(_deck_id, FOUNDRY_PAGE, data['context'], cache_path)


def _get_path_from_image_id(image_id: str) -> str:
    file_name = image_id
    return f'{IMAGE_CACHE_PATH}/{file_name}'
