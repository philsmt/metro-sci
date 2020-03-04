
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import http.server
import threading
import urllib

import metro


class RequestHandler(http.server.BaseHTTPRequestHandler):
    def serve_index(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()

        self.wfile.write(b'<html>'
                         b'<head><title>Metro UI Web Proxy</title></head>'
                         b'<body><a href="/controller">Controller</a><hr>')

        for dev in sorted(metro.getAllDevices(), key=lambda dev: dev._name):
            if isinstance(dev, metro.QtWidgets.QWidget):
                self.wfile.write(
                    '<a href="/device/{1}">{0}</a><br>'.format(
                        dev._name, urllib.parse.quote(dev._name)
                    ).encode('ascii')
                )
            else:
                self.wfile.write('{0}<br>'.format(dev._name).encode('ascii'))

        self.wfile.write(b'</body></html>')

    def serve_widget(self, widget):
        self.send_response(200)
        self.send_header('Content-Type', 'image/jpg')
        self.end_headers()

        buf = metro.QtCore.QByteArray()
        widget.grab().save(metro.QtCore.QBuffer(buf), 'JPG', 100)

        self.wfile.write(buf)

    def do_GET(self):
        if self.path == '/':
            self.serve_index()

        elif self.path == '/controller':
            self.serve_widget(metro.app.main_window)

        elif self.path.startswith('/device/'):
            try:
                widget = metro.getDevice(urllib.parse.unquote(self.path[8:]))
            except KeyError:
                self.send_error(404, 'invalid device name')
            else:
                self.serve_widget(widget)

        else:
            self.send_error(404, 'invalid url')

    def log_message(fmt, *args, **kwargs):
        pass


class Device(metro.CoreDevice):
    arguments = {
        'hostname': '',
        'port': 8000
    }

    def prepare(self, args, state):
        self.server = http.server.HTTPServer((args['hostname'], args['port']),
                                             RequestHandler)

        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()

    def finalize(self):
        self.server.shutdown()
        self.thread.join()
