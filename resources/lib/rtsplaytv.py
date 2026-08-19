# Copyright (C) 2018 Alexander Seiler
#
#
# This file is part of plugin.video.rtsplaytv.
#
# plugin.video.rtsplaytv is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# plugin.video.rtsplaytv is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with plugin.video.rtsplaytv.
# If not, see <http://www.gnu.org/licenses/>.

import sys
import traceback
import re
import urllib.request

from urllib.parse import unquote_plus
from urllib.parse import parse_qsl

import xbmc
import xbmcgui
import xbmcaddon
import xbmcplugin
import srgssr

ADDON_ID = "plugin.video.rtsplaytv"
REAL_SETTINGS = xbmcaddon.Addon(id=ADDON_ID)
ADDON_NAME = REAL_SETTINGS.getAddonInfo("name")
ADDON_VERSION = REAL_SETTINGS.getAddonInfo("version")
DEBUG = REAL_SETTINGS.getSetting("Enable_Debugging") == "true"
CONTENT_TYPE = "videos"


class RTSPlayTV(srgssr.SRGSSR):
    def __init__(self):
        super(RTSPlayTV, self).__init__(int(sys.argv[1]), bu="rts", addon_id=ADDON_ID)

    def build_sport_menu(self):
        """Scrapes RTS Sport programmes, groups them by date headers, and renders them in Kodi."""
        url = "https://www.rts.ch/sport/programmes/"
        headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                html = response.read().decode('utf-8')
        except Exception as e:
            log(f"Failed to fetch RTS Sport page: {e}", xbmc.LOGERROR)
            return

        items = []
        for m in re.finditer(r'<h2 class=\"module-title epg-title\">([^<]+)</h2>', html):
            items.append((m.start(), 'header', m.group(1).strip()))

        matches = list(re.finditer(r'<div class=\"(grid-item epg-item [^\"]*)\"', html))
        for i, m in enumerate(matches):
            start_idx = m.end()
            end_idx = matches[i + 1].start() if i + 1 < len(matches) else len(html)
            block_class = m.group(1)
            block_content = html[start_idx:end_idx]
            items.append((m.start(), 'card', (block_class, block_content)))

        items.sort(key=lambda x: x[0])

        for item in items:
            if item[1] == 'header':
                header_text = item[2]
                list_item = xbmcgui.ListItem(label=f"--- {header_text} ---")
                list_item.setProperty("IsPlayable", "false")
                xbmcplugin.addDirectoryItem(self.handle, self.build_url(mode=80), list_item, isFolder=False)
            else:
                block_class, block_content = item[2]
                is_live = "live" in block_class
                time_m = re.search(r'<div class=\"time\">([^<]+)</div>', block_content)
                url_m = re.search(r'href=\"([^\"]+whatson:[^\"]+)\"', block_content)
                title_m = re.search(r'<p class=\"card-title\">([^<]+)</p>', block_content)
                bait_m = re.search(r'<p class=\"card-bait\">([^<]+)</p>', block_content)
                img_m = re.search(r'<img [^>]*src=\"([^\"]+)\"', block_content)

                if url_m and title_m:
                    time_str = time_m.group(1) if time_m else ""
                    sport_discipline = bait_m.group(1).strip() if bait_m else "Sport"
                    event_title = title_m.group(1).strip()
                    sub_page_url = url_m.group(1)

                    prefix = "[COLOR red][LIVE] [/COLOR]" if is_live else f"[{time_str}] "
                    display_name = f"{prefix}{sport_discipline}: {event_title}"

                    list_item = xbmcgui.ListItem(label=display_name)
                    list_item.setProperty("IsPlayable", "true")
                    if img_m:
                        img_url = img_m.group(1).replace("&amp;", "&")
                        list_item.setArt({"thumb": img_url})

                    plugin_url = self.build_url(mode=81, name=sub_page_url)
                    xbmcplugin.addDirectoryItem(self.handle, plugin_url, list_item, isFolder=False)

    def play_sport_stream(self, sub_page_url):
        """Resolves sub_page_url to a SwissTXT/RTS video URN and plays it."""
        headers = {'User-Agent': 'Mozilla/5.0'}
        try:
            req = urllib.request.Request(sub_page_url, headers=headers)
            with urllib.request.urlopen(req) as response:
                sub_html = response.read().decode('utf-8')
        except Exception as e:
            log(f"Failed to fetch RTS Sport sub-page: {e}", xbmc.LOGERROR)
            xbmcgui.Dialog().notification("RTS Sport", "Impossible de charger la page du direct.", xbmcgui.NOTIFICATION_ERROR)
            return

        urn_match = re.search(r'urn:(swisstxt|rts):video:[a-zA-Z0-9:-]+', sub_html)
        if urn_match:
            video_urn = urn_match.group(0)
            log(f"Found video URN: {video_urn}")
            self.player.play_video(video_urn)
        else:
            log("No video URN found on page", xbmc.LOGERROR)
            xbmcgui.Dialog().notification("RTS Sport", "Aucun flux vidéo disponible.", xbmcgui.NOTIFICATION_ERROR)

    def build_livetv_menu(self):
        """Fetches the 24/7 TV program guide and renders live channels with current/next show info."""
        import json
        import datetime
        url = "https://www.rts.ch/play/v3/api/rts/production/tv-program-guide"
        headers = {'User-Agent': 'Mozilla/5.0'}
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except Exception as e:
            log(f"Failed to fetch live TV program guide: {e}", xbmc.LOGERROR)
            return

        now = datetime.datetime.now(datetime.timezone.utc)
        for item in payload.get("data", []):
            channel = item.get("channel", {})
            title = channel.get("title")
            livestream = channel.get("livestream", {})
            urn = livestream.get("livestreamUrn")
            img_url = channel.get("imageUrl") or livestream.get("imageUrl")

            if title and urn:
                current_show = ""
                next_show = ""

                for prog in item.get("programList", []):
                    try:
                        start = datetime.datetime.fromisoformat(prog["startTime"].replace('Z', '+00:00'))
                        end = datetime.datetime.fromisoformat(prog["endTime"].replace('Z', '+00:00'))
                        if start <= now <= end:
                            current_show = prog["title"]
                            break
                        elif start > now:
                            if not next_show:
                                formatted_start = start.astimezone().strftime("%H:%M")
                                next_show = f"À suivre : {prog['title']} ({formatted_start})"
                    except Exception:
                        pass

                status = current_show if current_show else next_show
                display_name = f"{title} - {status}" if status else title

                list_item = xbmcgui.ListItem(label=display_name)
                list_item.setProperty("IsPlayable", "true")
                if img_url:
                    list_item.setArt({"thumb": img_url})

                plugin_url = self.build_url(mode=50, name=urn)
                xbmcplugin.addDirectoryItem(self.handle, plugin_url, list_item, isFolder=False)


