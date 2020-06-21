# Gnu General Public License - see LICENSE.TXT
import xbmcaddon
import xbmc

import string
import random
import urllib.request, urllib.parse, urllib.error
import json
import base64
import time
import math
from datetime import datetime
import calendar
import re

from .downloadutils import DownloadUtils
from .simple_logging import SimpleLogging
from .clientinfo import ClientInformation

# hack to get datetime strptime loaded
throwaway = time.strptime('20110101', '%Y%m%d')

# define our global download utils
downloadUtils = DownloadUtils()
log = SimpleLogging(__name__)


def get_emby_url(base_url, params):
    params["format"] = "json"
    param_list = []
    for key in params:
        if params[key] is not None:
            value = params[key]
            if not isinstance(value, str):
                value = str(value)
            param_list.append(key + "=" + urllib.parse.quote_plus(str(value), safe="{}"))
    param_string = "&".join(param_list)
    return base_url + "?" + param_string


###########################################################################
class PlayUtils:

    @staticmethod
    def get_play_url(item_id, media_source, force_transcode, play_session_id):

        # check if strm file, path will contain contain strm contents
        if media_source.get('Container') == 'strm':
            log.debug("Detected STRM Container")
            playurl, listitem_props = PlayUtils().get_strm_details(media_source)
            if playurl is None:
                log.debug("Error, no strm content")
                return None, None, None
            else:
                return playurl, "0", listitem_props

        log.debug("get_play_url")

        addon_settings = xbmcaddon.Addon()
        playback_type = addon_settings.getSetting("playback_type")
        server = downloadUtils.get_server()
        use_https = False
        if addon_settings.getSetting('protocol') == "1":
            use_https = True
        log.debug("use_https: {0}", use_https)
        verify_cert = addon_settings.getSetting('verify_cert') == 'true'
        log.debug("verify_cert: {0}", verify_cert)

        log.debug("playback_type: {0}", playback_type)
        if force_transcode:
            log.debug("playback_type: FORCED_TRANSCODE")
        playurl = None
        log.debug("play_session_id: {0}", play_session_id)
        media_source_id = media_source.get("Id")
        log.debug("media_source_id: {0}", media_source_id)

        force_transcode_codecs = []
        if addon_settings.getSetting("force_transcode_h265") == "true":
            force_transcode_codecs.append("hevc")
            force_transcode_codecs.append("h265")
        if addon_settings.getSetting("force_transcode_mpeg2") == "true":
            force_transcode_codecs.append("mpeg2video")
        if addon_settings.getSetting("force_transcode_msmpeg4v3") == "true":
            force_transcode_codecs.append("msmpeg4v3")
        if addon_settings.getSetting("force_transcode_mpeg4") == "true":
            force_transcode_codecs.append("mpeg4")

        if len(force_transcode_codecs) > 0:
            codec_force_transcode = False
            codec_name = ""
            streams = media_source.get("MediaStreams", [])
            for stream in streams:
                if stream.get("Type", "") == "Video":
                    codec_name = stream.get("Codec", "").lower()
                    if codec_name in force_transcode_codecs:
                        codec_force_transcode = True
                        break
            if codec_force_transcode:
                log.debug("codec_force_transcode: {0}", codec_name)
                playback_type = "2"

        if force_transcode:
            playback_type = "2"

        # transcode
        if playback_type == "2":

            playback_bitrate = addon_settings.getSetting("playback_bitrate")
            log.debug("playback_bitrate: {0}", playback_bitrate)

            playback_max_width = addon_settings.getSetting("playback_max_width")
            playback_video_force_8 = addon_settings.getSetting("playback_video_force_8") == "true"

            audio_codec = addon_settings.getSetting("audio_codec")
            audio_playback_bitrate = addon_settings.getSetting("audio_playback_bitrate")
            audio_max_channels = addon_settings.getSetting("audio_max_channels")

            audio_bitrate = int(audio_playback_bitrate) * 1000
            bitrate = int(playback_bitrate) * 1000

            client_info = ClientInformation()
            device_id = client_info.get_device_id()
            user_token = downloadUtils.authenticate()

            transcode_params = []
            transcode_params.append("MediaSourceId=%s" % media_source_id)
            transcode_params.append("DeviceId=%s" % device_id)
            transcode_params.append("PlaySessionId=%s" % play_session_id)
            transcode_params.append("api_key=%s" % user_token)
            transcode_params.append("SegmentContainer=ts")

            transcode_params.append("VideoCodec=h264")
            transcode_params.append("VideoBitrate=%s" % bitrate)
            transcode_params.append("MaxWidth=%s" % playback_max_width)
            if playback_video_force_8:
                transcode_params.append("MaxVideoBitDepth=8")

            transcode_params.append("AudioCodec=%s" % audio_codec)
            transcode_params.append("TranscodingMaxAudioChannels=%s" % audio_max_channels)
            transcode_params.append("AudioBitrate=%s" % audio_bitrate)

            playurl = "%s/emby/Videos/%s/master.m3u8?" % (server, item_id)
            playurl += "&".join(transcode_params)
            if use_https and not verify_cert:
                playurl += "|verifypeer=false"

        # do direct path playback
        elif playback_type == "0":
            playurl = media_source.get("Path")
            playurl = playurl.replace("\\", "/")
            playurl = playurl.strip()

            # handle DVD structure
            if media_source.get("VideoType") == "Dvd":
                playurl = playurl + "/VIDEO_TS/VIDEO_TS.IFO"
            elif media_source.get("VideoType") == "BluRay":
                playurl = playurl + "/BDMV/index.bdmv"

            if playurl.startswith("//"):
                smb_username = addon_settings.getSetting('smbusername')
                smb_password = addon_settings.getSetting('smbpassword')
                if not smb_username:
                    playurl = "smb://" + playurl[2:]
                else:
                    playurl = "smb://" + smb_username + ':' + smb_password + '@' + playurl[2:]

        # do direct http streaming playback
        elif playback_type == "1":
            playurl = ("%s/emby/Videos/%s/stream" +
                       "?static=true" +
                       "&PlaySessionId=%s" +
                       "&MediaSourceId=%s")
            playurl = playurl % (server, item_id, play_session_id, media_source_id)
            user_token = downloadUtils.authenticate()
            playurl += "&api_key=" + user_token

            if use_https and not verify_cert:
                playurl += "|verifypeer=false"

        log.debug("Playback URL: {0}", playurl)
        return playurl, playback_type, []

    @staticmethod
    def get_strm_details(media_source):
        playurl = None
        listitem_props = []

        contents = media_source.get('Path').encode('utf-8')  # contains contents of strm file with linebreaks

        line_break = '\r'
        if '\r\n' in contents:
            line_break = '\r\n'
        elif '\n' in contents:
            line_break = '\n'

        lines = contents.split(line_break)
        for line in lines:
            line = line.strip()
            log.debug("STRM Line: {0}", line)
            if line.startswith('#KODIPROP:'):
                match = re.search('#KODIPROP:(?P<item_property>[^=]+?)=(?P<property_value>.+)', line)
                if match:
                    item_property = match.group('item_property')
                    property_value = match.group('property_value')
                    log.debug("STRM property found: {0} value: {1}", item_property, property_value)
                    listitem_props.append((item_property, property_value))
                else:
                    log.debug("STRM #KODIPROP incorrect format")
            elif line.startswith('#'):
                #  unrecognized, treat as comment
                log.debug("STRM unrecognized line identifier, ignored")
            elif line != '':
                playurl = line
                log.debug("STRM playback url found")

        log.debug("Playback URL: {0} ListItem Properties: {1}", playurl, listitem_props)
        return playurl, listitem_props


