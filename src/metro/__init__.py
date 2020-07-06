
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


def parse_args(prog_name, cli_hook=None):
    import argparse

    cli_actions = {}

    # Command line arguments
    cli = argparse.ArgumentParser(
        prog=prog_name,
        description='Start the METRO measuring environment.',
        conflict_handler='resolve'
    )

    cli_actions['profile'] = cli.add_argument(
        '--profile', dest='profile', action='store', type=str,
        help='load the given profile (either the name without .json '
             'relative to the profile directory or complete path) on '
             'startup.'
    )

    mode_group = cli.add_mutually_exclusive_group()

    cli_actions['kiosk'] = mode_group.add_argument(
        '--kiosk', dest='kiosk_mode', action='store_true',
        help='start in kiosk mode with hidden controller window and a '
             'single visible device controlling the application state.'
    )

    cli_actions['core'] = mode_group.add_argument(
        '--core', dest='core_mode', action='store_true',
        help='start in core mode without a graphical interface and no '
             'dependency on QtGui or QtWidgets'
    )

    dev_group = cli.add_argument_group(title='development flags')

    cli_actions['experimental'] = dev_group.add_argument(
        '--experimental', dest='experimental', action='store_true',
        help='turns on various experimental features.'
    )

    cli_actions['gc-debug'] = dev_group.add_argument(
        '--gc-debug', dest='gc_debug', action='store', type=int, default=0,
        help='specify the debug level for the python garbage collector.'
    )

    if cli_hook is not None:
        cli_hook(cli, cli_actions)

    return cli.parse_known_args()


