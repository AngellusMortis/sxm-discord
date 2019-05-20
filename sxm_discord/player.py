import os
from typing import List, Optional, Tuple, Type

import click

from sxm_player.models import PlayerState
from sxm_player.players import BasePlayer, Option
from sxm_player.runner import Runner
from sxm_player.workers import BaseWorker

from .bot import DiscordWorker


class DiscordPlayer(BasePlayer):
    params = [
        Option("--token", required=True, type=str, help="Discord bot token"),
        Option(
            "--global-prefix",
            type=str,
            default="/music ",
            help="Main Discord bot command prefix",
        ),
        Option(
            "--sxm-prefix",
            type=str,
            default="/sxm ",
            help="SXM Discord bot command prefix (short for `/music sxm `)",
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
        return DiscordPlayer.params  # type: ignore

    @staticmethod
    def get_worker_args(
        runner: Runner, state: PlayerState, **kwargs
    ) -> Optional[Tuple[Type[BaseWorker], str, dict]]:

        context = click.get_current_context()
        processed_folder: Optional[str] = None
        if "output_folder" in kwargs and kwargs["output_folder"] is not None:
            processed_folder = os.path.join(
                kwargs["output_folder"], "processed"
            )

        params = {
            "token": context.params["token"],
            "global_prefix": context.params["global_prefix"],
            "sxm_prefix": context.params["sxm_prefix"],
            "description": context.params["description"],
            "output_channel_id": context.params["output_channel_id"],
            "processed_folder": processed_folder,
            "sxm_status": state.sxm_running,
            "stream_data": state.stream_data,
            "channels": state.get_raw_channels(),
            "raw_live_data": state.get_raw_live(),
        }

        return (DiscordWorker, "discord", params)
