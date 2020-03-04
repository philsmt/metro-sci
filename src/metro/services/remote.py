# flake8: noqa

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


# OPTION 1
# So we need a server and a simple protocol to query the available
# channels from the server and for the client to select/deselect one
# for remote duplication.
# Once a channel is selected, a special subscriber will be created that
# forwards all samples to the client until it is deselected.

# OPTION 2
# One connection per channel from the client to the server. Optionally,
# it is also possible to query the channels instead of listening or at
# least to do that until listening to a channel.

# The server side should almost be completely autonomous except for
# starting/stopping the server.

# On the client side, a remote channel is created by calling
# AbstractChannel.setRemote(...).


import multiprocessing