def init(args, window_title, local_path='~/.metro',
         profile_path='~/.metro/profiles'):
    import sys

    if args.core_mode:
        def die(msg):
            print('Fatal error during initialization: ' + msg)
            sys.exit(0)
    else:
        def die(msg):
            if sys.version_info[0] == 2:
                import Tkinter  # different name in python2
                tkinter = Tkinter
            else:
                import tkinter

            root = tkinter.Tk()
            root.wm_title(window_title)

            frame = tkinter.Frame(borderwidth=5)

            label = tkinter.Label(frame, justify=tkinter.LEFT, wraplength=450,
                                  text='Fatal error during '
                                       'initialization:\n\n' + msg)
            label.grid(padx=5, pady=5)

            button = tkinter.Button(frame, text='Close',
                                    command=lambda: root.quit())
            button.grid(pady=5)

            frame.grid()
            frame.mainloop()

            sys.exit(0)

    if sys.version_info[:2] < (3, 3):
        die('Requires python version >= 3.3 (found {0})'.format(
            sys.version[:sys.version.find(' ')]
        ))

    try:
        import typing             # noqa (F401)
        import numpy              # noqa (F401)
        from PyQt5 import QtCore  # noqa (F401)

        if not args.core_mode:
            from PyQt5 import QtGui      # noqa (F401)
            from PyQt5 import QtWidgets  # noqa (F401)
    except ImportError as e:
        die('An essential dependency ({0}) could not be imported and is '
            'probably missing'.format(str(e)[str(e)[:-1].rfind('\'')+1:-1]))

    # Populate the metro namespace with a variety of internal modules
    # and parts of Qt. In core mode, several of those are simulated by
    # constructed module objects to allow the definition of related
    # classes without any actual dependency.

    import os
    import pkg_resources

    local_path = os.path.expanduser(local_path)
    os.makedirs(local_path, exist_ok=True)

    profile_path = os.path.expanduser(profile_path)
    os.makedirs(profile_path, exist_ok=True)

    globals().update({
        'WINDOW_TITLE': window_title,
        'LOCAL_PATH': local_path,
        'PROFILE_PATH': profile_path,
        'resource_exists': pkg_resources.resource_exists,
        'resource_filename': pkg_resources.resource_filename,
        'die': die
    })

    globals().update({
        'core_mode': args.core_mode,
        'kiosk_mode': args.kiosk_mode,

        'QtCore': QtCore,
        'QObject': QtCore.QObject,
        'QSignal': QtCore.pyqtSignal,
        'QSlot': QtCore.pyqtSlot,
        'QProperty': QtCore.pyqtProperty,
        'QTimer': QtCore.QTimer,
        'QThread': QtCore.QThread,
        'QConsts': QtCore.Qt,
    })

    if args.core_mode:
        class EmptyQtModule:
            def __getattr__(self, name):
                return QtCore.QObject

        QtGui = EmptyQtModule()  # noqa
        QtWidgets = EmptyQtModule()  # noqa
        QtUic = EmptyQtModule()

    else:
        from PyQt5 import uic as QtUic

    globals().update({
        'QtGui': QtGui,
        'QtWidgets': QtWidgets,
        'QtUic': QtUic
    })

    from .services import channels
    globals().update({
        'channels': channels,
        'getChannel': channels.get,
        'getAllChannels': channels.getAll,
        'queryChannels': channels.query,
        'AbstractChannel': channels.AbstractChannel,
        'ChannelAdapter': channels.ChannelAdapter,
        'StreamChannel': channels.StreamChannel,
        'NumericChannel': channels.NumericChannel,
        'DatagramChannel': channels.DatagramChannel,
        'LogChannel': channels.LogChannel
    })

    from .services import measure
    globals().update({
        'measure': measure,
        'RunBlock': measure.RunBlock,
        'StepBlock': measure.StepBlock,
        'BlockListener': measure.BlockListener,
        'ScanOperator': measure.ScanOperator,
        'TriggerOperator': measure.TriggerOperator,
        'LimitOperator': measure.LimitOperator,
        'StatusOperator': measure.StatusOperator,
        'Measurement': measure.Measurement
    })

    from .services import devices
    globals().update({
        'loadDevice': devices.load,
        'createDevice': devices.create,
        'getDevice': devices.get,
        'getAllDevices': devices.getAll,
        'getOperator': devices.getOperator,
        'getAllOperators': devices.getAllOperators,
        'killAllDevices': devices.killAll,
        'getAvailableDeviceName': devices.getAvailableName,
        'getDefaultDeviceName': devices.getDefaultName,
        'findDeviceForChannel': devices.findDeviceForChannel,
        'checkForDeviceLeaks': devices.checkForLeaks,
        'OperatorThread': devices.OperatorThread,
        'GenericDevice': devices.GenericDevice,
        'DisplayDevice': devices.DisplayDevice,
        'CoreDevice': devices.CoreDevice,
        'TransientDevice': devices.TransientDevice,
        'WidgetDevice': devices.WidgetDevice,
        'DeviceGroup': devices.DeviceGroup,
        'WindowGroupWidget': devices.WindowGroupWidget,
        'TabGroupWidget': devices.TabGroupWidget
    })

    from .frontend import arguments
    globals().update({
        'arguments': arguments,
        'AbstractArgument': arguments.AbstractArgument,
        'IndexArgument': arguments.IndexArgument,
        'ComboBoxArgument': arguments.ComboBoxArgument,
        'DeviceArgument': arguments.DeviceArgument,
        'ChannelArgument': arguments.ChannelArgument,
        'OperatorArgument': arguments.OperatorArgument,
        'FileArgument': arguments.FileArgument
    })


def init_mp_support():
    try:
        core_mode
    except NameError:
        pass
    else:
        return

    class _Args:
        core_mode = False
        kiosk_mode = False

    init(_Args, 'Metro')


def start(prog_name='metro', window_title='Metro', cli_hook=None):
    args, argv_left = parse_args(prog_name, cli_hook=cli_hook)
    init(args, window_title)

    from .frontend import application

    if core_mode:  # noqa
        app_class = application.CoreApplication
    else:
        app_class = application.GuiApplication

    app = app_class(args, argv_left)
    app.exec_()
