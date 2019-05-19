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
            "--prefix",
            type=str,
            default="/music ",
            help="Discord bot command prefix",
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
        params = {
            "token": context.params["token"],
            "prefix": context.params["prefix"],
            "description": context.params["description"],
            "output_channel_id": context.params["output_channel_id"],
        }

        return (DiscordWorker, "discord", params)
