from dataclasses import dataclass
from typing import List, Union

from discord.ext.commands import BadArgument, Converter
from sxm.models import XMChannel

from sxm_discord.utils import get_cog


class XMChannelConverter(Converter):
    async def convert(self, ctx, channel_id: str) -> XMChannel:
        channel: XMChannel = get_cog(ctx)._state.get_channel(channel_id)

        if channel is None:
            raise BadArgument(
                f"`channel_id` is invalid. Use `/{ctx.name} sxm channels` for "
                f"a list of valid channels"
            )

        return channel


class XMChannelListConverter(XMChannelConverter):
    async def convert(  # type: ignore
        self, ctx, channel_ids: Union[str, List[str]]
    ) -> List[XMChannel]:
        if isinstance(channel_ids, str):
            channel_ids = channel_ids.split(",")
        channels: List[XMChannel] = []

        for channel_id in channel_ids:
            channel = await super().convert(ctx, channel_id)
            channels.append(channel)

        if len(channels) > 5:
            raise BadArgument("too many `channel_ids`. Cannot be more than 5")

        return channels


@dataclass
class IntRangeConverter(Converter):
    min_number: int = 1
    max_number: int = 10
    name: str = "argument"

    @property
    def message(self):
        return (
            f"`{self.name}` must be a number between "
            f"{self.min_number} and {self.max_number}"
        )

    async def convert(self, ctx, argument: Union[str, int]) -> int:
        try:
            argument = int(argument)
        except ValueError:
            raise BadArgument(self.message)

        if argument > self.max_number or argument < self.min_number:
            raise BadArgument(self.message)

        return argument


@dataclass
class CountConverter(IntRangeConverter):
    name: str = "count"
