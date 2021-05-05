"""
Originally copied from streamdeck_ui.gui, this module allows me to get the references to manipulate the QT application.
"""

from functools import partial
import logging
import time
from typing import Callable, List, Optional, Tuple

from PySide2.QtWidgets import QComboBox, QFormLayout, QLabel  # pylint: disable=no-name-in-module
from streamdeck_ui import api, gui
from streamdeck_ui.config import LOGO
from streamdeck_ui.gui import (  # noqa: F811 pylint: disable=reimported
    build_device,
    change_brightness,
    change_page,
    dim_all_displays,
    Dimmer,
    dimmers,
    DraggableButton,
    export_config,
    handle_keypress,
    import_config,
    LOGO,
    MainWindow,
    QAction,
    QApplication,
    QIcon,
    QMenu,
    QSystemTrayIcon,
    QTimer,
    queue_text_change,
    select_image,
    show_settings,
    sync,
    remove_image,
    Ui_MainWindow,
    update_button_command,
    update_button_keys,
    update_button_write,
    update_change_brightness,
    update_switch_page
)

_MATERIAL_DECK_ACTIONS = ['', 'macro', 'soundboard']

log = logging.getLogger(__name__)
_get_md_action_value: Callable[[int], str]


def create_app(
    get_md_action_value: Callable[[int], str],
    key_up_callback: Optional[Callable[[str, int, bool], None]] = None,
    md_action_callback: Optional[Callable[[int, str], None]] = None,
) -> Tuple[QApplication, MainWindow]:
    """
    Sets up the QApplication to use on the main thread without calling app.exec_()
    """
    global _get_md_action_value  # pylint: disable=global-statement,invalid-name
    _get_md_action_value = get_md_action_value
    app = QApplication([])

    logo = QIcon(LOGO)
    main_window = MainWindow()
    ui = main_window.ui
    main_window.setWindowIcon(logo)
    tray = QSystemTrayIcon(logo, app)
    tray.activated.connect(main_window.systray_clicked)

    menu = QMenu()
    action_dim = QAction('Dim display (toggle)')
    action_dim.triggered.connect(dim_all_displays)
    action_configure = QAction('Configure...')
    action_configure.triggered.connect(main_window.bring_to_top)
    menu.addAction(action_dim)
    menu.addAction(action_configure)
    menu.addSeparator()
    action_exit = QAction('Exit')
    action_exit.triggered.connect(app.exit)
    menu.addAction(action_exit)

    tray.setContextMenu(menu)

    ui.text.textChanged.connect(partial(queue_text_change, ui))
    ui.command.textChanged.connect(partial(update_button_command, ui))
    ui.keys.textChanged.connect(partial(update_button_keys, ui))
    ui.write.textChanged.connect(partial(update_button_write, ui))
    ui.change_brightness.valueChanged.connect(partial(update_change_brightness, ui))
    ui.switch_page.valueChanged.connect(partial(update_switch_page, ui))
    ui.imageButton.clicked.connect(partial(select_image, main_window))
    ui.removeButton.clicked.connect(partial(remove_image, main_window))
    ui.settingsButton.clicked.connect(partial(show_settings, main_window))

    md_label = QLabel(ui.groupBox)
    md_label.setObjectName('md_label')
    md_label.setText('MD Action:')
    ui.formLayout.setWidget(7, QFormLayout.LabelRole, md_label)

    md_action = QComboBox(ui.groupBox)
    md_action.setObjectName('md_action')
    md_action.addItems(_MATERIAL_DECK_ACTIONS)
    md_action.currentIndexChanged.connect(partial(_md_action_changed, md_action_callback))
    ui.formLayout.setWidget(7, QFormLayout.FieldRole, md_action)
    ui.md_action = md_action

    api.streamdesk_keys.key_pressed.connect(partial(_extended_handle_key_press, key_up_callback))

    items = api.open_decks().items()
    if len(items) == 0:
        print('Waiting for Stream Deck(s)...')
        while len(items) == 0:
            time.sleep(3)
            items = api.open_decks().items()

    for deck_id, deck in items:
        ui.device_list.addItem(f"{deck['type']} - {deck_id}", userData=deck_id)
        dimmers[deck_id] = Dimmer(
            api.get_display_timeout(deck_id),
            api.get_brightness(deck_id),
            partial(change_brightness, deck_id),
        )
        dimmers[deck_id].reset()

    build_device(ui)
    ui.device_list.currentIndexChanged.connect(partial(build_device, ui))

    ui.pages.currentChanged.connect(partial(change_page, ui))

    ui.actionExport.triggered.connect(partial(export_config, main_window))
    ui.actionImport.triggered.connect(partial(import_config, main_window))
    ui.actionExit.triggered.connect(app.exit)

    timer = QTimer()
    timer.timeout.connect(partial(sync, ui))
    timer.start(1000)

    api.render()
    tray.show()

    return (app, main_window)


def _extended_handle_key_press(
    key_up_callback: Optional[Callable[[str, int, bool], None]],
    deck_id: str,
    key: int,
    state: bool
) -> None:
    if state:
        handle_keypress(deck_id, key, state)
    elif key_up_callback:
        key_up_callback(deck_id, key, state)


def _md_action_changed(
    md_action_callback: Optional[Callable[[int, str], None]],
    action_index: int
) -> None:
    if md_action_callback:
        md_action_callback(gui.selected_button.index, _MATERIAL_DECK_ACTIONS[action_index])


_original_button_clicked = gui.button_clicked


def _button_clicked_override(
    ui: Ui_MainWindow,
    clicked_button: DraggableButton,
    buttons: List[DraggableButton]
) -> None:
    global _get_md_action_value  # pylint: disable=global-statement,invalid-name
    _original_button_clicked(ui, clicked_button, buttons)
    button_id = gui.selected_button.index
    md_action_value = _get_md_action_value(button_id)
    ui.md_action.setCurrentIndex(_MATERIAL_DECK_ACTIONS.index(md_action_value))


gui.button_clicked = _button_clicked_override
