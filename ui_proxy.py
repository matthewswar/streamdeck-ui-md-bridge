"""
Originally copied from streamdeck_ui.gui, this module allows me to get the references to manipulate the QT application.
"""

from functools import partial
import logging
import time
from typing import Callable, Tuple

from streamdeck_ui import api
from streamdeck_ui.config import LOGO
from streamdeck_ui.gui import (  # noqa: F811 pylint: disable=reimported
    build_device,
    change_brightness,
    change_page,
    dim_all_displays,
    Dimmer,
    dimmers,
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
    update_button_command,
    update_button_keys,
    update_button_write,
    update_change_brightness,
    update_switch_page
)

log = logging.getLogger(__name__)


def create_app(key_up_callback: Callable[[str, int, bool], None]) -> Tuple[QApplication, MainWindow]:
    """
    Sets up the QApplication to use on the main thread without calling app.exec_()
    """
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
    key_up_callback: Callable[[str, int, bool], None],
    deck_id: str,
    key: int,
    state: bool
) -> None:
    if state:
        handle_keypress(deck_id, key, state)
    else:
        key_up_callback(deck_id, key, state)
