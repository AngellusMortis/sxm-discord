from discord import TextChannel
from discord_slash import SlashContext  # type: ignore

from sxm_discord.utils import get_cog, send_message

__all__ = ["no_pm", "require_voice"]


async def no_pm(ctx: SlashContext):
    if not isinstance(ctx.channel, TextChannel):
        await send_message(
            ctx,
            "Can only be used in a text chat room in a Discord server",
        )
        return False
    return True


async def require_voice(ctx: SlashContext):
    if not await no_pm(ctx):
        return False

    if ctx.author.voice is None:
        await send_message(
            ctx,
            "Can only be ran if you are in a voice channel",
        )
        return False
    return True


async def require_player_voice(ctx: SlashContext):
    if get_cog(ctx).player.voice is None:
        await send_message(
            ctx,
            "I do not seem to be in a voice channel",
        )
        return False
    return True


async def require_sxm(ctx: SlashContext):
    if get_cog(ctx)._state.sxm_running:
        return True
    await send_message(ctx, "SXM client is offline")
    return False


async def require_matching_voice(ctx: SlashContext):
    if not await require_voice(ctx):
        return False

    if not await require_player_voice(ctx):
        return False

    if ctx.author.voice is None or get_cog(ctx).player.voice is None:
        return False

    author_channel = ctx.author.voice.channel
    player_channel = get_cog(ctx).player.voice.channel

    if author_channel.id != player_channel.id:
        await send_message(
            ctx,
            "I am not in the same voice channel as you",
        )
        return False
    return True


async def is_playing(ctx: SlashContext):
    if not get_cog(ctx).player.is_playing:
        await send_message(
            ctx,
            "Nothing is playing",
        )
        return False
    return True
