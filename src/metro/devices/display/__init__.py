
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


def getDefault(channel):
    if channel.__class__.__name__ == 'StreamChannel':
        if channel.hint == channel.INDICATOR_HINT:
            if channel.shape == 1:
                return 'display.plot'
            elif channel.shape == 2:
                return 'display.plot_xy'
            else:
                return 'display.value'
        elif channel.shape == 0 and channel.hint == channel.WAVEFORM_HINT:
            return 'display.waveform'
        elif channel.shape == 1 and channel.hint == channel.HISTOGRAM_HINT:
            return 'display.hist1d'
        elif channel.shape == 2 and channel.hint == channel.HISTOGRAM_HINT:
            return 'display.hist2d'
    elif channel.__class__.__name__ == 'DatagramChannel':
        if channel.hint == channel.INDICATOR_HINT:
            return 'display.image'

    return None
