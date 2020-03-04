
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


class FittingCallback(object):
    def dataAdded(self, x, y):
        pass


class Device(object):
    def _notifyFittingCallbacks(self, x, y):
        try:
            cbs = self.__fitting_callbacks
        except AttributeError:
            pass
        else:
            for cb in cbs:
                cb.dataAdded(x, y)

    def addFittingCallback(self, func: FittingCallback) -> None:
        try:
            cbs = self.__fitting_callbacks
        except AttributeError:
            self.__fitting_callbacks = [func]
        else:
            cbs.append(func)

    def removeFittingCallback(self, func: FittingCallback) -> None:
        try:
            self.__fitting_callbacks.remove(func)
        except AttributeError:
            pass
        except ValueError:
            pass

    def addFittedCurve(self, tag, x, y):
        raise NotImplementedError('addFittedCurve')

    def removeFittedCurve(self, tag):
        raise NotImplementedError('removeFittedCurve')
