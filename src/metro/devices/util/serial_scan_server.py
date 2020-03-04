
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import serial

import metro
import metro.frontend.devices
from metro.interfaces import auxargs


class Device(metro.CoreDevice):
    arguments = {
        'port': auxargs.SerialPortArgument(),
        'operator': metro.OperatorArgument('scan'),
        'hwflow': False
    }

    descriptions = {
        '__main__': 'Enables remote control of a scan operator over a serial '
                    'connection. This device will block any measurement while '
                    'it is running!',
        'port': 'Serial port to use',
        'operator': 'Scan operator to control',
        'hwflow': 'Might be required for virtual COM ports'
    }

    nextStep = metro.QSignal(float)

    def prepare(self, args, state):
        metro.RunBlock.acquire()

        self.port = serial.Serial(args['port'], baudrate=9600,
                                  timeout=0, write_timeout=0,
                                  bytesize=serial.EIGHTBITS,
                                  stopbits=serial.STOPBITS_ONE,
                                  parity=serial.PARITY_NONE,
                                  rtscts=args['hwflow'],
                                  dsrdtr=args['hwflow'])

        self.moving = False
        self.buf = b''

        self.recv_timer = metro.QTimer(self)
        self.recv_timer.setInterval(200)
        self.recv_timer.timeout.connect(self.on_recv)

        self.operator = args['operator']
        move_scan, scan_ready = self.operator.prepareScan()

        self.nextStep.connect(move_scan)
        scan_ready.connect(self.on_target)

        self.recv_timer.start()

    def finalize(self):
        self.recv_timer.stop()

        self.operator.finalizeScan()
        self.port.close()

        metro.RunBlock.release()

    @metro.QSlot()
    def on_recv(self):
        target = None
        self.buf += self.port.read(1024)

        # The order now is very important. We have to make sure to not
        # emit our move signal before we sent the reply, because some
        # scan operators might run in the same thread, causing a direct
        # call and executing BEFORE our emit returns.
        # We therefor go decode -> reply -> set flag -> move

        # First try to decode a target
        if b';' in self.buf:
            try:
                target = float(self.buf[:self.buf.find(b';')])
            except ValueError:
                pass

            self.buf = b''
        else:
            return

        # At this point we either got a valid target or it was
        # malformed. If no target was sent to so far, we returned
        # already.

        # Now sent the appropriate reply
        if self.moving:
            reply = 'moving;'
        else:
            if target is not None:
                reply = 'started;'
            else:
                reply = 'error;'

        self.port.write(reply.encode('ascii'))

        # And finally move if we had a valid target
        if target is not None:
            self.moving = True  # Set this flag FIRST
            self.nextStep.emit(target)

    @metro.QSlot()
    def on_target(self):
        if self.moving:
            # IMPORTANT: Ignore the signal if we are not meant to
            # actually move. If the serial port is not connected, it may
            # block indefinetely (at least for some virtual port
            # implementations).
            # The reason here is that spec_motor expects no manual
            # setpoints normally to be used between prepareScan and
            # finalizeScan, but this device is currently miusing this
            # semantics a bit...
            self.port.write('ready;'.encode('ascii'))
            self.moving = False
