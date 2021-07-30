=======
History
=======

0.2.5 (2021-07-30)
------------------

* Fixes event loop eventually dying out
* Improves bot automatically disconnecting from chat
* Fixes sxm_player.music logger name
* Adds bot logging

0.2.4 (2021-07-21)
------------------

* Adds more logging
* Fixes `sxm_player.music` logger name

0.2.3 (2021-07-18)
------------------

* Removes `volume` command and uses `FFmpegOpusAudio`

0.2.2 (2021-07-17)
------------------

* Adds env var for `--root-command`: `SXM_DISCORD_ROOT_COMMAND`
* Adds env var for `--output-channel-id`: `SXM_DISCORD_OUTPUT_CHANNEL`

0.2.1 (2021-07-17)
------------------

* Adds env var for `--token`: `SXM_DISCORD_TOKEN`

0.2.0 (2021-07-17)
------------------

* Replaces setuptools with filt
* Updates linting
* Replaces TravisCI with Github Actions
* Updates for `sxm-player=0.2.1` client
* Replaces old school Discord commands with proper slash commands
* Adds pydantic to `sxm_discord`

0.1.0 (2018-12-25)
------------------

* First release on PyPI.
