
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


import base64
import json
import pickle


def encodeObject(obj):
    """Serialize an object to UTF-8.

    Pickles an object, applies base64 encoding and decode the byte
    buffer to an UTF-8 string.

    Args:
        obj: Object to encode.

    Returns:
        A string describing the serialised object.

    Raises:
        Any exception from pickle.
    """

    return base64.b85encode(pickle.dumps(obj)).decode(encoding='utf-8')


def decodeObject(s):
    """Unserialize an object from UTF-8.

    Encodes an UTF-8 string to a byte buffer, applies base64 decoding
    and tries to unpickle into a python object.

    Args:
        s: String to decode.

    Returns:
        An arbitrary python object contained in the serialized string.

    Raises:
        Any exception from pickle.
    """

    return pickle.loads(base64.b85decode(s.encode(encoding='utf-8')))


def load(path):
    with open(path, 'r', encoding='utf-8') as fp:
        profile = json.load(fp)

    return profile


def save(path, profile):
    with open(path, 'w', encoding='utf-8') as fp:
        json.dump(profile, fp, indent=4)
