from datetime import datetime, timezone

from typing import Tuple, List, Optional, Union
from discord import Embed, Message
from discord.ext.commands import errors
from discord_slash import SlashContext
from humanize import naturaltime

from sxm.models import (
    XMSong,
    XMImage,
    XMChannel,
    XMCut,
    XMArt,
    XMEpisodeMarker,
)
from sxm_player.models import Episode, PlayerState, Song

__all__ = ["send_message"]


def get_cog(ctx: SlashContext):
    return ctx.bot.cogs[ctx.name.title()]


async def send_message(
    ctx: SlashContext,
    message: Optional[str] = None,
    embed: Optional[Embed] = None,
) -> Message:
    if message is None and embed is None:
        raise errors.CommandError("A message or a embed must be provided")

    return await ctx.send(message, embed=embed)


def generate_embed_from_cut(
    xm_channel: XMChannel,
    cut: Optional[XMCut],
    episode: Optional[XMEpisodeMarker] = None,
    footer: Optional[XMEpisodeMarker] = None,
) -> Embed:
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

    if footer is not None:
        embed.set_footer(text=footer)

    return embed


def generate_embed_from_archived(
    item: Union[Song, Episode], footer: Optional[XMEpisodeMarker] = None
) -> Optional[Embed]:
    if isinstance(item, Song):
        return generate_embed_from_song(item, footer=footer)
    return None


def generate_embed_from_song(
    song: Song, footer: Optional[XMEpisodeMarker] = None
) -> Embed:
    embed = Embed(title=song.title, author=song.artist)

    if song.image_url is not None:
        embed.set_thumbnail(url=song.image_url)
    if song.album is not None:
        embed.add_field(name="Album", value=song.album)

    embed.add_field(
        name="Aired",
        value=naturaltime(song.air_time_smart, when=datetime.now(timezone.utc)),
        inline=True,
    )
    embed.add_field(name="SXM", value=song.channel, inline=True)

    if footer is not None:
        embed.set_footer(text=footer)

    return embed


def generate_now_playing_embed(state: PlayerState) -> Tuple[XMChannel, Embed]:
    xm_channel = state.get_channel(state.stream_channel)

    if state.live is not None:
        cut = state.live.get_latest_cut(now=state.radio_time)
        episode = state.live.get_latest_episode(now=state.radio_time)

    return xm_channel, generate_embed_from_cut(xm_channel, cut, episode)


def get_recent_songs(
    state: PlayerState, count: int
) -> Tuple[XMChannel, List[XMCut], Optional[XMCut]]:
    xm_channel = state.get_channel(state.stream_channel)

    if state.live is None or xm_channel is None:
        return (xm_channel, [], None)

    song_cuts: List[XMCut] = []
    now = state.radio_time
    latest_cut = state.live.get_latest_cut(now)

    for song_cut in reversed(state.live.song_cuts):
        if len(song_cuts) >= count:
            break

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

    return xm_channel, song_cuts, latest_cut


def get_art_url_by_size(arts: List[XMArt], size: str) -> Optional[str]:
    for art in arts:
        if isinstance(art, XMImage) and art.size is not None and art.size == size:
            return art.url
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
