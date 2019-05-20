=====
Usage
=====

.. warning:: Designed for PERSONAL USE ONLY

    `sxm-discord` is a 100% unofficial project and you use it at your own risk.
    It is designed to be used for personal use with a small number of users
    listening to it at once. Similar to playing music over a speakers from the
    radio directly. Using `sxm-discord` in any corporate setting, to
    attempt to priate music, or to try to make a profit off your subscription
    may result in you getting in legal trouble.


Command Line Interface
======================

`sxm-discord` is a Player Class for `sxm-player`_. Please be sure to
fimilarize yourself with the `CLI interface`_ for that project first.

.. _sxm-player: https://github.com/AngellusMortis/sxm-player
.. _CLI interface: https://sxm-player.readthedocs.io/en/latest/usage.html

Basic Bot
---------

Command to start the bot

.. code-block:: console

    $ sxm-player sxm_discord.DiscordPlayer --token discord_bot_token


By default, all of the bot commands are prefixed with `/music `, if you would
like that to be something different, you can. This will set the command prefix
to `$`.

.. code-block:: console

    $ sxm-player sxm_discord.DiscordPlayer --global_prefix $


Discord Commands
================

This assumes you have not changed the bot prefix with the `--global_prefix`
option. Otherwise your bot commands will be a little different.

Help
----

All of the commands can be PM to a user with detailed information:

.. code-block:: console

    $ /music help

Utility
-------

Call the bot to the current voice channel. This will move the bot without
stopping the tunes.

.. code-block:: console

    $ /music summon

Change volumes. Numbers range from 0% to 100%, bot always starts at 25%.
No argument retrieves volume level.

.. code-block:: console

    $ /music volume       # gets current volume level
    $ /music volume 100   # sets volume to 100%
    $ /music volume 25    # sets volume to default of 25%

Stops all music playback and kicks bot of out voice channel.

.. code-block:: console

    $ /music stop

Resets the bot if it gets stuck in a voice channel. If playing music,
also stops.

.. code-block:: console

    $ /music reset

Retrieves what the bot is currently playing.

.. code-block:: console

    $ /music playing

Prints a list of the most recent songs played. Defaults to top 3, can display
up to 10.

.. code-block:: console

    $ /music recent       # displays top 3 songs/shows
    $ /music recent 1     # displaying the most recent song/show

SXM Commands
------------

PMs the user a full list of all avaiable SXM channels

.. code-block:: console

    $ /music sxm channels

Starts playing a SXM channel. `<channel_id>` can be the channel ID,
the channel name or the station number that you see in your car or on the
Web player.

.. code-block:: console

    $ /music sxm channel <channel_id>
    $ /music sxm channel octane       # will play #37 Octane
    $ /music sxm channel 37           # will play #37 Octane

Archive Playback Commands
-------------------------

All of these commands require archiving to be enabled (`-o` argument from
command line).

Search archive for avaible songs. `<search>` string matches again song title or
artist name. Returns only the 10 most recent matches.

.. code-block:: console

    $ /music sxm songs <search>

Search archive for avaible shows. `<search>` string matches again title of
episode or the title of the show. Returns only the 10 most recent matches.

.. code-block:: console

    $ /music sxm shows <search>

Adds a song to the now playing play queue. `<guid>` must be the one returned
from `songs` command.

.. code-block:: console

    $ /music sxm song <guid>

Adds a show to the now playing play queue. `<guid>` must be the one returned
from `shows` command.

.. code-block:: console

    $ /music sxm show <guid>

Skips the current playing song/show. If it is the last one, it will
effectivly calling the `stop` command.

.. code-block:: console

    $ /music sxm skip

Display all of the songs/shows in the now playing queue

.. code-block:: console

    $ /music sxm upcoming

Creates a random infinite playlist of archived songs from a list of channels.
`<channel_id>` is a comma delimited list of channel IDs or the station number.
By default, there must be at least 40 unique songs for that station for the
bot to consider it. You can add an optional arg to override that limit.

.. code-block:: console

    $ /music sxm playlist <channel_ids> [threshold]
    $ /music sxm playlist octane      # threshold=40, playlist from #37 Octane
    $ /music sxm playlist 37,41       # threshold=40, playlist from #37 and #41
    $ /music sxm playlist 37 20       # threshold=20, playlist from #37 Octane