def get_checksum(item):
    userdata = item['UserData']
    checksum = "%s_%s_%s_%s_%s_%s_%s" % (
        item['Etag'],
        userdata['Played'],
        userdata['IsFavorite'],
        userdata.get('Likes', "-"),
        userdata['PlaybackPositionTicks'],
        userdata.get('UnplayedItemCount', "-"),
        userdata.get("PlayedPercentage", "-")
    )

    return checksum


def get_art(item, server):
    art = {
        'thumb': '',
        'fanart': '',
        'poster': '',
        'banner': '',
        'clearlogo': '',
        'clearart': '',
        'discart': '',
        'landscape': '',
        'tvshow.fanart': '',
        'tvshow.poster': '',
        'tvshow.clearart': '',
        'tvshow.clearlogo': '',
        'tvshow.banner': '',
        'tvshow.landscape': ''
    }

    image_tags = item["ImageTags"]
    if image_tags is not None and image_tags["Primary"] is not None:
        # image_tag = image_tags["Primary"]
        art['thumb'] = downloadUtils.get_artwork(item, "Primary", server=server)

    item_type = item["Type"]

    if item_type == "Genre":
        art['poster'] = downloadUtils.get_artwork(item, "Primary", server=server)
    elif item_type == "Episode":
        art['tvshow.poster'] = downloadUtils.get_artwork(item, "Primary", parent=True, server=server)
        # art['poster'] = downloadUtils.getArtwork(item, "Primary", parent=True, server=server)
        art['tvshow.clearart'] = downloadUtils.get_artwork(item, "Art", parent=True, server=server)
        art['clearart'] = downloadUtils.get_artwork(item, "Art", parent=True, server=server)
        art['tvshow.clearlogo'] = downloadUtils.get_artwork(item, "Logo", parent=True, server=server)
        art['clearlogo'] = downloadUtils.get_artwork(item, "Logo", parent=True, server=server)
        art['tvshow.banner'] = downloadUtils.get_artwork(item, "Banner", parent=True, server=server)
        art['banner'] = downloadUtils.get_artwork(item, "Banner", parent=True, server=server)
        art['tvshow.landscape'] = downloadUtils.get_artwork(item, "Thumb", parent=True, server=server)
        art['landscape'] = downloadUtils.get_artwork(item, "Thumb", parent=True, server=server)
        art['tvshow.fanart'] = downloadUtils.get_artwork(item, "Backdrop", parent=True, server=server)
        art['fanart'] = downloadUtils.get_artwork(item, "Backdrop", parent=True, server=server)
    elif item_type == "Season":
        art['tvshow.poster'] = downloadUtils.get_artwork(item, "Primary", parent=True, server=server)
        art['season.poster'] = downloadUtils.get_artwork(item, "Primary", parent=False, server=server)
        art['poster'] = downloadUtils.get_artwork(item, "Primary", parent=False, server=server)
        art['tvshow.clearart'] = downloadUtils.get_artwork(item, "Art", parent=True, server=server)
        art['clearart'] = downloadUtils.get_artwork(item, "Art", parent=True, server=server)
        art['tvshow.clearlogo'] = downloadUtils.get_artwork(item, "Logo", parent=True, server=server)
        art['clearlogo'] = downloadUtils.get_artwork(item, "Logo", parent=True, server=server)
        art['tvshow.banner'] = downloadUtils.get_artwork(item, "Banner", parent=True, server=server)
        art['season.banner'] = downloadUtils.get_artwork(item, "Banner", parent=False, server=server)
        art['banner'] = downloadUtils.get_artwork(item, "Banner", parent=False, server=server)
        art['tvshow.landscape'] = downloadUtils.get_artwork(item, "Thumb", parent=True, server=server)
        art['season.landscape'] = downloadUtils.get_artwork(item, "Thumb", parent=False, server=server)
        art['landscape'] = downloadUtils.get_artwork(item, "Thumb", parent=False, server=server)
        art['tvshow.fanart'] = downloadUtils.get_artwork(item, "Backdrop", parent=True, server=server)
        art['fanart'] = downloadUtils.get_artwork(item, "Backdrop", parent=True, server=server)
    elif item_type == "Series":
        art['tvshow.poster'] = downloadUtils.get_artwork(item, "Primary", parent=False, server=server)
        art['poster'] = downloadUtils.get_artwork(item, "Primary", parent=False, server=server)
        art['tvshow.clearart'] = downloadUtils.get_artwork(item, "Art", parent=False, server=server)
        art['clearart'] = downloadUtils.get_artwork(item, "Art", parent=False, server=server)
        art['tvshow.clearlogo'] = downloadUtils.get_artwork(item, "Logo", parent=False, server=server)
        art['clearlogo'] = downloadUtils.get_artwork(item, "Logo", parent=False, server=server)
        art['tvshow.banner'] = downloadUtils.get_artwork(item, "Banner", parent=False, server=server)
        art['banner'] = downloadUtils.get_artwork(item, "Banner", parent=False, server=server)
        art['tvshow.landscape'] = downloadUtils.get_artwork(item, "Thumb", parent=False, server=server)
        art['landscape'] = downloadUtils.get_artwork(item, "Thumb", parent=False, server=server)
        art['tvshow.fanart'] = downloadUtils.get_artwork(item, "Backdrop", parent=False, server=server)
        art['fanart'] = downloadUtils.get_artwork(item, "Backdrop", parent=False, server=server)
    elif item_type == "Movie" or item_type == "BoxSet":
        art['poster'] = downloadUtils.get_artwork(item, "Primary", server=server)
        art['landscape'] = downloadUtils.get_artwork(item, "Thumb", server=server)
        art['banner'] = downloadUtils.get_artwork(item, "Banner", server=server)
        art['clearlogo'] = downloadUtils.get_artwork(item, "Logo", server=server)
        art['clearart'] = downloadUtils.get_artwork(item, "Art", server=server)
        art['discart'] = downloadUtils.get_artwork(item, "Disc", server=server)

    art['fanart'] = downloadUtils.get_artwork(item, "Backdrop", server=server)
    if not art['fanart']:
        art['fanart'] = downloadUtils.get_artwork(item, "Backdrop", parent=True, server=server)

    return art


