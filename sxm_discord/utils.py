from typing import Tuple, List, Optional
from discord import DMChannel, Embed, TextChannel
from discord.ext.commands import errors

from sxm.models import XMSong, XMImage, XMChannel, XMCut, XMArt
from sxm_player.models import PlayerState

__all__ = ["send_message"]


async def send_message(
    ctx, message: str = None, embed: Embed = None, sep: str = ", "
):
    if message is None and embed is None:
        raise errors.CommandError("A message or a embed must be provided")

    if isinstance(ctx, TextChannel):
        channel = ctx
    elif isinstance(ctx.message.channel, (DMChannel, TextChannel)):
        channel = ctx.message.channel
        if message is not None:
            message = f"{ctx.message.author.mention}{sep}{message}"
        else:
            message = ctx.message.author.mention

    await channel.send(message, embed=embed)


def generate_now_playing_embed(state: PlayerState) -> Tuple[XMChannel, Embed]:
    xm_channel = state.get_channel(state.stream_channel)

    if state.live is not None:
        cut = state.live.get_latest_cut(now=state.radio_time)
        episode = state.live.get_latest_episode(now=state.radio_time)

    np_title = None
    np_author = None
    np_thumbnail = None
    np_album = None
    np_episode_title = None

    if cut is not None and isinstance(cut.cut, XMSong):
        song = cut.cut
        np_title = song.title
        np_author = song.artists[0].name

        if song.album is not None:
            album = song.album
            if album.title is not None:
                np_album = album.title

            np_thumbnail = get_art_url_by_size(album.arts, "MEDIUM")

    if episode is not None:
        episode = episode.episode
        np_episode_title = episode.long_title

        if np_thumbnail is None:
            np_thumbnail = get_art_thumb_url(episode.show.arts)

    embed = Embed(title=np_title)
    if np_author is not None:
        embed.set_author(name=np_author)
    if np_thumbnail is not None:
        embed.set_thumbnail(url=np_thumbnail)
    if np_album is not None:
        embed.add_field(name="Album", value=np_album)
    embed.add_field(name="SXM", value=xm_channel.pretty_name, inline=True)
    if np_episode_title is not None:
        embed.add_field(name="Show", value=np_episode_title, inline=True)

    return xm_channel, embed


def get_recent_songs(
    state: PlayerState, count: int
) -> Tuple[XMChannel, List[XMCut], Optional[XMCut]]:
    xm_channel = state.get_channel(state.stream_channel)

    if state.live is None or xm_channel is None:
        return (xm_channel, [], None)

    song_cuts = []
    now = state.radio_time
    latest_cut = state.live.get_latest_cut(now)

    for song_cut in reversed(state.live.song_cuts):
        if song_cut == latest_cut:
            song_cuts.append(song_cut)
            continue

        end = int(song_cut.time + song_cut.duration)
        if (
            state.start_time is not None
            and song_cut.time < now
            and (end > state.start_time or song_cut.time > state.start_time)
        ):
            song_cuts.append(song_cut)

        if len(song_cuts) >= count:
            break

    return xm_channel, song_cuts, latest_cut


def get_art_url_by_size(arts: List[XMArt], size: str) -> Optional[str]:
    for art in arts:
        if (
            isinstance(art, XMImage)
            and art.size is not None
            and art.size == size
        ):
            return art
    return None


def get_art_thumb_url(arts: List[XMArt]) -> Optional[str]:
    thumb: Optional[str] = None

    for art in arts:
        if art.height > 100 and art.height < 200 and art.height == art.width:
            # logo on dark is what we really want
            if art.name == "show logo on dark":
                thumb = art.url
                break
            # but it is not always there, so fallback image
            elif art.name == "image":
                thumb = art.url

    return thumb