def log(msg, level=xbmc.LOGDEBUG):
    """
    Logs a message using Kodi's logging interface.

    Keyword arguments:
    msg   -- the message to log
    level -- the logging level
    """
    if DEBUG:
        if level == xbmc.LOGERROR:
            msg += " ," + traceback.format_exc()
    xbmc.log(ADDON_ID + "-" + ADDON_VERSION + "-" + msg, level)


def get_params():
    return dict(parse_qsl(sys.argv[2][1:]))


def run():
    """
    Run the plugin.
    """
    params = get_params()
    try:
        url = unquote_plus(params["url"])
    except Exception:
        url = None
    try:
        name = unquote_plus(params["name"])
    except Exception:
        name = None
    try:
        mode = int(params["mode"])
    except Exception:
        mode = None
    try:
        page_hash = unquote_plus(params["page_hash"])
    except Exception:
        page_hash = None
    try:
        page = unquote_plus(params["page"])
    except Exception:
        page = None

    log("Mode: " + str(mode))
    log("URL : " + str(url))
    log("Name: " + str(name))
    log("Page Hash: " + str(page_hash))
    log("Page: " + str(page))

    if mode is None:
        identifiers = [
            "All_Shows",
            "Favourite_Shows",
            "Newest_Favourite_Shows",
            "Homepage",
            "Topics",
            "Shows_By_Date",
            "Search",
            "RTS_YouTube",
        ]
        rts = RTSPlayTV()
        rts.menu_builder.build_main_menu(identifiers)

        # Append RTS Sport to the main menu
        list_item = xbmcgui.ListItem(label="RTS Sport")
        list_item.setArt({"icon": rts.icon})
        sport_url = rts.build_url(mode=80)
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), sport_url, list_item, isFolder=True)

        # Append Direct TV to the main menu
        tv_list_item = xbmcgui.ListItem(label="Direct TV")
        tv_list_item.setArt({"icon": rts.icon})
        tv_url = rts.build_url(mode=90)
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), tv_url, tv_list_item, isFolder=True)
    elif mode == 10:
        RTSPlayTV().menu_builder.build_all_shows_menu()
    elif mode == 11:
        RTSPlayTV().menu_builder.build_favourite_shows_menu()
    elif mode == 12:
        RTSPlayTV().menu_builder.build_newest_favourite_menu(page=page)
    elif mode == 13:
        RTSPlayTV().menu_builder.build_topics_menu()
    elif mode == 17:
        RTSPlayTV().menu_builder.build_dates_overview_menu()
    elif mode == 19:
        RTSPlayTV().manage_favourite_shows()
    elif mode == 21:
        RTSPlayTV().menu_builder.build_episode_menu(name)
    elif mode == 24:
        RTSPlayTV().menu_builder.build_date_menu(name)
    elif mode == 60:
        RTSPlayTV().menu_builder.build_specific_date_menu(name)
    elif mode == 25:
        RTSPlayTV().menu_builder.pick_date()
    elif mode == 27:
        RTSPlayTV().menu_builder.build_search_menu()
    elif mode == 28:
        RTSPlayTV().menu_builder.build_search_media_menu(
            mode=mode, name=name, page=page, page_hash=page_hash
        )
    elif mode == 70:
        RTSPlayTV().menu_builder.build_recent_search_menu()
    elif mode == 30:
        RTSPlayTV().youtube_builder.build_youtube_channel_overview_menu(33)
    elif mode == 33:
        RTSPlayTV().youtube_builder.build_youtube_channel_menu(
            name, mode, page=page, page_token=page_hash
        )
    elif mode == 50:
        RTSPlayTV().player.play_video(name)
    elif mode == 100:
        RTSPlayTV().menu_builder.build_menu_by_urn(name)
    elif mode == 200:
        RTSPlayTV().menu_builder.build_homepage_menu()
    elif mode == 80:
        RTSPlayTV().build_sport_menu()
    elif mode == 81:
        RTSPlayTV().play_sport_stream(name)
    elif mode == 90:
        RTSPlayTV().build_livetv_menu()
    elif mode == 1000:
        RTSPlayTV().menu_builder.build_menu_apiv3(name, mode, page, page_hash)

    xbmcplugin.setContent(int(sys.argv[1]), CONTENT_TYPE)
    xbmcplugin.addSortMethod(int(sys.argv[1]), xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.addSortMethod(int(sys.argv[1]), xbmcplugin.SORT_METHOD_NONE)
    xbmcplugin.addSortMethod(int(sys.argv[1]), xbmcplugin.SORT_METHOD_LABEL)
    xbmcplugin.addSortMethod(int(sys.argv[1]), xbmcplugin.SORT_METHOD_TITLE)
    xbmcplugin.endOfDirectory(int(sys.argv[1]), cacheToDisc=True)
