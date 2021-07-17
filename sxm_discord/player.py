import os
from typing import List, Optional, Tuple, Type

import click
from sxm_player.models import PlayerState
from sxm_player.players import BasePlayer, Option
from sxm_player.runner import Runner
from sxm_player.workers import BaseWorker

from sxm_discord.utils import set_root_command


class DiscordPlayer(BasePlayer):
    params: List[click.Parameter] = [
        Option(
            "--token",
            required=True,
            type=str,
            help="Discord bot token",
            envvar="SXM_DISCORD_TOKEN",
        ),
        Option(
            "--root-command",
            type=str,
            default="music",
            help="Root slash command",
        ),
        Option(
            "--description",
            type=str,
            default="SXM radio bot for Discord",
            help="Bot description inside of Discord",
        ),
        Option(
            "--output-channel-id",
            type=int,
            help="Discord channel ID for various bot status updates",
        ),
    ]

    @staticmethod
    def get_params() -> List[click.Parameter]:
        return DiscordPlayer.params

    @staticmethod
    def get_worker_args(
        runner: Runner, state: PlayerState, **kwargs
    ) -> Optional[Tuple[Type[BaseWorker], str, dict]]:

        context = click.get_current_context()
        processed_folder: Optional[str] = None
        if "output_folder" in kwargs and kwargs["output_folder"] is not None:
            processed_folder = os.path.join(kwargs["output_folder"], "processed")

        params = {
            "token": context.meta["token"],
            "description": context.meta["description"],
            "output_channel_id": context.meta["output_channel_id"],
            "processed_folder": processed_folder,
            "sxm_status": state.sxm_running,
            "stream_data": state.stream_data,
            "channels": state.get_raw_channels(),
            "raw_live_data": state.get_raw_live(),
        }

        set_root_command(context.meta["root_command"])
        # must be imported _after_ `set_root_command`
        from sxm_discord.bot import DiscordArchivedWorker, DiscordWorker

        if processed_folder is None:
            return (DiscordWorker, "discord", params)
        return (DiscordArchivedWorker, "discord", params)
