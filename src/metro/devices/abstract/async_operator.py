
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


# Basic multhreading device using Qt primitives
#
# This device template takes care of the basic housekeeping of
# offloading a QObject to a separate QThread with full support for
# thread-safe slot connections.


import metro


class Operator(metro.QObject):
    _ready = metro.QSignal(object)
    _error = metro.QSignal(object)

    def __init__(self, args):
        super().__init__()

        self.args = args

    @metro.QSlot()
    def _on_started(self):
        try:
            res = self.prepare(self.args)
        except Exception as e:
            self.showError('Unchecked exception in Operator.prepare, please '
                           'see details.', e)
        else:
            self._ready.emit(res)

    @metro.QSlot()
    def _on_finished(self):
        try:
            self.finalize()
        except Exception as e:
            self.showError('Unchecked exception in Operator.finalize, please '
                           'see details.', e)

    def showError(self, text, details=None):
        self._error.emit((text, details))

    def showException(self, e):
        self._error.emit(e)

    def prepare(self, args):
        pass

    def finalize(self):
        pass


class BaseDevice(object):
    def prepare(self, operator_cls, operator_args, state):
        metro.RunBlock.acquire()

        self.operator = operator_cls(operator_args)
        self.thread = metro.QThread(self)
        self.operator.moveToThread(self.thread)

        self.thread.started.connect(self.operator._on_started)
        self.thread.finished.connect(self.operator._on_finished)
        self.operator._ready.connect(self._on_ready)
        self.operator._error.connect(self._on_error)

        self._prepared_completed = False
        self.thread.start()

    def finalize(self):
        self.thread.quit()
        self.thread.wait()

    def operatorReady(self, res):
        pass

    @metro.QSlot(object)
    def _on_ready(self, res):
        self._prepared_completed = True

        self.operatorReady(res)

        metro.RunBlock.release()

    @metro.QSlot(object)
    def _on_error(self, err):
        if isinstance(err, Exception):
            self.showException(err)
        else:
            self.showError(*err)

        if not self._prepared_completed:
            metro.RunBlock.release()
            self.kill()


class CoreDevice(BaseDevice, metro.CoreDevice):
    pass


class WidgetDevice(BaseDevice, metro.WidgetDevice):
    pass