def id_generator(size=6, chars=string.ascii_uppercase + string.digits):
    return ''.join(random.choice(chars) for _ in range(size))


def double_urlencode(text):
    text = single_urlencode(text)
    text = single_urlencode(text)
    return text


def single_urlencode(text):
    text = urllib.parse.urlencode({"1": text})
    text = text[2:]
    return text


def send_event_notification(method, data):
    message_data = json.dumps(data)
    source_id = "embycon"
    base64_data = base64.b64encode(message_data.encode("utf-8"))
    base64_data = base64_data.decode("utf-8")
    escaped_data = '\\"[\\"{0}\\"]\\"'.format(base64_data)
    command = 'NotifyAll({0}.SIGNAL,{1},{2})'.format(source_id, method, escaped_data)
    log.debug("Sending notification event data: {0}", command)
    xbmc.executebuiltin(command)


def datetime_from_string(time_string):

    if time_string[-1:] == "Z":
        time_string = re.sub("[0-9]{1}Z", " UTC", time_string)
    elif time_string[-6:] == "+00:00":
        time_string = re.sub("[0-9]{1}\+00:00", " UTC", time_string)
    log.debug("New Time String : {0}", time_string)

    start_time = time.strptime(time_string, "%Y-%m-%dT%H:%M:%S.%f %Z")
    dt = datetime(*(start_time[0:6]))
    timestamp = calendar.timegm(dt.timetuple())
    local_dt = datetime.fromtimestamp(timestamp)
    local_dt.replace(microsecond=dt.microsecond)
    return local_dt


def convert_size(size_bytes):
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, size_name[i])
