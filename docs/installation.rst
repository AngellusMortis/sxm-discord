.. highlight:: shell

============
Installation
============

Requirements
------------

Since this is an audio playing Discord bot, there are obviously some
non-python requirements.

* `Python 3.6`_ +. This is avaible on Windows easily and it is also avaible
  on Mac via Homebrew. Also most Linux distros now either ship with 3.6
  or have an easy way to get it, like SCL for RedHat based distros.

* A SXM account with access to online streaming (not just a car
  radio account)

* A Discord server with a `Bot Application`_ set up on it. You will need
  the "Bot Token"

* `ffmpeg`_ for actually decoding and playing the HLS streams from SXM

* As a requirement from the `Python Discord library`_: `libffi`, `libnacl`,
  `python3-dev`

.. _Python 3.6: https://www.python.org/downloads/
.. _Bot Application: https://discordapp.com/developers/
.. _ffmpeg: https://ffmpeg.org/download.html
.. _Python Discord library: https://discordpy.readthedocs.io/en/latest/intro.html#installing


Stable release
--------------

To install sxm-discord, run this command in your terminal:

.. code-block:: console

    $ pip install sxm-discord

This is the preferred method to install sxm-discord, as it will always install
the most recent stable release.

If you don't have `pip`_ installed, this `Python installation guide`_ can guide
you through the process.

.. _pip: https://pip.pypa.io
.. _Python installation guide: http://docs.python-guide.org/en/latest/starting/installation/


From sources
------------

The sources for sxm-discord can be downloaded from the `Github repo`_.

You can either clone the public repository:

.. code-block:: console

    $ git clone git://github.com/AngellusMortis/sxm-discord

Or download the `tarball`_:

.. code-block:: console

    $ curl  -OL https://github.com/AngellusMortis/sxm-discord/tarball/master

Once you have a copy of the source, you can install it with:

.. code-block:: console

    $ python setup.py install


.. _Github repo: https://github.com/AngellusMortis/sxm-discord
.. _tarball: https://github.com/AngellusMortis/sxm-discord/tarball/master
