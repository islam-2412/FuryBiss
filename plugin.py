# -*- coding: utf-8 -*-

#################################################

# Created by islam salama

##################################################

import os
import time
import re
import sys
import ssl
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass
import calendar
import binascii
import subprocess
from array import array
import json
from twisted.web.client import getPage
from twisted.internet import threads
from Tools.Notifications import AddNotification, AddPopup
from Screens.MessageBox import MessageBox
import NavigationInstance
from Plugins.Plugin import PluginDescriptor

# --- Adjustments here (added ConfigSubsection and ActionMap) ---
from Components.config import config, getConfigListEntry, ConfigNothing, NoSave, ConfigText, ConfigSubsection
from Components.ActionMap import ActionMap 

try:
    from Components.config import configfile
except Exception:
    configfile = None

# --- Customer proxy settings (new) ---
if not hasattr(config.plugins, "furybiss"):
    config.plugins.furybiss = ConfigSubsection()
config.plugins.furybiss.proxy_url = ConfigText(default="", visible_width=50, fixed_size=False)

PLUGIN_PATH = os.path.dirname(__file__)
PROXY_FILE = os.path.join(PLUGIN_PATH, "proxy.txt")
# ---------------------------------------------------

from Tools.Downloader import downloadWithProgress
from Components.Sources.Progress import Progress
from Components.Sources.StaticText import StaticText
from Screens.Standby import TryQuitMainloop
try:
    from Screens.Console import Console
except Exception:
    Console = None

def _ver_tuple(v):
    try:
        return tuple(int(x) for x in re.findall(r"\d+", str(v)))
    except Exception:
        return (0,)


def _plugin_dir():
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return "/usr/lib/enigma2/python/Plugins/Extensions/FuryBiss"


def _plugin_init_path():
    return os.path.join(_plugin_dir(), "__init__.py")


def _plugin_version_path():
    return os.path.join(_plugin_dir(), "version.txt")


def _normalize_version_text(value):
    try:
        cleaned = ".".join(re.findall(r"\d+", _to_text(value)))
        return cleaned.strip(".")
    except Exception:
        return ""


def _read_plugin_version_from_path(path):
    try:
        if not os.path.exists(path):
            return ""
        with open(path, "r") as f:
            data = f.read()
        match = re.search(r"PLUGIN_VERSION\s*=\s*['\"]([^'\"]+)['\"]", data)
        if match:
            return _normalize_version_text(match.group(1))
    except Exception:
        pass
    return ""


def _read_plugin_version_file(path=None):
    path = path or _plugin_version_path()
    try:
        if not os.path.exists(path):
            return ""
        with open(path, "r") as handle:
            return _normalize_version_text(handle.read())
    except Exception:
        return ""


def _read_installed_plugin_version():
    version = _read_plugin_version_file()
    if version:
        return version
    version = _read_plugin_version_from_path(_plugin_init_path())
    return _normalize_version_text(version or PLUGIN_VERSION)


REMOTE_VERSION_URL = "https://raw.githubusercontent.com/islam-2412/FuryBiss/main/fury/version.txt"
REMOTE_INSTALLER_URL = "https://raw.githubusercontent.com/islam-2412/FuryBiss/main/fury/installer.sh"


def _run_shell_capture(cmd):
    try:
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output = process.communicate()[0]
        code = process.returncode
        if PY3 and isinstance(output, bytes):
            output = output.decode('utf-8', 'ignore')
        elif not PY3 and not isinstance(output, str):
            try:
                output = output.encode('utf-8')
            except Exception:
                output = str(output)
        return code, (output or "")
    except Exception as error:
        return 999, _to_text(error)


def _read_remote_version(url=None):
    target_url = _to_text(url or REMOTE_VERSION_URL).strip()
    if not target_url:
        return ""

    try:
        request = urllib2.Request(target_url, headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib2.urlopen(request, timeout=8).read()
        if PY3:
            response = response.decode('utf-8', 'ignore')
        else:
            response = _to_text(response)
        version = _normalize_version_text(response)
        if version:
            return version
    except Exception:
        pass

    shell_commands = [
        "curl -k -sL '%s'" % target_url.replace("'", "'\''"),
        "wget -q --no-check-certificate -O - '%s'" % target_url.replace("'", "'\''"),
    ]
    for command in shell_commands:
        code, output = _run_shell_capture(command)
        if code == 0:
            version = _normalize_version_text(output)
            if version:
                return version
    return ""


def _build_installer_command():
    quoted_url = _to_text(REMOTE_INSTALLER_URL).strip().replace("'", "'\''")
    return "wget -q --no-check-certificate -O - '%s' | /bin/sh" % quoted_url


def _cleanup_plugin_bytecode():
    try:
        plugin_dir = _plugin_dir()
        for root, dirs, files in os.walk(plugin_dir):
            for name in files:
                if name.endswith(('.pyc', '.pyo')):
                    try:
                        os.remove(os.path.join(root, name))
                    except Exception:
                        pass
            for name in dirs:
                if name == '__pycache__':
                    try:
                        pycache_dir = os.path.join(root, name)
                        for cache_name in os.listdir(pycache_dir):
                            cache_path = os.path.join(pycache_dir, cache_name)
                            if os.path.isfile(cache_path):
                                try:
                                    os.remove(cache_path)
                                except Exception:
                                    pass
                        try:
                            os.rmdir(pycache_dir)
                        except Exception:
                            pass
                    except Exception:
                        pass
    except Exception:
        pass
        
def plugin_get_receiver_model():
    """Returns the full receiver/box model name from the system."""
    try:
        import boxbranding
        parts = []
        try:
            brand = _to_text(boxbranding.getBrandName()).strip()
            if brand:
                parts.append(brand)
        except Exception:
            pass
        try:
            machine = _to_text(boxbranding.getMachineName()).strip()
            if machine:
                parts.append(machine)
        except Exception:
            pass
        try:
            boxtype = _to_text(boxbranding.getBoxType()).strip()
            if boxtype:
                parts.append("(%s)" % boxtype)
        except Exception:
            pass
        if parts:
            return " ".join(parts)
    except Exception:
        pass
    try:
        from Tools.HardwareInfo import HardwareInfo
        model = _to_text(HardwareInfo().device_name).strip()
        if model:
            return model
    except Exception:
        pass
    for path in ('/proc/stb/info/model', '/proc/stb/info/boxtype'):
        try:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    model = f.read().strip()
                if model:
                    return _to_text(model)
        except Exception:
            pass
    return "Unknown"


from Screens.Screen import Screen
from Components.ConfigList import ConfigListScreen
from Components.ActionMap import ActionMap
from Components.Button import Button
from Components.Label import Label
from Components.MenuList import MenuList
from Components.MultiContent import MultiContentEntryText
from enigma import (
    eTimer,
    eConsoleAppContainer,
    eListboxPythonMultiContent,
    gFont,
    RT_HALIGN_LEFT,
    RT_VALIGN_CENTER,
)

from . import (
    BASE_CONFIG_DIR,
    DEFAULT_KEY_FILE,
    PLUGIN_VERSION,
    ensure_config,
    get_storage_path,
    get_storage_write_paths,
    normalize_stored_values,
    set_storage_path,
)
from .web_server import build_biss_lines

ensure_config()

# =================================================================
# Compatibility with Python 2 and Python 3
# =================================================================
PY3 = sys.version_info[0] >= 3
if PY3:
    text_type = str
    import urllib.request as urllib2
else:
    text_type = unicode
    import urllib2

def _to_text(value):
    if value is None: return ""
    if isinstance(value, text_type): return value
    try: return value.decode("utf-8")
    except: 
        try: return value.decode("latin-1", "ignore")
        except: pass
    try: return text_type(value)
    except: return str(value)

AR_SATELLITE_LABEL = u"\u0627\u0644\u0642\u0645\u0631"
AR_CHANNEL_LABEL = u"\u0627\u0644\u0642\u0646\u0627\u0629"
AR_FEED_NAME_LABEL = u"\u0627\u0633\u0645 \u0627\u0644\u0641\u064A\u062F"
AR_CHANNEL_NAME_LABEL = u"\u0627\u0633\u0645 \u0627\u0644\u0642\u0646\u0627\u0629"

# =================================================================
# My-Country detection
# Primary  : ip-api.com via getPage (Twisted) — same engine as Telegram
# Fallback : /etc/timezone file — instant, no network needed
# =================================================================

_MY_COUNTRY_MAP = {
    # --- Arab ---
    "EG": (u"Egypt",          7200),
    "SA": (u"Saudi Arabia",  10800),
    "AE": (u"UAE",           14400),
    "KW": (u"Kuwait",        10800),
    "QA": (u"Qatar",         10800),
    "BH": (u"Bahrain",       10800),
    "OM": (u"Oman",          14400),
    "JO": (u"Jordan",        10800),
    "IQ": (u"Iraq",          10800),
    "SY": (u"Syria",         10800),
    "LB": (u"Lebanon",        7200),
    "PS": (u"Palestine",      7200),
    "YE": (u"Yemen",         10800),
    "LY": (u"Libya",          7200),
    "TN": (u"Tunisia",        3600),
    "DZ": (u"Algeria",        3600),
    "MA": (u"Morocco",        3600),
    "SD": (u"Sudan",         10800),
    "SO": (u"Somalia",       10800),
    "MR": (u"Mauritania",        0),
    # --- Non-Arab Middle East ---
    "IR": (u"Iran",          12600),
    "TR": (u"Turkey",        10800),
    # --- Europe ---
    "DE": (u"Germany",    3600),
    "GB": (u"UK",         0),
    "FR": (u"France",     3600),
    "NL": (u"Netherlands",3600),
    "SE": (u"Sweden",     3600),
    "NO": (u"Norway",     3600),
    "IT": (u"Italy",      3600),
    "ES": (u"Spain",      3600),
    "GR": (u"Greece",     7200),
    "PL": (u"Poland",     3600),
    # --- Asia ---
    "PK": (u"Pakistan",   18000),
    "IN": (u"India",      19800),
    "CN": (u"China",      28800),
    "JP": (u"Japan",      32400),
    # --- Americas ---
    "US": (u"USA",       -18000),
    "BR": (u"Brazil",    -10800),
}

# TZ string -> (label, offset)  — for offline fallback
_MY_TZ_FALLBACK = {
    "Africa/Cairo":     (u"Egypt",          7200),
    "Asia/Riyadh":      (u"Saudi Arabia",  10800),
    "Asia/Dubai":       (u"UAE",           14400),
    "Asia/Kuwait":      (u"Kuwait",        10800),
    "Asia/Qatar":       (u"Qatar",         10800),
    "Asia/Bahrain":     (u"Bahrain",       10800),
    "Asia/Muscat":      (u"Oman",          14400),
    "Asia/Amman":       (u"Jordan",        10800),
    "Asia/Baghdad":     (u"Iraq",          10800),
    "Asia/Damascus":    (u"Syria",         10800),
    "Asia/Beirut":      (u"Lebanon",        7200),
    "Asia/Gaza":        (u"Palestine",      7200),
    "Asia/Aden":        (u"Yemen",         10800),
    "Africa/Tripoli":   (u"Libya",          7200),
    "Africa/Tunis":     (u"Tunisia",        3600),
    "Africa/Algiers":   (u"Algeria",        3600),
    "Africa/Casablanca":(u"Morocco",        3600),
    "Africa/Khartoum":  (u"Sudan",         10800),
    "Asia/Tehran":      (u"Iran",          12600),
    "Europe/Istanbul":  (u"Turkey",        10800),
    "Europe/London":    (u"UK",                0),
    "Europe/Berlin":    (u"Germany",        3600),
    "Europe/Paris":     (u"France",         3600),
    "Asia/Karachi":     (u"Pakistan",      18000),
    "Asia/Kolkata":     (u"India",         19800),
    "America/New_York": (u"USA",          -18000),
}

_my_country_cache = {
    'label':   None,   # None = not resolved yet
    'offset':  0,
    'fetched': False,
    'cc':      '',     # ISO country code — used for live DST recalculation
}

# =================================================================
# Accurate UTC Time  (NTP + HTTP fallback)
# Order:
#   1. time.akamai.com  — HTTP, returns plain Unix timestamp, very fast
#   2. pool.ntp.org     — UDP NTP
#   3. time.cloudflare.com — UDP NTP
#   4. time.google.com  — UDP NTP
#   5. Device clock     — last resort
#
# plugin_get_utc_time() replaces bare time.time() wherever the result
# is used for day-boundary / window calculations so that a wrong
# receiver clock never causes feeds to disappear or appear on the
# wrong day.
# =================================================================

_NTP_EPOCH_DELTA   = 2208988800   # seconds 1900-01-01 → 1970-01-01
_NTP_CACHE_TTL     = 3600         # re-sync after 1 hour

_accurate_utc_cache = {
    'utc_time':   0,      # NTP UTC timestamp at the moment of fetch
    'fetched_at': 0.0,    # time.time() when we fetched it (monotonic ref)
    'source':     '',
    'ready':      False,
}
_ntp_sync_started = False


def _ntp_fetch_akamai_http():
    """HTTP request to time.akamai.com — returns plain Unix timestamp text."""
    for url in ('http://time.akamai.com/', 'https://time.akamai.com/'):
        try:
            req = urllib2.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            resp = urllib2.urlopen(req, timeout=3)
            raw = resp.read(64)
            if PY3 and isinstance(raw, bytes):
                raw = raw.decode('utf-8', 'ignore')
            else:
                raw = _to_text(raw)
            ts = int(float(raw.strip()))
            if ts > 1000000000:
                return ts, 'time.akamai.com'
        except Exception:
            continue
    return 0, ''


def _ntp_fetch_udp(server, timeout=3):
    """Classic UDP NTP request (RFC 5905).  Returns (unix_ts, server) or (0, '')."""
    import socket, struct
    try:
        pkt = b'\x1b' + b'\x00' * 47          # LI=0 VN=3 Mode=3 (client)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(pkt, (server, 123))
        data, _ = sock.recvfrom(1024)
        sock.close()
        if len(data) >= 48:
            integ = struct.unpack('!I', data[40:44])[0]
            ts = integ - _NTP_EPOCH_DELTA
            if ts > 1000000000:
                return ts, server
    except Exception:
        pass
    return 0, ''


def _ntp_sync_worker():
    """
    Background worker (runs in a thread).
    Tries sources in order and writes to _accurate_utc_cache.
    """
    global _accurate_utc_cache

    # 1. Akamai HTTP (fastest, most reliable)
    ts, src = _ntp_fetch_akamai_http()

    # 2. UDP NTP fallbacks
    if ts <= 0:
        for server in ('pool.ntp.org', 'time.cloudflare.com', 'time.google.com'):
            ts, src = _ntp_fetch_udp(server)
            if ts > 0:
                break

    # 3. Device clock — last resort (offset may be wrong but at least we have a date)
    if ts <= 0:
        ts  = int(time.time())
        src = 'device'

    _accurate_utc_cache = {
        'utc_time':   ts,
        'fetched_at': time.time(),
        'source':     src,
        'ready':      True,
    }


def plugin_start_ntp_sync():
    """
    Fire a one-shot background NTP sync.
    Safe to call multiple times — only one sync runs at a time.
    """
    global _ntp_sync_started
    if _ntp_sync_started:
        return
    _ntp_sync_started = True
    try:
        threads.deferToThread(_ntp_sync_worker)
    except Exception:
        try:
            import threading
            t = threading.Thread(target=_ntp_sync_worker)
            t.daemon = True
            t.start()
        except Exception:
            pass


def plugin_refresh_ntp_if_stale():
    """Re-sync NTP if the cached result is older than _NTP_CACHE_TTL seconds."""
    global _ntp_sync_started
    try:
        age = time.time() - float(_accurate_utc_cache.get('fetched_at', 0) or 0)
        if age >= _NTP_CACHE_TTL:
            _ntp_sync_started = False   # allow a new sync
            plugin_start_ntp_sync()
    except Exception:
        pass


def plugin_get_utc_time():
    """
    Returns an accurate UTC Unix timestamp.

    If the NTP cache is populated and fresh (< _NTP_CACHE_TTL):
        returns  cached_ntp_time + elapsed_since_fetch
    Otherwise:
        returns  time.time()  (receiver clock fallback)
    """
    plugin_refresh_ntp_if_stale()
    try:
        cache = _accurate_utc_cache
        if cache.get('ready') and cache.get('utc_time', 0) > 0:
            elapsed = time.time() - float(cache.get('fetched_at', 0) or 0)
            if 0.0 <= elapsed < _NTP_CACHE_TTL:
                return int(cache['utc_time'] + elapsed)
    except Exception:
        pass
    return int(time.time())


def plugin_get_ntp_status_text():
    """Short status string for display/debugging, e.g. 'NTP: time.akamai.com'."""
    try:
        if not _accurate_utc_cache.get('ready'):
            return u'NTP: syncing...'
        src = _to_text(_accurate_utc_cache.get('source', '') or '')
        age = int(time.time() - float(_accurate_utc_cache.get('fetched_at', 0) or 0))
        return u'NTP: %s (%ds ago)' % (src, age)
    except Exception:
        return u'NTP: unknown'


# =================================================================
# DST (Daylight Saving Time) Rules
# Used when ip-api.com is unavailable OR as a cross-check.
# Avoids relying on the receiver's tzdata which is often outdated
# (e.g. Egypt re-introduced DST in 2023 but many receivers still
#  report tm_isdst=0 for Africa/Cairo).
#
# Format per entry:
#   CC: (std_offset_sec, dst_offset_sec,
#        (start_month, start_weekday, start_nth, start_hour_local),
#        (end_month,   end_weekday,   end_nth,   end_hour_local))
#
#   weekday : 0=Mon 1=Tue 2=Wed 3=Thu 4=Fri 5=Sat 6=Sun
#   nth     : -1=last  1=first  2=second  3=third  4=fourth
# =================================================================
_DST_RULES = {
    # Egypt — UTC+2 (winter) / UTC+3 (summer) — re-introduced 2023
    # Last Friday of April 00:00 → Last Thursday of October 00:00
    'EG': (7200,  10800, (4,  4, -1, 0),  (10, 3, -1, 0)),
    # Lebanon — UTC+2 / UTC+3
    # Last Sunday March 03:00 → Last Sunday October 04:00
    'LB': (7200,  10800, (3,  6, -1, 3),  (10, 6, -1, 4)),
    # Palestine — UTC+2 / UTC+3
    # Last Saturday March 02:00 → Last Friday October 02:00
    'PS': (7200,  10800, (3,  5, -1, 2),  (10, 4, -1, 2)),
    # Syria — UTC+2 / UTC+3
    # Last Friday March 00:00 → Last Friday October 00:00
    'SY': (7200,  10800, (3,  4, -1, 0),  (10, 4, -1, 0)),
    # Iran — UTC+3:30 / UTC+4:30
    # 2nd Monday March → 3rd Thursday September (Gregorian approximation)
    'IR': (12600, 16200, (3,  0,  2, 0),  (9,  3,  3, 0)),
    # Europe CET — UTC+1 / UTC+2
    # Last Sunday March 02:00 → Last Sunday October 03:00
    'DE': (3600,  7200,  (3,  6, -1, 2),  (10, 6, -1, 3)),
    'FR': (3600,  7200,  (3,  6, -1, 2),  (10, 6, -1, 3)),
    'NL': (3600,  7200,  (3,  6, -1, 2),  (10, 6, -1, 3)),
    'IT': (3600,  7200,  (3,  6, -1, 2),  (10, 6, -1, 3)),
    'ES': (3600,  7200,  (3,  6, -1, 2),  (10, 6, -1, 3)),
    'PL': (3600,  7200,  (3,  6, -1, 2),  (10, 6, -1, 3)),
    'SE': (3600,  7200,  (3,  6, -1, 2),  (10, 6, -1, 3)),
    'NO': (3600,  7200,  (3,  6, -1, 2),  (10, 6, -1, 3)),
    # UK — UTC+0 / UTC+1
    # Last Sunday March 01:00 → Last Sunday October 02:00
    'GB': (0,     3600,  (3,  6, -1, 1),  (10, 6, -1, 2)),
    # Greece / Eastern Europe EET — UTC+2 / UTC+3
    # Last Sunday March 03:00 → Last Sunday October 04:00
    'GR': (7200,  10800, (3,  6, -1, 3),  (10, 6, -1, 4)),
}

# TZ-string → ISO country code (for the offline fallback path)
_MY_TZ_TO_CC = {
    'Africa/Cairo':     'EG',
    'Asia/Beirut':      'LB',
    'Asia/Gaza':        'PS',
    'Asia/Hebron':      'PS',
    'Asia/Damascus':    'SY',
    'Asia/Tehran':      'IR',
    'Europe/Berlin':    'DE',
    'Europe/Paris':     'FR',
    'Europe/Amsterdam': 'NL',
    'Europe/Rome':      'IT',
    'Europe/Madrid':    'ES',
    'Europe/Warsaw':    'PL',
    'Europe/Stockholm': 'SE',
    'Europe/Oslo':      'NO',
    'Europe/London':    'GB',
    'Europe/Athens':    'GR',
}


def _dst_find_weekday_in_month(year, month, weekday, nth):
    """
    Returns the day-of-month of the nth occurrence of weekday in (year, month).
    nth=-1 → last occurrence.  nth=1/2/3/4 → 1st/2nd/3rd/4th.
    weekday: 0=Mon … 6=Sun  (Python calendar convention).
    """
    import calendar as _cal
    days = [d for d in range(1, _cal.monthrange(year, month)[1] + 1)
            if _cal.weekday(year, month, d) == weekday]
    if not days:
        return 1
    if nth == -1:
        return days[-1]
    idx = max(0, min(nth - 1, len(days) - 1))
    return days[idx]


def _dst_transition_utc(year, month, weekday, nth, hour_local, offset_at_transition):
    """
    UTC Unix timestamp of a DST transition.
    offset_at_transition: offset IN EFFECT just before the switch
        (std_offset for DST-start, dst_offset for DST-end).
    """
    import calendar as _cal
    day = _dst_find_weekday_in_month(year, month, weekday, nth)
    local_ts = int(_cal.timegm((year, month, day, hour_local, 0, 0, 0, 0, 0)))
    return local_ts - offset_at_transition


def _compute_dst_aware_offset(cc, utc_ts):
    """
    Returns the correct UTC offset in seconds for country `cc` at UTC time `utc_ts`,
    fully accounting for DST.  Returns None if no rule exists for this country.

    This function is INDEPENDENT of the receiver's timezone database so it
    works correctly even on devices with outdated tzdata (common on older
    Enigma2 boxes that pre-date Egypt's 2023 DST re-introduction).
    """
    rule = _DST_RULES.get(cc)
    if rule is None:
        return None
    std_off, dst_off, (sm, swd, sn, sh), (em, ewd, en, eh) = rule
    try:
        year = time.gmtime(int(utc_ts)).tm_year
        # DST starts at sh:00 local *standard* time
        start_utc = _dst_transition_utc(year, sm, swd, sn, sh, std_off)
        # DST ends   at eh:00 local *DST* time
        end_utc   = _dst_transition_utc(year, em, ewd, en, eh, dst_off)
        ts = int(utc_ts)
        # Northern hemisphere: DST is active between start and end
        if start_utc <= ts < end_utc:
            return dst_off   # summer — DST active
        return std_off       # winter — DST inactive
    except Exception:
        return std_off


def _my_country_from_tz_file():
    """Read country from /etc/timezone — zero network, instant."""
    tz_str = ''
    try:
        with open('/etc/timezone', 'r') as f:
            tz_str = f.read().strip()
    except Exception:
        pass
    if not tz_str:
        try:
            link = os.readlink('/etc/localtime')
            parts = link.replace('\\', '/').split('/')
            for i, p in enumerate(parts):
                if p in ('zoneinfo', 'posix', 'right') and i + 1 < len(parts):
                    tz_str = '/'.join(parts[i + 1:])
                    break
            if not tz_str and len(parts) >= 2:
                tz_str = '/'.join(parts[-2:])
        except Exception:
            pass

    # Prefer our own DST-aware calculation over the device tzdata.
    # Receiver tzdata is often frozen and unaware of DST rule changes
    # (e.g. Egypt re-introduced DST in 2023 — many boxes still report tm_isdst=0).
    cc = _MY_TZ_TO_CC.get(tz_str, '')
    if cc:
        dst_offset = _compute_dst_aware_offset(cc, plugin_get_utc_time())
        if dst_offset is not None:
            label, _ = _MY_TZ_FALLBACK.get(tz_str, (u'', 0))
            return (label, dst_offset, cc)

    # Fallback: rely on device timezone database (may be outdated)
    try:
        is_dst_now = time.localtime().tm_isdst > 0
        sys_offset = -time.altzone if (is_dst_now and time.daylight) else -time.timezone
    except Exception:
        sys_offset = 0
    if tz_str and tz_str in _MY_TZ_FALLBACK:
        label, _ = _MY_TZ_FALLBACK[tz_str]
        return (label, sys_offset, cc)
    # last resort: no label, device-provided offset
    return (u'', sys_offset, cc)


def _my_country_geoip_cb(raw):
    """Twisted callback — called on main thread when ip-api responds."""
    global _my_country_cache
    try:
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8', 'ignore')
        data = json.loads(raw)
        cc     = _to_text(data.get('countryCode', '')).strip().upper()
        # offset from ip-api is live and DST-aware — use it directly
        offset = int(data.get('offset', 0) or 0)
        if cc and cc in _MY_COUNTRY_MAP:
            label, _map_offset = _MY_COUNTRY_MAP[cc]
            _my_country_cache['label']  = label
            _my_country_cache['offset'] = offset   # live DST-aware API offset
            _my_country_cache['cc']     = cc
        elif cc:
            _my_country_cache['label']  = cc
            _my_country_cache['offset'] = offset
            _my_country_cache['cc']     = cc
        # else: keep whatever the TZ fallback set
    except Exception:
        pass


def _my_country_geoip_err(failure):
    """Twisted errback — network failed, TZ fallback already set."""
    pass


def plugin_ensure_my_country():
    """
    Called once when FuryBissFeedsScreen opens.
    1) Immediately apply TZ-file fallback so something shows right away.
    2) Fire a getPage to ip-api.com (same Twisted engine as Telegram).
       When it returns it overwrites the label with the real country.
    """
    global _my_country_cache
    if _my_country_cache['fetched']:
        return
    _my_country_cache['fetched'] = True

    # Step 1 — instant offline fallback (DST-aware via our own rules)
    label, offset, cc = _my_country_from_tz_file()
    _my_country_cache['label']  = label
    _my_country_cache['offset'] = offset
    _my_country_cache['cc']     = cc

    # Step 2 — real GeoIP via getPage (Twisted, no blocking)
    try:
        d = getPage(
            b"http://ip-api.com/json/?fields=countryCode,offset",
            headers={b'User-Agent': b'Mozilla/5.0'},
            timeout=8,
        )
        d.addCallback(_my_country_geoip_cb)
        d.addErrback(_my_country_geoip_err)
    except Exception:
        pass


def plugin_get_my_country_clock_text():
    """
    Returns 'Egypt  14:32:07' — called every second by _updateClock.

    The UTC offset is recalculated on EVERY call using our DST rules
    (not from a cached value) so that:
      - The clock is correct even before ip-api.com responds.
      - The clock automatically adjusts at DST transitions mid-session.
      - A frozen receiver tzdata never causes a 1-hour error.
    """
    label   = _my_country_cache.get('label') or u''
    cc      = _my_country_cache.get('cc')    or ''
    utc_now = plugin_get_utc_time()

    # Prefer live DST-aware calculation if we know the country code
    if cc:
        dst_offset = _compute_dst_aware_offset(cc, utc_now)
        offset = dst_offset if dst_offset is not None else (_my_country_cache.get('offset') or 0)
    else:
        offset = _my_country_cache.get('offset') or 0

    try:
        t_str = time.strftime('%H:%M:%S', time.gmtime(utc_now + int(offset)))
        return (u"%s  %s" % (label, t_str)) if label else t_str
    except Exception:
        return time.strftime('%H:%M:%S', time.gmtime())

# ================= قائمة الأقمار المدمجة =================
# يُستخدم كـ Fallback لو Enigma2 أو satellites.xml مش لاقيين الاسم
SATELLITES_MAP = {
    # West
    "0.8W": "Thor 5/6/7",        "1.0W": "Intelsat 10-02",      "4.0W": "Amos 2/3/7",
    "5.0W": "Eutelsat 5 West B", "7.0W": "Nilesat 201 / Eutelsat 7 West A",
    "8.0W": "Eutelsat 8 West B", "11.0W": "Express AM44",        "15.0W": "Telstar 12 Vantage",
    "18.0W": "Intelsat 37e",     "22.0W": "SES-4",               "24.5W": "Intelsat 905",
    "27.5W": "Intelsat 907",     "30.0W": "Hispasat 30W-6",      "34.5W": "Intelsat 35e",
    "40.5W": "SES-6",            "43.0W": "Intelsat 11",         "47.5W": "SES-14",
    "50.0W": "Intelsat 1R",      "55.5W": "Intelsat 21",         "61.0W": "Amazonas 2/3",
    "65.0W": "Star One C1",      "70.0W": "Star One D1",         "75.0W": "ABS-3A",
    "89.0W": "Galaxy 28",        "95.0W": "Galaxy 3C",           "101.0W": "DirecTV 1R",
    "110.0W": "EchoStar 10/11",  "119.0W": "EchoStar 7",        "127.0W": "Galaxy 13",
    "133.0W": "Galaxy 15",       "146.0W": "ABS-6",              "150.0W": "EchoStar 12",
    # East
    "3.0E": "Eutelsat 3B",       "4.8E": "Astra 4A",            "7.0E": "Eutelsat 7A/7B/7C",
    "9.0E": "Eutelsat 9B",       "10.0E": "Eutelsat 10B",        "13.0E": "Hotbird",
    "16.0E": "Eutelsat 16A",     "19.2E": "Astra 1",            "21.6E": "Eutelsat 21B",
    "23.5E": "Astra 3B",         "25.5E": "Es'hail",            "26.0E": "Badr",
    "28.2E": "Astra 2",          "30.5E": "Arabsat 5A/6A",      "31.5E": "Astra 5B",
    "33.0E": "Eutelsat 33E",     "36.0E": "Eutelsat 36",        "39.0E": "Hellas Sat",
    "42.0E": "Turksat",          "45.0E": "AzerSpace",           "52.0E": "MonacoSat",
    "53.0E": "Express AM6",      "55.0E": "Yamal 402",           "57.0E": "NSS-12",
    "60.0E": "Intelsat 33e",     "62.0E": "Intelsat 39",        "64.2E": "Intelsat 906",
    "66.0E": "Intelsat 17",      "67.0W": "SES10",              "68.5E": "Intelsat 20",
    "70.5E": "Eutelsat 70B",     "72.0E": "GSAT-17",            "76.5E": "Apstar 7",
    "78.5E": "Thaicom",          "83.0E": "Insat",              "85.2E": "Intelsat 15",
    "88.0E": "ST-2",             "90.0E": "Yamal 401",          "91.5E": "Measat 3",
    "93.5E": "GSAT-15",          "95.0E": "NSS-6",              "96.5E": "Express AM33",
    "100.5E": "AsiaSat 5",
}
# ==========================================================

FEED_SOURCE_CHANNELS = ["biss2key", "live_7_feeds"]
FEED_FALLBACK_HOURS = 0
_RUNTIME_FEED_CACHE_LIMIT = 5000
def plugin_detect_hdd_mount():
    """
    اكتشاف أفضل مسار تخزين دائم (HDD/USB) بقراءة /proc/mounts
    + اختبار كتابة فعلي للتأكد من أن المسار قابل للكتابة.
    Fallback: /tmp لو مفيش حاجة متاحة.
    """
    # اقرأ المسارات الفعلية المماونتة من kernel
    mounted_rw = set()
    try:
        with open('/proc/mounts', 'r') as f:
            for line in f:
                parts = line.split()
                # parts[1]=mount_point  parts[3]=options (ro/rw...)
                if len(parts) >= 4 and 'rw' in parts[3].split(','):
                    mounted_rw.add(parts[1])
    except Exception:
        pass

    preferred = [
        "/media/hdd",  "/media/hdd2", "/media/hdd3",
        "/media/usb",  "/media/usb1", "/media/usb2", "/media/usb3",
        "/media/cf",   "/media/mmc1", "/media/mmc",
        "/mnt/hdd",    "/mnt/usb",
    ]

    for path in preferred:
        try:
            # يجب يكون مماونت فعلاً وقابل للكتابة
            if path not in mounted_rw:
                continue
            fury_dir = os.path.join(path, "furybiss_cache")
            # إنشاء المجلد لو مش موجود
            if not os.path.exists(fury_dir):
                os.makedirs(fury_dir)
            # اختبار كتابة فعلي
            test_path = os.path.join(fury_dir, ".wtest")
            with open(test_path, 'w') as f:
                f.write("ok")
            os.remove(test_path)
            return fury_dir
        except Exception:
            continue

    return "/tmp"

_FURYBISS_CACHE_DIR  = plugin_detect_hdd_mount()
_FEED_DISK_CACHE_FILE = os.path.join(_FURYBISS_CACHE_DIR, "furybiss_daily_feeds.json")
_OPENED_FEEDS_FILE    = os.path.join(_FURYBISS_CACHE_DIR, "furybiss_opened_feeds.json")
_runtime_feed_cache = []
_last_feed_fetch_used_fallback = False
_remote_feed_day_state = {
    'reference_ts': 0,
    'day_start': 0,
    'day_end': 2147483647,
    'day_key': '',
    'source': '',
}
# UTC offset detected automatically from Telegram message timestamps
# Example: +10800 = UTC+3 (Egypt winter / Saudi Arabia)
# Updated as soon as we receive a message with an explicit timezone such as +03:00
_detected_utc_offset_seconds = 0
# Telegram web datetime is often UTC (+00:00). The app may show the next local day.
# Use UTC+3 as the default Telegram display day offset, unless a non-zero offset is detected.
TELEGRAM_DEFAULT_UTC_OFFSET_SECONDS = 3 * 60 * 60

def plugin_get_feed_source_url(channel, before_post_id=None, nocache=None):
    # Check whether proxy is enabled in settings
    try:
        use_proxy = config.plugins.furybis.use_proxy.value
    except:
        use_proxy = False

    # Read the user proxy URL imported from the file
    try:
        user_proxy = config.plugins.furybiss.proxy_url.value
    except:
        user_proxy = ""

    # If proxy is enabled and the user added a valid URL
    if use_proxy and user_proxy.startswith("http"):
        # Remove any trailing slash (/) if the user added it by mistake to avoid // in the URL
        base_url = user_proxy.rstrip('/')
        url = "%s/s/%s" % (base_url, channel)
    else:
        # If proxy is not enabled or the URL is empty, use the original direct Telegram URL
        url = "https://t.me/s/%s" % channel

    params = []
    if before_post_id not in (None, "", 0):
        try:
            params.append('before=%s' % int(before_post_id))
        except:
            params.append('before=%s' % _to_text(before_post_id).strip())
    if nocache not in (None, ""):
        params.append('nocache=%s' % _to_text(nocache).strip())
    if params:
        url += '?' + '&'.join(params)
    
    return url


_proxy_connection_status_cache = {
    'url': '',
    'enabled': None,
    'timestamp': 0,
    'text': '',
}

def plugin_reset_proxy_status_cache():
    """Clear proxy status cache so Yes/No changes are reflected immediately."""
    global _proxy_connection_status_cache
    try:
        _proxy_connection_status_cache = {
            'url': '',
            'enabled': None,
            'timestamp': 0,
            'text': '',
        }
    except Exception:
        pass


def plugin_apply_proxy_runtime_change(clear_feed_cache=True):
    """Apply Enable Proxy Yes/No instantly without waiting for a GUI/device restart."""
    global _runtime_feed_cache

    try:
        config.plugins.furybis.use_proxy.save()
    except Exception:
        pass
    try:
        config.plugins.furybiss.proxy_url.save()
    except Exception:
        pass
    try:
        if configfile:
            configfile.save()
    except Exception:
        pass

    plugin_reset_proxy_status_cache()

    if clear_feed_cache:
        try:
            _runtime_feed_cache = []
        except Exception:
            pass
        try:
            plugin_clear_feed_disk_cache()
        except Exception:
            pass

    try:
        os.system("sync")
    except Exception:
        pass


def plugin_get_proxy_connection_status(force=False):
    """Test the saved proxy URL and return a short real connection quality text."""
    global _proxy_connection_status_cache

    try:
        use_proxy = bool(config.plugins.furybis.use_proxy.value)
    except Exception:
        use_proxy = False

    try:
        proxy_url = _to_text(config.plugins.furybiss.proxy_url.value).strip()
    except Exception:
        proxy_url = ''

    if not use_proxy:
        _proxy_connection_status_cache = {'url': proxy_url, 'enabled': False, 'timestamp': time.time(), 'text': 'Proxy Server: Disabled'}
        return 'Proxy Server: Disabled'

    if not proxy_url or not proxy_url.startswith('http'):
        _proxy_connection_status_cache = {'url': '', 'enabled': True, 'timestamp': 0, 'text': 'Proxy Server: Not configured'}
        return 'Proxy Server: Not configured'

    now = time.time()
    try:
        cached_url = _proxy_connection_status_cache.get('url', '')
        cached_timestamp = float(_proxy_connection_status_cache.get('timestamp', 0) or 0)
        cached_text = _proxy_connection_status_cache.get('text', '')
        cached_enabled = _proxy_connection_status_cache.get('enabled', None)
        if (not force) and cached_url == proxy_url and cached_enabled is True and cached_text and (now - cached_timestamp) < 45:
            return cached_text
    except Exception:
        pass

    test_url = proxy_url.rstrip('/') + '/s/biss2key?nocache=%d' % int(now)
    started = time.time()
    try:
        req = urllib2.Request(test_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        response = urllib2.urlopen(req, timeout=5)
        try:
            data = response.read(2048)
        except TypeError:
            data = response.read()
        elapsed = max(0.01, time.time() - started)

        if PY3 and isinstance(data, bytes):
            data_text = data.decode('utf-8', 'ignore')
        else:
            data_text = _to_text(data)

        if not data_text:
            status_text = 'Proxy Server: Connected - Weak'
        else:
            if elapsed <= 1.5:
                quality = 'Strong'
            elif elapsed <= 3.5:
                quality = 'Medium'
            else:
                quality = 'Weak'
            status_text = 'Proxy Server: Connected - %s (%.1fs)' % (quality, elapsed)
    except Exception as error:
        status_text = 'Proxy Server: Disconnected - %s' % _to_text(error).strip()[:70]

    _proxy_connection_status_cache = {
        'url': proxy_url,
        'enabled': True,
        'timestamp': now,
        'text': status_text,
    }
    return status_text


def plugin_get_proxy_status_color(status_text):
    """Return a UI color for the current proxy quality."""
    status_text = _to_text(status_text).lower()
    if 'strong' in status_text:
        return 0x00FF00  # green
    if 'medium' in status_text:
        return 0xFFCC00  # yellow
    if 'weak' in status_text or 'disconnected' in status_text:
        return 0xFF4A4A  # red
    if 'not configured' in status_text:
        return 0xFFCC00  # yellow
    return 0xCCCCCC  # disabled/neutral


def plugin_set_widget_foreground(widget, color_value):
    """Safely change an Enigma2 label foreground color."""
    try:
        from enigma import gRGB
        if widget is not None and getattr(widget, 'instance', None) is not None:
            widget.instance.setForegroundColor(gRGB(int(color_value)))
            return True
    except Exception:
        pass
    return False


def plugin_make_feed_cache_key(feed):
    if not isinstance(feed, dict):
        return ''

    try:
        post_id = int(feed.get('post_id', 0) or 0)
    except:
        post_id = 0

    if post_id > 0:
        channel = feed.get('source_channel', 'unknown')
        return 'post:%s_%s' % (channel, post_id)

    return 'sig:%s|%s|%s|%s' % (
        int(feed.get('timestamp', 0) or 0),
        _to_text(feed.get('name', '')).strip(),
        _to_text(feed.get('freq_str', '')).strip(),
        _to_text(feed.get('key', '')).strip(),
    )


def plugin_save_feed_cache_to_disk():
    """Save the cache to disk as JSON so it can be loaded after restart."""
    try:
        # Use the current Telegram day if available, not only the receiver day
        today_key = plugin_get_today_feed_day_key() or plugin_get_local_day_key()
        data = {
            'day_key': today_key,
            'feeds': _runtime_feed_cache,
        }
        with open(_FEED_DISK_CACHE_FILE, 'w') as f:
            json.dump(data, f)
    except Exception:
        pass


def plugin_load_feed_cache_from_disk():
    """Load the cache from disk on startup, only if it belongs to the same day."""
    global _runtime_feed_cache
    try:
        if not os.path.exists(_FEED_DISK_CACHE_FILE):
            return
        with open(_FEED_DISK_CACHE_FILE, 'r') as f:
            data = json.load(f)
        saved_day = data.get('day_key', '')
        # Use the current Telegram day if available, not only the receiver day
        today_key = plugin_get_today_feed_day_key() or plugin_get_local_day_key()
        if not saved_day or saved_day != today_key:
            # File from another day - remove it and start fresh
            try:
                os.remove(_FEED_DISK_CACHE_FILE)
            except Exception:
                pass
            return
        feeds = data.get('feeds', [])
        if isinstance(feeds, list):
            _runtime_feed_cache = [f for f in feeds if isinstance(f, dict)]
    except Exception:
        pass


def plugin_clear_feed_disk_cache():
    """Remove the cache file from disk at midnight."""
    try:
        if os.path.exists(_FEED_DISK_CACHE_FILE):
            os.remove(_FEED_DISK_CACHE_FILE)
    except Exception:
        pass


def plugin_store_runtime_feed(feed):
    global _runtime_feed_cache

    if not isinstance(feed, dict):
        return

    cache_key = plugin_make_feed_cache_key(feed)
    if not cache_key:
        return

    cloned = dict(feed)
    cloned['_cache_key'] = cache_key

    new_cache = [cloned]
    for item in _runtime_feed_cache:
        if item.get('_cache_key') == cache_key:
            continue
        new_cache.append(item)
        if len(new_cache) >= _RUNTIME_FEED_CACHE_LIMIT:
            break
    _runtime_feed_cache = new_cache

    # Save to disk every time to make sure feeds are not lost
    plugin_save_feed_cache_to_disk()


def plugin_get_runtime_feeds(start_ts=None, end_ts=None):
    results = []
    seen = {}

    for item in _runtime_feed_cache:
        if not isinstance(item, dict):
            continue

        ts = int(item.get('timestamp', 0) or 0)
        if start_ts is not None and ts < int(start_ts):
            continue
        if end_ts is not None and ts > int(end_ts):
            continue

        cache_key = item.get('_cache_key') or plugin_make_feed_cache_key(item)
        if not cache_key or cache_key in seen:
            continue

        seen[cache_key] = True
        results.append(dict(item))

    results.sort(key=lambda entry: int(entry.get('timestamp', 0) or 0), reverse=True)
    return results


def plugin_keep_best_feed(feed_map, dedup_id, feed_data):
    if not dedup_id:
        dedup_id = plugin_make_feed_cache_key(feed_data)
    if not dedup_id:
        return

    existing_feed = feed_map.get(dedup_id)
    if existing_feed is None:
        feed_map[dedup_id] = feed_data
        return

    if int(feed_data.get('score', 0) or 0) > int(existing_feed.get('score', 0) or 0):
        feed_map[dedup_id] = feed_data
        return

    if int(feed_data.get('score', 0) or 0) == int(existing_feed.get('score', 0) or 0):
        if int(feed_data.get('timestamp', 0) or 0) >= int(existing_feed.get('timestamp', 0) or 0):
            feed_map[dedup_id] = feed_data

crc_table = array("L")
for byte in range(256):
    crc = 0
    for bit in range(8):
        if (byte ^ crc) & 1: crc = (crc >> 1) ^ 0xEDB88320
        else: crc >>= 1
        byte >>= 1
    crc_table.append(crc)

def plugin_get_current_channel():
    info_dict = {"name": "Unknown", "sid": "0000", "hash": "", "vpid": "1FFF", "namespace": "00000000", "freq": ""}
    try:
        nav_instance = getattr(NavigationInstance, "instance", None)
        if nav_instance:
            service = nav_instance.getCurrentlyPlayingServiceReference()
            if service:
                try:
                    from enigma import eServiceCenter, iServiceInformation
                    info_center = eServiceCenter.getInstance().info(service)
                    if info_center: 
                        info_dict["name"] = info_center.getName(service) or info_dict["name"]
                        tp_data = info_center.getInfoObject(service, iServiceInformation.sTransponderData)
                        if tp_data:
                            freq = tp_data.get("frequency", 0)
                            if freq > 0:
                                info_dict["freq"] = str(int(freq / 1000))
                except: pass
                
                if info_dict["name"] == "Unknown":
                    try:
                        info = nav_instance.getCurrentlyPlayingServiceOrGroup().info()
                        info_dict["name"] = info.getName() or info_dict["name"]
                    except: pass

                try:
                    from enigma import iServiceInformation
                    vpid_int = nav_instance.getCurrentlyPlayingServiceOrGroup().info().getInfo(iServiceInformation.sVideoPID)
                    if vpid_int > 0: info_dict["vpid"] = hex(vpid_int)[2:].zfill(4).upper()
                except: pass

                try:
                    sid_num = service.getUnsignedData(1)
                    tsid_num = service.getUnsignedData(2)
                    onid_num = service.getUnsignedData(3)
                    namespace_num = service.getUnsignedData(4)

                    info_dict["sid"] = "%04X" % sid_num
                    info_dict["namespace"] = "%08X" % namespace_num
                    hash_namespace = namespace_num | 0xA0000000

                    if hash_namespace & 0xFFFF == 0:
                        data = "%04X%04X%04X%08X" % (sid_num, tsid_num, onid_num, hash_namespace)
                    else:
                        data = "%04X%08X" % (sid_num, hash_namespace)

                    string_data = binascii.unhexlify(data)
                    value = 0x2600 ^ 0xffffffff
                    for ch in string_data:
                        if PY3: value = crc_table[(ch ^ value) & 0xff] ^ (value >> 8)
                        else: value = crc_table[(ord(ch) ^ value) & 0xff] ^ (value >> 8)

                    info_dict["hash"] = "%08X" % (value ^ 0xffffffff)
                except: pass
    except: pass
        
    text = _to_text(info_dict["name"])
    for token in (u"\u0086", u"\u0087", "\x86", "\x87"): text = text.replace(token, "")
    try: text = re.sub(u"[\x00-\x1f]+", u" ", text)
    except: pass
    info_dict["name"] = u" ".join(text.split()) or u"Unknown"
    return info_dict

def plugin_get_current_biss_key(info, path):
    import os
    if not os.path.exists(path): return "Not Found"
    hash_val = info.get("hash", "")
    sid = info.get("sid", "0000")
    vpid = info.get("vpid", "1FFF")
    prefixes = []
    if hash_val: prefixes.extend(["F {0} 00".format(hash_val), "F {0} 01".format(hash_val)])
    if vpid and vpid != "1FFF" and vpid != "0000": prefixes.extend(["F {0}{1} 00".format(sid, vpid), "F {0}{1} 01".format(sid, vpid)])
    prefixes.extend(["F {0}1FFF 00".format(sid), "F {0}1FFF 01".format(sid)])
    
    found_keys = []
    try:
        with open(path, 'r') as f:
            lines = f.readlines()
            for line in reversed(lines):
                line_str = line.strip()
                if not line_str or line_str.startswith(";"): continue
                parts = line_str.split()
                if len(parts) >= 4 and parts[0].upper() == 'F':
                    prefix = " ".join(parts[:3]).upper()
                    if prefix in prefixes:
                        key = parts[3].upper()
                        if key not in found_keys:
                            found_keys.append(key)
                        if len(found_keys) >= 2: break
    except: pass
    
    if found_keys:
        return " | ".join(found_keys[::-1])
    return "Not Found"

def plugin_parse_telegram_datetime_to_timestamp(value):
    global _detected_utc_offset_seconds
    value = _to_text(value).strip()
    if not value:
        return 0
    try:
        offset_seconds = 0
        match = re.search(r'([+-])(\d{2}):?(\d{2})$', value)
        if match:
            sign = 1 if match.group(1) == '+' else -1
            offset_seconds = sign * ((int(match.group(2)) * 60 * 60) + (int(match.group(3)) * 60))
            value = value[:match.start()]
            # Save the UTC offset detected from Telegram messages to calculate local midnight correctly
            if offset_seconds != 0 and _detected_utc_offset_seconds == 0:
                _detected_utc_offset_seconds = offset_seconds
        elif value.endswith('Z'):
            value = value[:-1]
        struct_time = time.strptime(value, "%Y-%m-%dT%H:%M:%S")
        return int(calendar.timegm(struct_time) - offset_seconds)
    except:
        return 0


def plugin_extract_source_day_key(value):
    value = _to_text(value).strip()
    match = re.match(r'^(\d{4}-\d{2}-\d{2})(?:[Tt\s].*)?$', value)
    if match:
        return match.group(1)
    return ''


def plugin_get_effective_feed_utc_offset_seconds():
    try:
        detected = int(_detected_utc_offset_seconds or 0)
        if detected != 0:
            return detected
    except Exception:
        pass
    try:
        return int(TELEGRAM_DEFAULT_UTC_OFFSET_SECONDS)
    except Exception:
        return 0


def plugin_day_key_from_timestamp_with_offset(timestamp, offset_seconds=None):
    try:
        timestamp = int(timestamp or 0)
    except Exception:
        timestamp = 0
    if timestamp <= 0:
        return ''
    if offset_seconds is None:
        offset_seconds = plugin_get_effective_feed_utc_offset_seconds()
    try:
        return time.strftime('%Y-%m-%d', time.gmtime(int(timestamp) + int(offset_seconds or 0)))
    except Exception:
        return ''


def plugin_get_telegram_source_day_key(raw_datetime, timestamp=0):
    try:
        timestamp = int(timestamp or 0)
    except Exception:
        timestamp = 0
    if timestamp > 0:
        day_key = plugin_day_key_from_timestamp_with_offset(timestamp)
        if day_key:
            return day_key
    return plugin_extract_source_day_key(raw_datetime)


def plugin_format_source_published_text(value):
    value = _to_text(value).strip()
    match = re.match(r'^(\d{4}-\d{2}-\d{2})[Tt\s]+(\d{2}:\d{2})(?::\d{2})?', value)
    if match:
        return '%s  %s' % (match.group(1), match.group(2))
    return ''


def plugin_parse_http_datetime_to_timestamp(value):
    value = _to_text(value).strip()
    if not value:
        return 0
    try:
        from email.utils import parsedate_tz, mktime_tz
        parsed = parsedate_tz(value)
        if parsed:
            return int(mktime_tz(parsed))
    except Exception:
        pass
    return 0


def plugin_build_utc_day_window(reference_ts):
    try:
        reference_ts = int(reference_ts)
    except Exception:
        reference_ts = 0

    if reference_ts <= 0:
        return 0, 2147483647, ''

    offset = plugin_get_effective_feed_utc_offset_seconds()
    local_reference = int(reference_ts + offset)
    local_midnight_local = int(local_reference - (local_reference % 86400))
    day_start = int(local_midnight_local - offset)
    day_end = int(day_start + 86399)
    try:
        day_key = time.strftime('%Y-%m-%d', time.gmtime(local_midnight_local))
    except Exception:
        day_key = ''

    return day_start, day_end, day_key
def plugin_set_remote_feed_day(reference_ts, source=''):
    global _remote_feed_day_state

    day_start, day_end, day_key = plugin_build_utc_day_window(reference_ts)
    if int(reference_ts or 0) <= 0 or not day_key:
        return plugin_get_today_feed_window()

    current_reference = int(_remote_feed_day_state.get('reference_ts', 0) or 0)
    if current_reference > 0 and int(reference_ts) < current_reference:
        return (
            int(_remote_feed_day_state.get('day_start', 0) or 0),
            int(_remote_feed_day_state.get('day_end', 0) or 0),
        )

    _remote_feed_day_state = {
        'reference_ts': int(reference_ts),
        'day_start': day_start,
        'day_end': day_end,
        'day_key': day_key,
        'source': _to_text(source).strip(),
    }
    return day_start, day_end


def plugin_get_today_feed_window():
    try:
        day_start = int(_remote_feed_day_state.get('day_start', 0) or 0)
        day_end = int(_remote_feed_day_state.get('day_end', 0) or 0)
        if day_start > 0 and day_end >= day_start:
            return day_start, day_end
    except Exception:
        pass

    # If reading the Date header from Telegram/website fails, do not open all days.
    # Return only a one-day window instead of 0..2147483647 so yesterday feeds do not appear.
    # Use NTP-corrected time so a wrong receiver clock never shifts the window.
    try:
        day_start, day_end, day_key = plugin_build_utc_day_window(plugin_get_utc_time())
        if day_start > 0 and day_end >= day_start:
            return day_start, day_end
    except Exception:
        pass
    return 0, 0


def plugin_get_today_feed_day_key():
    try:
        day_key = _to_text(_remote_feed_day_state.get('day_key', '')).strip()
        if day_key:
            return day_key
    except Exception:
        pass

    try:
        day_start, day_end, day_key = plugin_build_utc_day_window(plugin_get_utc_time())
        if day_key:
            return day_key
    except Exception:
        pass
    return ''


def plugin_refresh_feed_day_window_with_detected_offset(source=''):
    """Recalculate the day window after detecting the timezone from Telegram messages."""
    global _remote_feed_day_state
    try:
        reference_ts = int(_remote_feed_day_state.get('reference_ts', 0) or 0)
    except Exception:
        reference_ts = 0

    if reference_ts <= 0:
        return plugin_get_today_feed_window()

    day_start, day_end, day_key = plugin_build_utc_day_window(reference_ts)
    if not day_key:
        return plugin_get_today_feed_window()

    _remote_feed_day_state = {
        'reference_ts': reference_ts,
        'day_start': day_start,
        'day_end': day_end,
        'day_key': day_key,
        'source': _to_text(source or _remote_feed_day_state.get('source', '')).strip(),
    }
    return day_start, day_end


def plugin_get_response_header_value(response, header_name):
    header_name = _to_text(header_name).strip()
    if response is None or not header_name:
        return ''

    info_obj = None
    try:
        info_method = getattr(response, 'info', None)
        if callable(info_method):
            info_obj = info_method()
    except Exception:
        info_obj = None

    for candidate in (info_obj, getattr(response, 'headers', None)):
        if candidate is None:
            continue
        for method_name in ('get', 'getheader'):
            try:
                getter = getattr(candidate, method_name, None)
                if getter is None:
                    continue
                value = getter(header_name)
                if value:
                    return _to_text(value).strip()
            except Exception:
                pass

    return ''


def plugin_update_feed_day_from_http_response(response, source=''):
    header_value = plugin_get_response_header_value(response, 'Date')
    reference_ts = plugin_parse_http_datetime_to_timestamp(header_value)
    if reference_ts > 0:
        return plugin_set_remote_feed_day(reference_ts, source)
    return plugin_get_today_feed_window()


def plugin_feed_is_in_current_window(feed, day_start_timestamp=None, day_end_timestamp=None):
    if not isinstance(feed, dict):
        return False

    if day_start_timestamp is None or day_end_timestamp is None:
        day_start_timestamp, day_end_timestamp = plugin_get_today_feed_window()

    try:
        day_start_timestamp = int(day_start_timestamp or 0)
        day_end_timestamp = int(day_end_timestamp or 0)
    except Exception:
        day_start_timestamp, day_end_timestamp = 0, 0

    # Do not allow opening all days as fallback, because that caused previous-day feeds to appear.
    if day_start_timestamp <= 0 or day_end_timestamp <= 0 or day_end_timestamp < day_start_timestamp:
        return False

    try:
        feed_timestamp = int(feed.get('timestamp', 0) or 0)
    except Exception:
        feed_timestamp = 0

    if feed_timestamp <= 0:
        return False

    return day_start_timestamp <= feed_timestamp <= day_end_timestamp


def plugin_feed_is_in_current_telegram_day(feed, day_start_timestamp=None, day_end_timestamp=None):
    """Strict Telegram message filtering: the message day must match the current Telegram day."""
    if not isinstance(feed, dict):
        return False

    target_day_key = plugin_get_today_feed_day_key()
    source_day_key = _to_text(feed.get('source_day_key', '')).strip()

    # If the message date exists in Telegram datetime, use it as an additional strict condition.
    if target_day_key and source_day_key and source_day_key != target_day_key:
        return False

    return plugin_feed_is_in_current_window(feed, day_start_timestamp, day_end_timestamp)


def plugin_extract_telegram_post_id(raw_message):
    try:
        post_match = re.search(r'data-post="[^/"]+/(\d+)"', raw_message, re.IGNORECASE)
        if post_match:
            return int(post_match.group(1))
    except:
        pass
    return None


def plugin_get_telegram_next_page_url(html, channel=None, last_post_id=None):
    # Use our proxy helper to avoid blocking old pages
    if last_post_id and channel:
        return plugin_get_feed_source_url(channel, before_post_id=last_post_id)
    return None


def plugin_extract_feed_type(text):
    text = _to_text(text).replace(u"\xa0", u" ")
    if not text:
        return ""

    if re.search(r'\b4\s*[:.\-/|]?\s*2\s*[:.\-/|]?\s*2\b', text, re.IGNORECASE):
        return '4:2:2'
    if re.search(r'\b4\s*[:.\-/|]?\s*2\s*[:.\-/|]?\s*0\b', text, re.IGNORECASE):
        return '4:2:0'
    return ''


def plugin_extract_key_value(text):
    text = _to_text(text).replace(u"\xa0", u" ")
    if not text:
        return ""

    # Adjustment here: use [ \t] instead of \s to avoid matching new lines
    key_matches = re.findall(r'(?:Key|CW|BISS)\s*[:\-]?\s*([0-9A-Fa-f \t]{16,40})', text, re.IGNORECASE)
    found_keys = []
    
    for match in key_matches:
        raw_key = match.replace(" ", "").strip().upper()
        if len(raw_key) >= 16:
            clean_key = raw_key[:16]
            if clean_key not in found_keys:
                found_keys.append(clean_key)
                
    if found_keys:
        return ",".join(found_keys)

    fta_match = re.search(r'(?:\b(?:Key|CW|BISS)\b\s*[:\-]?\s*)?\bFTA\b', text, re.IGNORECASE)
    if fta_match:
        return "FTA"

    return ""


def plugin_unescape_html(value):
    value = _to_text(value)
    try:
        if PY3:
            import html
            return html.unescape(value)
    except Exception:
        pass
    try:
        import HTMLParser
        return HTMLParser.HTMLParser().unescape(value)
    except Exception:
        return value


def plugin_compact_key_text(value):
    value_str = _to_text(value)
    if "," in value_str:
        keys = value_str.split(",")
        cleaned_keys = []
        for k in keys:
            cleaned = re.sub(r'[^0-9A-Fa-f]', '', k).upper()
            if len(cleaned) >= 16:
                cleaned_keys.append(cleaned[:16])
        return ",".join(cleaned_keys)
        
    cleaned = re.sub(r'[^0-9A-Fa-f]', '', value_str).upper()
    if len(cleaned) >= 16:
        return cleaned[:16]
    return ''


def plugin_format_key_display(value):
    raw_keys = plugin_compact_key_text(value).split(',')
    displays = []
    for raw_key in raw_keys:
        if raw_key and raw_key != 'FTA':
            displays.append(' '.join([raw_key[i:i + 2] for i in range(0, len(raw_key), 2)]))
            
    if displays:
        return ' | '.join(displays)

    value = _to_text(value).strip().upper()
    if value == 'FTA':
        return 'FTA'
    return value


def plugin_is_generic_feed_name(name, freq_val=None):
    name = _to_text(name).strip()
    if not name:
        return True

    lower_name = name.lower()
    if lower_name in ('feed unknown', 'unknown', 'unname', 'unnamed', 'no name'):
        return True
    if lower_name.startswith('livefeed'):
        return True

    freq_val = _to_text(freq_val).strip()
    if freq_val and lower_name == ('livefeed %s' % freq_val).lower():
        return True
    return False


def plugin_normalize_match_text(value):
    text = _to_text(value).lower()
    try:
        text = re.sub(u'[\x00-\x1f]+', u' ', text)
    except Exception:
        pass

    text = text.replace('&', ' ')
    try:
        text = re.sub(u'[^0-9a-z\u0600-\u06ff]+', u' ', text)
    except Exception:
        text = re.sub(r'[^0-9a-z]+', ' ', text)
    return u' '.join(text.split())


def plugin_names_match(left_name, right_name):
    left_norm = plugin_normalize_match_text(left_name)
    right_norm = plugin_normalize_match_text(right_name)

    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm or left_norm in right_norm or right_norm in left_norm:
        return True

    left_tokens = [token for token in left_norm.split() if len(token) > 2]
    right_tokens = [token for token in right_norm.split() if len(token) > 2]
    if not left_tokens or not right_tokens:
        return False

    common_tokens = [token for token in left_tokens if token in right_tokens]
    return len(common_tokens) >= min(2, len(left_tokens), len(right_tokens))


def plugin_parse_simple_timestamp(value):
    value = _to_text(value).strip()
    if not value:
        return 0

    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S'):
        try:
            return int(time.mktime(time.strptime(value, fmt)))
        except Exception:
            pass
    return 0


LIVE_FEED_SERVER_OFFSET_HOURS = 3.0


def plugin_parse_live_feed_server_timestamp(value, source_offset_hours=LIVE_FEED_SERVER_OFFSET_HOURS):
    value = _to_text(value).strip()
    if not value:
        return 0

    normalized = re.sub(r'[Tt]', ' ', value)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    match = re.match(r'^(\d{4})[-/](\d{2})[-/](\d{2})\s+(\d{2}):(\d{2})(?::(\d{2}))?$', normalized)
    if not match:
        return plugin_parse_simple_timestamp(normalized)

    try:
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        hour = int(match.group(4))
        minute = int(match.group(5))
        second = int(match.group(6) or 0)

        utc_timestamp = calendar.timegm((year, month, day, hour, minute, second, 0, 0, 0))
        offset_seconds = int(round(float(source_offset_hours or 0) * 3600))
        return int(utc_timestamp - offset_seconds)
    except Exception:
        return plugin_parse_simple_timestamp(normalized)


def plugin_extract_list_time_text(feed):
    published_text = _to_text(feed.get('published', '')).strip()
    if published_text:
        match = re.search(r'\b(\d{2}:\d{2})\b', published_text)
        if match:
            return '[%s]' % match.group(1)

    timestamp = int(feed.get('timestamp', 0) or 0)
    if timestamp > 0:
        try:
            return '[%s]' % time.strftime('%H:%M', time.localtime(timestamp))
        except Exception:
            pass

    return '[--:--]'


def plugin_extract_published_display_text(feed):
    published_text = _to_text(feed.get('published', '')).strip()
    if published_text:
        return published_text

    timestamp = int(feed.get('timestamp', 0) or 0)
    if timestamp > 0:
        try:
            return time.strftime('%Y-%m-%d  %H:%M', time.localtime(timestamp))
        except Exception:
            pass

    return ''


def plugin_extract_event_name_from_info(text, freq_val=''):
    text = _to_text(text).replace(u'\xa0', u' ').strip()
    if not text:
        return ''

    patterns = (
        r'\bID\s*[:\-]?\s*([^\n|]+?)(?:\s+\bCW\b|$)',
        r'\b(?:Event|Match|Channel|Feed)\s*[:\-]?\s*([^\n|]+)',
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip(' -|')
            if candidate and not plugin_is_generic_feed_name(candidate, freq_val):
                return candidate

    parts = [part.strip(' -|') for part in re.split(r'\s*\|\s*', text) if part.strip(' -|')]
    for part in parts:
        if re.search(r'@\s*\d{1,3}(?:\.\d+)?\s*[°º]?\s*[EWew]\b', part):
            continue
        if re.search(r'\b\d{4,5}\s*[VHvh]\s*\d{3,5}\b', part):
            continue
        if re.search(r'\b(?:DVB|QPSK|8PSK|16APSK|H\.264|HEVC|AVC|MPEG|VIDEO)\b', part, re.IGNORECASE):
            continue
        if re.search(r'\b(?:4:2:0|4:2:2|Mbit/s|Mb/s|bit/s|fps|Kbps|Unknown)\b', part, re.IGNORECASE):
            continue
        if re.search(r'\b\d{3,4}\s*[x×]\s*\d{3,4}\b', part, re.IGNORECASE):
            continue
        upper_part = part.upper()
        if upper_part.startswith('CW') or upper_part.startswith('KEY'):
            continue
        if len(part) < 3:
            continue
        if not plugin_is_generic_feed_name(part, freq_val):
            return part

    return ''


def plugin_build_live_feed_full_text(sat, freq_str, feed_type, raw_key, timestamp=0):
    sat = _to_text(sat).strip()
    freq_str = _to_text(freq_str).strip()
    raw_key = _to_text(raw_key).strip().upper()
    feed_type = _to_text(feed_type).strip() or 'Unknown'

    published_text = '-'
    if timestamp > 0:
        try:
            published_text = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))
        except Exception:
            pass

    # Sat is shown separately in full_post_sat widget (white color)
    # FuryBiss-IslamSalama takes the first line (yellow)
    base_text = "FuryBiss-IslamSalama\nPublished: %s\nFreq: %s\nType: %s" % (published_text, freq_str, feed_type)

    if raw_key == 'FTA':
        return base_text + "\nCW: FTA"
    elif raw_key:
        return base_text + "\nBISS Key: %s" % raw_key
    return base_text


def plugin_parse_live_feed_entries_from_page_text(page_text):
    page_text = _to_text(page_text)
    if not page_text:
        return []

    normalized_lines = []
    for raw_line in page_text.splitlines():
        clean_line = u' '.join(_to_text(raw_line).replace(u'\xa0', u' ').split())
        if clean_line:
            normalized_lines.append(clean_line)

    status_re = re.compile(r'^(?:ON\s+)?(.+?)\s+(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})$', re.IGNORECASE)
    sat_re = re.compile(r'@\s*\d{1,3}(?:\.\d+)?\s*[°º]?\s*[EWew]\b')
    freq_re = re.compile(r'^(\d{4,5})\s*([VHvh])\s*(\d{3,5}(?:[\.,]\d+)?)$')
    key_line_re = re.compile(r'^(?:[0-9A-Fa-f]{2}(?:\s+|$)){8,}$')

    feed_map = {}
    i = 0
    while i < len(normalized_lines):
        line = normalized_lines[i]
        status_match = status_re.match(line)
        if not status_match:
            i += 1
            continue

        status_text = status_match.group(1).strip()
        timestamp = plugin_parse_simple_timestamp('%s %s' % (status_match.group(2), status_match.group(3)))

        j = i + 1
        while j < len(normalized_lines) and normalized_lines[j].upper() in ('NO SNAPSHOT', 'SNAPSHOT', 'IMAGE'):
            j += 1

        if j >= len(normalized_lines) or not sat_re.search(normalized_lines[j]):
            i += 1
            continue
        sat = normalized_lines[j]
        j += 1

        if j >= len(normalized_lines):
            break

        freq_match = freq_re.match(normalized_lines[j])
        if not freq_match:
            i += 1
            continue

        freq_val = freq_match.group(1)
        pol_val = freq_match.group(2).upper()
        sr_raw = freq_match.group(3).replace(',', '.')
        try:
            sr_val = str(int(float(sr_raw)))
        except Exception:
            sr_val = freq_match.group(3)
        freq_str = '%s %s %s' % (freq_val, pol_val, sr_val)
        j += 1

        video_line = ''
        if j < len(normalized_lines) and '|' in normalized_lines[j] and not status_re.match(normalized_lines[j]):
            video_line = normalized_lines[j]
            j += 1

        format_line = ''
        if j < len(normalized_lines) and '|' in normalized_lines[j] and not status_re.match(normalized_lines[j]):
            format_line = normalized_lines[j]
            j += 1

        name = ''
        if j < len(normalized_lines):
            candidate_name = normalized_lines[j]
            if not status_re.match(candidate_name) and not sat_re.search(candidate_name) and not freq_re.match(candidate_name) and not key_line_re.match(candidate_name) and candidate_name.upper() not in ('NO SNAPSHOT', 'SNAPSHOT'):
                name = candidate_name.strip()
                j += 1

        key_line = ''
        if j < len(normalized_lines) and key_line_re.match(normalized_lines[j]):
            key_line = normalized_lines[j]
            j += 1

        raw_key = plugin_compact_key_text(key_line)
        if not raw_key and re.search(r'\bclear\b', status_text, re.IGNORECASE):
            raw_key = 'FTA'

        feed_type = plugin_extract_feed_type('%s %s' % (video_line, format_line)) or 'Unknown'
        if not name:
            name = plugin_extract_event_name_from_info('%s | %s' % (video_line, format_line), freq_val)
        if not name:
            name = 'LiveFeed %s' % freq_val

        full_text = plugin_build_live_feed_full_text(sat, freq_str, feed_type, raw_key, timestamp)

        score = 0
        if name and not plugin_is_generic_feed_name(name, freq_val):
            score += 2
        if sat and sat != 'Unknown':
            score += 1
        if freq_str and freq_str != 'Unknown':
            score += 1
        if feed_type != 'Unknown':
            score += 1
        if raw_key:
            score += 1

        feed_data = {
            'name': name,
            'sat': sat,
            'freq_str': freq_str,
            'freq_val': freq_val,
            'pol_val': pol_val,
            'sr_val': sr_val,
            'feed_type': feed_type,
            'key': raw_key,
            'full_text': full_text,
            'timestamp': timestamp,
            'post_id': 0,
            'source': 'website',
            'status_text': status_text,
            'score': score,
        }

        dedup_id = '%s|%s|%s|%s' % (freq_val, pol_val, sr_val, raw_key or name)
        plugin_keep_best_feed(feed_map, dedup_id, feed_data)
        i = max(j, i + 1)

    results = list(feed_map.values())
    results.sort(key=lambda item: int(item.get('timestamp', 0) or 0), reverse=True)
    return results


def plugin_parse_live_feed_json_fragments(html):
    html = _to_text(html)
    if not html:
        return []

    feed_map = {}

    context_blocks = []
    context_pattern = re.compile(
        r'<script[^>]*class="[^"]*services-json[^"]*"[^>]*>(?P<json>\[\s*\{.*?\}\s*\])</script>'
        r'(?P<tail>.*?)(?:<span[^>]*class="[^"]*\bts\b[^"]*"[^>]*data-server-ts="(?P<ts>[^"]+)"|(?=<script[^>]*class="[^"]*services-json[^"]*")|$)',
        re.IGNORECASE | re.DOTALL
    )
    for match in context_pattern.finditer(html):
        context_blocks.append((match.group('json'), match.group('tail') or '', match.group('ts') or ''))

    if not context_blocks:
        loose_blocks = re.findall(r'(\[\s*\{.*?\}\s*\])', html, re.DOTALL)
        context_blocks = [(block, '', '') for block in loose_blocks]

    for block, block_tail, block_ts in context_blocks:
        try:
            parsed = json.loads(plugin_unescape_html(block))
        except Exception:
            continue

        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list):
            continue

        published_raw = _to_text(block_ts).strip()
        timestamp = plugin_parse_live_feed_server_timestamp(published_raw)

        tail_text = plugin_unescape_html(re.sub(r'<[^>]+>', ' ', block_tail or ''))
        if not published_raw:
            tail_ts_match = re.search(r'(\d{4}[-/]\d{2}[-/]\d{2}\s+\d{2}:\d{2}(?::\d{2})?)', tail_text)
            if tail_ts_match:
                published_raw = tail_ts_match.group(1)
                timestamp = plugin_parse_live_feed_server_timestamp(published_raw)

        status_parts = []
        for status_match in re.findall(r'<span[^>]*class="[^"]*\bbadge\b[^"]*"[^>]*>([^<]+)</span>', block_tail or '', re.IGNORECASE):
            status_text = u' '.join(plugin_unescape_html(status_match).split())
            if not status_text:
                continue
            upper_status = status_text.upper()
            if upper_status in ('ON', 'OFF') or 'KEY' in upper_status or 'CLEAR' in upper_status or 'BISS' in upper_status:
                if status_text not in status_parts:
                    status_parts.append(status_text)
        combined_status_text = ' '.join(status_parts).strip()

        published_text = ''
        if timestamp > 0:
            try:
                published_text = time.strftime('%Y-%m-%d %H:%M', time.localtime(timestamp))
            except Exception:
                published_text = ''
        if not published_text:
            published_text = published_raw

        for item in parsed:
            if not isinstance(item, dict):
                continue

            info_text = _to_text(item.get('info', '')).replace(u'\xa0', u' ').strip()
            if not info_text:
                continue

            freq_match = re.search(r'\b(\d{4,5})\s*([VHvh])\s*(\d{3,5}(?:[\.,]\d+)?)\b', info_text)
            if not freq_match:
                continue

            freq_val = freq_match.group(1)
            pol_val = freq_match.group(2).upper()
            sr_raw = freq_match.group(3).replace(',', '.')
            try:
                sr_val = str(int(float(sr_raw)))
            except Exception:
                sr_val = freq_match.group(3)
            freq_str = '%s %s %s' % (freq_val, pol_val, sr_val)

            sat = 'Unknown'
            sat_match = re.search(r'(.+?@\s*\d{1,3}(?:\.\d+)?\s*[°º]?[EWew])', info_text, re.IGNORECASE)
            if sat_match:
                sat = sat_match.group(1).strip(' |')

            raw_key = plugin_compact_key_text(item.get('cw', ''))
            is_clear = str(item.get('is_clear', '')).strip().lower()
            if not raw_key and is_clear in ('true', '1', 'yes'):
                raw_key = 'FTA'

            name = _to_text(item.get('name', '')).strip()
            if plugin_is_generic_feed_name(name, freq_val):
                name = ''
            if not name:
                name = plugin_extract_event_name_from_info(info_text, freq_val)
            if not name:
                name = 'LiveFeed %s' % freq_val

            feed_type = plugin_extract_feed_type(info_text) or 'Unknown'

            base_text = "FuryBiss-IslamSalama\nPublished: %s\nFreq: %s\nType: %s" % (published_text or '-', freq_str, feed_type)
            if raw_key == 'FTA':
                pretty_text = base_text + "\nCW: FTA"
            elif raw_key:
                pretty_text = base_text + "\nBISS Key: %s" % raw_key
            else:
                pretty_text = base_text

            score = 0
            if name and not plugin_is_generic_feed_name(name, freq_val):
                score += 1
            if sat != 'Unknown':
                score += 1
            if freq_str != 'Unknown':
                score += 1
            if feed_type != 'Unknown':
                score += 1
            if raw_key:
                score += 1
            if timestamp > 0:
                score += 1

            feed_data = {
                'name': name,
                'sat': sat,
                'freq_str': freq_str,
                'freq_val': freq_val,
                'pol_val': pol_val,
                'sr_val': sr_val,
                'feed_type': feed_type,
                'key': raw_key,
                'full_text': pretty_text,
                'published': published_text,
                'timestamp': timestamp,
                'post_id': 0,
                'source': 'website',
                'status_text': combined_status_text or ('Clear' if raw_key == 'FTA' else 'Key Found' if raw_key else ''),
                'score': score,
            }

            dedup_id = '%s|%s|%s|%s' % (freq_val, pol_val, sr_val, raw_key or name)
            plugin_keep_best_feed(feed_map, dedup_id, feed_data)

    results = list(feed_map.values())
    results.sort(key=lambda item: int(item.get('timestamp', 0) or 0), reverse=True)
    return results


def plugin_fetch_live_feed_net_legacy(html):
    feeds = []
    blocks = re.split(r'<div[^>]*class="[^"]*card[^"]*"[^>]*>', html, flags=re.IGNORECASE)
    seen_ids = {}

    for block in blocks:
        cleaned_block = re.sub(r'<script\b[^>]*>.*?</script>', ' ', block, flags=re.IGNORECASE | re.DOTALL)
        cleaned_block = re.sub(r'<style\b[^>]*>.*?</style>', ' ', cleaned_block, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'<br\s*/?>', '\n', cleaned_block, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = plugin_unescape_html(text)
        text = re.sub(r'\r', '\n', text)
        text = re.sub(r'\n\s*\n+', '\n', text)
        text = '\n'.join([u' '.join(_to_text(line).split()) for line in text.split('\n') if u' '.join(_to_text(line).split())]).strip()

        if not text:
            continue

        raw_key = plugin_extract_key_value(text)

        freq_val, pol_val, sr_val = '', '', ''
        freq_str = 'Unknown'
        freq_match = re.search(r'\b(\d{4,5})\s*([VHvh])\s*(\d{3,5})\b', text)
        if not freq_match:
            freq_match = re.search(r'(?:Freq(?:uency)?)\s*[:\-]?\s*(\d{4,5}).*?\b([VHvh])\b.*?(\d{3,5})', text, re.IGNORECASE | re.DOTALL)
        if freq_match:
            freq_val = freq_match.group(1)
            pol_val = freq_match.group(2).upper()
            sr_val = freq_match.group(3)
            freq_str = '%s %s %s' % (freq_val, pol_val, sr_val)

        if not freq_val:
            continue

        sat = 'Unknown'
        sat_match = re.search(r'([A-Za-z0-9\-\/\s]+@\s*\d{1,3}(?:\.\d+)?[°]?[EWew])', text)
        if sat_match:
            sat = sat_match.group(1).strip()
        else:
            orb_match = re.search(r'^.*?\b\d{1,3}(?:\.\d+)?\s*[°]?\s*[EWew]\b.*?$', text, re.MULTILINE)
            if orb_match:
                sat = orb_match.group(0).strip()

        feed_type = plugin_extract_feed_type(text) or 'Unknown'

        name = plugin_extract_event_name_from_info(text, freq_val)
        if not name:
            name_match = re.search(r'\bID\b[\s:\-]+([^\n]+)', text, re.IGNORECASE)
            if not name_match:
                name_match = re.search(r'\b(?:Feed|Channel|Match|Event|ENC)\b[\s:\-]+([^\n]+)', text, re.IGNORECASE)
            if name_match:
                candidate_name = name_match.group(1).strip()
                if candidate_name:
                    name = candidate_name
        if not name:
            name = 'LiveFeed %s' % freq_val

        timestamp_match = re.search(r'(\d{4}[\-/]\d{2}[\-/]\d{2}[\sT]+\d{2}:\d{2}:\d{2})', text)
        post_timestamp = plugin_parse_simple_timestamp(timestamp_match.group(1).replace('/', '-')) if timestamp_match else 0

        if not raw_key and re.search(r'\bclear\b', text, re.IGNORECASE):
            raw_key = 'FTA'

        if not raw_key and feed_type == 'Unknown' and sat == 'Unknown':
            continue

        unique_id = '%s|%s|%s|%s|%s' % (freq_val, pol_val, sr_val, name, raw_key or 'NO_KEY')
        if unique_id in seen_ids:
            continue

        if raw_key:
            full_text = plugin_build_live_feed_full_text(sat, freq_str, feed_type, raw_key, post_timestamp)
        else:
            full_text = text

        feed_data = {
            'name': name,
            'sat': sat,
            'freq_str': freq_str,
            'freq_val': freq_val,
            'pol_val': pol_val,
            'sr_val': sr_val,
            'feed_type': feed_type,
            'key': raw_key,
            'full_text': full_text,
            'timestamp': post_timestamp,
            'post_id': 0,
            'source': 'website',
            'score': 6 if raw_key else 5,
        }

        feeds.append(feed_data)
        seen_ids[unique_id] = True

    return feeds


def plugin_fetch_live_feed_net():
    feeds = []
    url = 'https://live-feed.net/'
    try:
        req = urllib2.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        response = urllib2.urlopen(req, timeout=10)
        plugin_update_feed_day_from_http_response(response, 'website')
        html = response.read()
        if PY3:
            html = html.decode('utf-8', 'ignore')
        else:
            html = _to_text(html)

        cleaned_html = re.sub(r'<script\b[^>]*>.*?</script>', ' ', html, flags=re.IGNORECASE | re.DOTALL)
        cleaned_html = re.sub(r'<style\b[^>]*>.*?</style>', ' ', cleaned_html, flags=re.IGNORECASE | re.DOTALL)
        page_text = re.sub(r'<br\s*/?>', '\n', cleaned_html, flags=re.IGNORECASE)
        page_text = re.sub(r'</(?:div|section|article|p|li|tr|h\d)>', '\n', page_text, flags=re.IGNORECASE)
        page_text = re.sub(r'<[^>]+>', ' ', page_text)
        page_text = plugin_unescape_html(page_text)
        page_text = re.sub(r'\r', '\n', page_text)

        feed_map = {}
        for candidate_list in (
            plugin_parse_live_feed_entries_from_page_text(page_text),
            plugin_parse_live_feed_json_fragments(html),
            plugin_fetch_live_feed_net_legacy(html),
        ):
            for feed_data in candidate_list:
                feed_name = _to_text(feed_data.get('name', '')).strip()
                
                # 1. Ignore fake feeds that start with LiveFeed
                if feed_name.lower().startswith('livefeed'):
                    continue
                    
                # 2. Ignore feeds where the key was mistakenly captured as the name
                # (This line detects any name containing 6 or more pairs of key letters/numbers)
                if re.search(r'(?:[A-Fa-f0-9]{2}[\s:]+){5,}[A-Fa-f0-9]{2}', feed_name):
                    continue

                # 3. Completely ignore 4:2:2 feeds as requested
                if feed_data.get('feed_type') == '4:2:2':
                    continue

                dedup_id = '%s|%s|%s|%s' % (
                    _to_text(feed_data.get('freq_val', '')).strip(),
                    _to_text(feed_data.get('pol_val', '')).strip(),
                    _to_text(feed_data.get('sr_val', '')).strip(),
                    plugin_compact_key_text(feed_data.get('key', '')) or feed_name,
                )
                plugin_keep_best_feed(feed_map, dedup_id, feed_data)

        feeds = list(feed_map.values())
        feeds.sort(key=lambda item: int(item.get('timestamp', 0) or 0), reverse=True)

    except Exception as e:
        print('[FuryBiss] Error fetching from live-feed.net: ' + str(e))

    return feeds


def plugin_fetch_all_feeds():
    global _last_feed_fetch_used_fallback

    # Load the cache from disk as soon as the function is called so old feeds are not lost
    plugin_load_feed_cache_from_disk()

    feeds = []
    _last_feed_fetch_used_fallback = False
    day_start_timestamp, day_end_timestamp = plugin_get_today_feed_window()

    try:
        current_source = config.plugins.furybis.feed_source.value
    except Exception:
        current_source = "both"

    if current_source in ("both", "telegram"):
        try:
            max_pages = 3
            unique_today_feeds = {}
            seen_posts = {}
            visited_urls = {}

            for channel in FEED_SOURCE_CHANNELS:
                try:
                    url = plugin_get_feed_source_url(channel, nocache=int(time.time()))
                    for page in range(max_pages):
                        if not url or url in visited_urls:
                            break
                        visited_urls[url] = True

                        req = urllib2.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                        response = urllib2.urlopen(req, timeout=5)
                        day_start_timestamp, day_end_timestamp = plugin_update_feed_day_from_http_response(response, 'telegram:%s' % channel)

                        html = response.read()
                        if PY3:
                            html = html.decode('utf-8', 'ignore')
                        else:
                            html = _to_text(html)

                        raw_messages = html.split('tgme_widget_message_wrap')[1:]
                        if not raw_messages:
                            break

                        oldest_post_id = None
                        page_has_current_day_messages = False
                        page_has_older_messages = False

                        for raw in raw_messages:
                            post_id = plugin_extract_telegram_post_id(raw)
                            signature = "%s_%s" % (channel, post_id) if post_id is not None else None
                            if signature is not None and signature in seen_posts:
                                continue

                            if post_id is not None:
                                if oldest_post_id is None or post_id < oldest_post_id:
                                    oldest_post_id = post_id

                            feed_data = plugin_parse_telegram_message(raw)
                            if not feed_data:
                                continue

                            if int(feed_data.get('timestamp', 0) or 0) > 0:
                                # After reading the first Telegram message, the timezone may have been detected from datetime.
                                # Recalculate the current day window, then filter only the same Telegram day.
                                day_start_timestamp, day_end_timestamp = plugin_refresh_feed_day_window_with_detected_offset(
                                    'telegram:%s-feed' % channel
                                )

                            feed_timestamp = int(feed_data.get('timestamp', 0) or 0)
                            if feed_timestamp > 0 and day_start_timestamp > 0 and feed_timestamp < day_start_timestamp:
                                page_has_older_messages = True

                            if not plugin_feed_is_in_current_telegram_day(feed_data, day_start_timestamp, day_end_timestamp):
                                continue

                            page_has_current_day_messages = True
                            feed_data['source_channel'] = channel

                            if signature is None:
                                signature = "%s|%s|%s" % (
                                    int(feed_data.get('timestamp', 0) or 0),
                                    _to_text(feed_data.get('name', '')).strip(),
                                    _to_text(feed_data.get('key', '')).strip(),
                                )
                                if signature in seen_posts:
                                    continue

                            dedup_id = "%s|%s|%s|%s" % (
                                _to_text(feed_data.get('freq_val', '')).strip(),
                                _to_text(feed_data.get('pol_val', '')).strip(),
                                _to_text(feed_data.get('sr_val', '')).strip(),
                                plugin_compact_key_text(feed_data.get('key', '')) or _to_text(feed_data.get('name', '')).strip(),
                            )
                            plugin_keep_best_feed(unique_today_feeds, dedup_id, feed_data)

                            plugin_store_runtime_feed(feed_data)
                            seen_posts[signature] = True

                        next_url = plugin_get_telegram_next_page_url(html, channel, oldest_post_id)
                        if not next_url:
                            break
                        if page_has_older_messages and not page_has_current_day_messages:
                            break
                        url = next_url
                except Exception:
                    continue

            feeds = list(unique_today_feeds.values())

            # Always merge with the runtime cache so same-day feeds are not lost
            cached_feeds = plugin_get_runtime_feeds(day_start_timestamp, day_end_timestamp)
            if cached_feeds:
                existing_dedup_ids = set()
                for f in feeds:
                    dk = "%s|%s|%s|%s" % (
                        _to_text(f.get("freq_val", "")).strip(),
                        _to_text(f.get("pol_val", "")).strip(),
                        _to_text(f.get("sr_val", "")).strip(),
                        plugin_compact_key_text(f.get("key", "")) or _to_text(f.get("name", "")).strip(),
                    )
                    existing_dedup_ids.add(dk)
                for cf in cached_feeds:
                    dk = "%s|%s|%s|%s" % (
                        _to_text(cf.get("freq_val", "")).strip(),
                        _to_text(cf.get("pol_val", "")).strip(),
                        _to_text(cf.get("sr_val", "")).strip(),
                        plugin_compact_key_text(cf.get("key", "")) or _to_text(cf.get("name", "")).strip(),
                    )
                    if dk not in existing_dedup_ids:
                        feeds.append(cf)
                        existing_dedup_ids.add(dk)

            feeds.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

        except Exception:
            feeds = plugin_get_runtime_feeds(day_start_timestamp, day_end_timestamp)

    if current_source in ("both", "website"):
        website_feeds = plugin_fetch_live_feed_net()
        day_start_timestamp, day_end_timestamp = plugin_get_today_feed_window()
        if website_feeds:
            existing_dedup_ids = ["%s|%s|%s|%s" % (
                _to_text(f.get("freq_val", "")).strip(),
                _to_text(f.get("pol_val", "")).strip(),
                _to_text(f.get("sr_val", "")).strip(),
                plugin_compact_key_text(f.get("key", "")) or _to_text(f.get("name", "")).strip(),
            ) for f in feeds]

            for w_feed in website_feeds:
                if not plugin_feed_is_in_current_window(w_feed, day_start_timestamp, day_end_timestamp):
                    continue

                dedup_id = "%s|%s|%s|%s" % (
                    _to_text(w_feed.get("freq_val", "")).strip(),
                    _to_text(w_feed.get("pol_val", "")).strip(),
                    _to_text(w_feed.get("sr_val", "")).strip(),
                    plugin_compact_key_text(w_feed.get("key", "")) or _to_text(w_feed.get("name", "")).strip(),
                )
                if dedup_id not in existing_dedup_ids:
                    feeds.append(w_feed)
                    plugin_store_runtime_feed(w_feed)
                    existing_dedup_ids.append(dedup_id)

    feeds.sort(key=lambda x: x.get('timestamp', 0), reverse=True)

    if not feeds:
        day_start_timestamp, day_end_timestamp = plugin_get_today_feed_window()
        feeds = plugin_get_runtime_feeds(day_start_timestamp, day_end_timestamp)

    return feeds


def plugin_fetch_telegram_key(current_sid, current_name, current_freq, preferred_feed=None, available_feeds=None):
    try:
        fetched_feeds = plugin_fetch_all_feeds()
        candidate_feeds = plugin_collect_candidate_feeds(preferred_feed, available_feeds, fetched_feeds)
        found_key = plugin_find_matching_feed_key(current_sid, current_name, current_freq, candidate_feeds, preferred_feed)
        if found_key:
            return found_key

        try:
            current_source = config.plugins.furybis.feed_source.value
        except Exception:
            current_source = 'both'

        found_key = None

        if current_source in ('both', 'telegram'):
            for channel in FEED_SOURCE_CHANNELS:
                if found_key:
                    break
                try:
                    url = plugin_get_feed_source_url(channel, nocache=int(time.time()))
                    req = urllib2.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                    response = urllib2.urlopen(req, timeout=5)
                    html = response.read()
                    if PY3:
                        html = html.decode('utf-8', 'ignore')
                    else:
                        html = _to_text(html)

                    messages = re.findall(r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>', html, re.IGNORECASE | re.DOTALL)
                    for msg in reversed(messages):
                        text = re.sub(r'<br\s*/?>', '\n', msg)
                        text = re.sub(r'<[^>]+>', '', text)

                        sid_match = re.search(r'SID\s*[:\-]?\s*([0-9A-Fa-f]{1,4})\b', text, re.IGNORECASE)
                        found_by_sid = False
                        if sid_match:
                            found_sid = sid_match.group(1).upper().zfill(4)
                            current_sid_clean = _to_text(current_sid).upper().zfill(4)
                            acceptable_sids = [current_sid_clean]
                            if current_sid_clean == '0001':
                                acceptable_sids.append('0002')
                            elif current_sid_clean == '0002':
                                acceptable_sids.append('0001')
                            if found_sid in acceptable_sids:
                                found_by_sid = True

                        found_by_name = False
                        if current_name and _to_text(current_name).lower() != 'unknown' and len(_to_text(current_name)) > 2:
                            if plugin_names_match(current_name, text):
                                found_by_name = True

                        found_by_freq = False
                        if _to_text(current_freq).isdigit():
                            freq_int = int(current_freq)
                            for freq_candidate in range(freq_int - 2, freq_int + 3):
                                if str(freq_candidate) in text:
                                    found_by_freq = True
                                    break

                        if found_by_sid or found_by_name or found_by_freq:
                            # Ignore the key if the feed is 4:2:2
                            if plugin_extract_feed_type(text) == '4:2:2':
                                continue
                                
                            raw_key = plugin_compact_key_text(plugin_extract_key_value(text))
                            if raw_key:
                                found_key = raw_key
                                break
                except Exception:
                    pass

        if not found_key and current_source in ('both', 'website'):
            try:
                website_feeds = plugin_fetch_live_feed_net()
                found_key = plugin_find_matching_feed_key(current_sid, current_name, current_freq, website_feeds, preferred_feed)
            except Exception:
                pass

        return found_key if found_key else None

    except Exception as e:
        return 'ERROR: ' + str(e)


# Global container reference so the process is not garbage-collected
_emu_container = None
_emu_restart_lock = None


def plugin_get_active_emu_proc_info():
    """
    Scan /proc for the real running EMU process and return its cmdline.
    Returns (comm, bin_path, extra_args) or (None, None, []).

    The scan prefers the executable behind /proc/PID/exe over cmdline[0]
    because some images start OSCam/NCam through wrappers or relative names.
    """
    best_item = None
    best_score = -1
    try:
        for pid in os.listdir('/proc'):
            if not pid.isdigit():
                continue
            try:
                comm_path = '/proc/%s/comm' % pid
                cmd_path = '/proc/%s/cmdline' % pid
                exe_link = '/proc/%s/exe' % pid

                with open(comm_path, 'r') as f:
                    comm = f.read().strip()
                normalized = plugin_normalize_emu_identifier(comm)
                if normalized not in PLUGIN_EMU_BASE_NAMES:
                    continue

                raw = b'' if PY3 else ''
                try:
                    with open(cmd_path, 'rb') as f:
                        raw = f.read()
                except Exception:
                    raw = b'' if PY3 else ''

                parts = []
                try:
                    for item in raw.split(b'\x00' if PY3 else '\x00'):
                        if not item:
                            continue
                        if PY3:
                            parts.append(item.decode('utf-8', 'ignore'))
                        else:
                            parts.append(item.decode('utf-8', 'ignore'))
                except Exception:
                    parts = []

                exe_path = ''
                try:
                    exe_path = os.path.realpath(exe_link)
                    if exe_path and not os.path.isfile(exe_path):
                        exe_path = ''
                except Exception:
                    exe_path = ''

                bin_path = ''
                if parts and os.path.isfile(parts[0]):
                    bin_path = parts[0]
                if exe_path:
                    bin_path = exe_path
                if not bin_path:
                    continue

                extra_args = parts[1:] if parts else []
                lower_path = bin_path.lower()
                score = 100
                if '/usr/softcams/' in lower_path:
                    score += 40
                elif '/usr/bin/' in lower_path or '/var/bin/' in lower_path:
                    score += 25
                if normalized in os.path.basename(lower_path):
                    score += 20
                if any(arg in ('-b', '-S') for arg in extra_args):
                    score += 10

                if score > best_score:
                    best_score = score
                    best_item = (comm, bin_path, extra_args)
            except Exception:
                pass
    except Exception:
        pass
    if best_item:
        return best_item
    return (None, None, [])


def plugin_build_direct_proc_restart_command(bin_path, extra_args):
    """
    Restart the currently running EMU directly from its real executable.

    This avoids slow/blocking cam scripts and fixes images where script start
    leaves OSCam/NCam waiting in foreground, so a manual restart was needed.
    """
    bin_path = _to_text(bin_path).strip()
    if not bin_path:
        return ''
    bin_name = os.path.basename(bin_path)
    kill_sequence = plugin_build_emu_kill_sequence(bin_name)
    quoted_bin = plugin_shell_quote(bin_path)
    quoted_args = ' '.join(plugin_shell_quote(a) for a in (extra_args or []) if _to_text(a).strip())
    cleanup = (
        "rm -rf /tmp/.oscam /tmp/.ncam /tmp/*.pid* /tmp/oscam.* "
        "/tmp/*.oscam /tmp/ncam.* /tmp/*.ncam /tmp/status.* /tmp/frozen "
        ">/dev/null 2>&1"
    )
    if quoted_args:
        start_cmd = "(ulimit -s 1024; nohup %s %s >/dev/null 2>&1 &)" % (quoted_bin, quoted_args)
    else:
        start_cmd = "(ulimit -s 1024; nohup %s >/dev/null 2>&1 &)" % quoted_bin
    start_wait = plugin_shell_short_wait(160000)
    return (
        "FURYBISS_DIRECT_RESTART=1; "
        "%s; "
        "%s; "
        "%s; "
        "%s; "
        "(sync >/dev/null 2>&1 &)"
    ) % (kill_sequence, cleanup, start_cmd, start_wait)


def plugin_shell_quote(value):
    value = _to_text(value)
    return "'" + value.replace("'", "'\"'\"'") + "'"


def plugin_shell_short_wait(microseconds=200000):
    """Tiny shell wait without falling back to a full one-second sleep."""
    try:
        microseconds = int(microseconds)
    except Exception:
        microseconds = 200000
    if microseconds < 1:
        microseconds = 1
    return "(usleep %d >/dev/null 2>&1 || true)" % microseconds



PLUGIN_EMU_BASE_NAMES = ('oscam', 'ncam', 'gcam', 'cccam', 'wicardd', 'gbox')


def plugin_normalize_emu_identifier(value):
    text = _to_text(value).strip().lower()
    if not text:
        return ''
    text = text.replace('\\', '/')
    base = os.path.basename(text).strip()
    if not base:
        base = text
    if 'none' in base and not any(token in base for token in PLUGIN_EMU_BASE_NAMES):
        return ''
    base = base.replace('softcam.', '').replace('.sh', '').replace('_cam', '')
    for token in PLUGIN_EMU_BASE_NAMES:
        if token in base:
            return token
    return base


def plugin_emu_name_has_ci(value):
    text = _to_text(value).strip().lower().replace('-', '_').replace('.', '_').replace(' ', '_')
    parts = [part for part in text.split('_') if part]
    return 'ci' in parts


def plugin_score_emu_match(candidate, emu_name):
    candidate_base = plugin_normalize_emu_identifier(candidate)
    emu_base = plugin_normalize_emu_identifier(emu_name)
    if not candidate_base or not emu_base or candidate_base != emu_base:
        return 0
    candidate_lower = _to_text(candidate).strip().lower()
    name_lower = _to_text(emu_name).strip().lower()
    stripped_name = name_lower.replace('softcam.', '').replace('.sh', '').strip()

    score = 100
    if stripped_name == candidate_base:
        score += 50
    if stripped_name in ('%s_%s' % (candidate_base, candidate_base), '%s-%s' % (candidate_base, candidate_base)):
        score += 20
    if plugin_emu_name_has_ci(name_lower) and not plugin_emu_name_has_ci(candidate_lower):
        score -= 45
    return score


def plugin_get_emu_restart_lock():
    global _emu_restart_lock
    try:
        if _emu_restart_lock is None:
            import threading
            _emu_restart_lock = threading.Lock()
        return _emu_restart_lock
    except Exception:
        return None


def plugin_build_emu_kill_sequence(extra_name=None):
    # Build a real stop sequence that kills the old softcam process every time.
    # OpenViX may run the selected softcam from /usr/softcams with names like
    # oscam-latest or ncam-emu, so kill by exact name and by /proc scan too.
    names = [
        'oscam', 'oscam-emu', 'oscam_emu', 'oscam-latest', 'oscam-stable',
        'oscam-modern', 'oscamicam', 'ncam', 'ncam-emu', 'ncam-latest',
        'gcam', 'cccam', 'CCcam', 'wicardd', 'gbox'
    ]
    extra_name = _to_text(extra_name).strip()
    if extra_name:
        base_name = os.path.basename(extra_name)
        no_ext = base_name[:-3] if base_name.lower().endswith('.sh') else base_name
        for candidate in (extra_name, base_name, no_ext, base_name.lower(), no_ext.lower()):
            candidate = _to_text(candidate).strip()
            if candidate and candidate not in names:
                names.append(candidate)

    quoted_names = ' '.join([plugin_shell_quote(name) for name in names if name])
    proc_match = '*oscam*|*OSCam*|*OSCAM*|*ncam*|*NCam*|*NCAM*|*gcam*|*GCam*|*GCAM*|*cccam*|*CCcam*|*CCCam*|*CCCAM*|*wicardd*|*gbox*|*GBox*|*GBOX*'
    proc_soft = "for c in /proc/[0-9]*/comm; do [ -r \"$c\" ] || continue; p=${c%%/comm}; p=${p##*/}; n=`cat \"$c\" 2>/dev/null`; case \"$n\" in %s) kill \"$p\" >/dev/null 2>&1;; esac; done" % proc_match
    proc_hard = "for c in /proc/[0-9]*/comm; do [ -r \"$c\" ] || continue; p=${c%%/comm}; p=${p##*/}; n=`cat \"$c\" 2>/dev/null`; case \"$n\" in %s) kill -9 \"$p\" >/dev/null 2>&1;; esac; done" % proc_match
    first_wait = plugin_shell_short_wait(250000)
    second_wait = plugin_shell_short_wait(180000)
    return (
        "for p in %s; do killall \"$p\" >/dev/null 2>&1; done; "
        "%s; "
        "%s; "
        "for p in %s; do killall -9 \"$p\" >/dev/null 2>&1; done; "
        "%s; "
        "%s"
    ) % (quoted_names, proc_soft, first_wait, quoted_names, proc_hard, second_wait)


def plugin_build_emu_script_restart_command(script_path, bin_name):
    script_path = plugin_shell_quote(script_path)
    kill_sequence = plugin_build_emu_kill_sequence(bin_name)
    stop_wait = plugin_shell_short_wait(220000)
    start_wait = plugin_shell_short_wait(300000)
    return (
        "%s stop >/dev/null 2>&1; "
        "%s; "
        "%s; "
        "%s start >/dev/null 2>&1; "
        "%s; "
        "(sync >/dev/null 2>&1 &)"
    ) % (script_path, stop_wait, kill_sequence, script_path, start_wait)


def plugin_build_emu_binary_restart_command(process_name, binary_path):
    kill_sequence = plugin_build_emu_kill_sequence(process_name or binary_path)
    quoted_binary = plugin_shell_quote(binary_path)
    start_wait = plugin_shell_short_wait(300000)
    return (
        "%s; "
        "(nohup %s >/dev/null 2>&1 || %s >/dev/null 2>&1) & "
        "%s; "
        "(sync >/dev/null 2>&1 &)"
    ) % (kill_sequence, quoted_binary, quoted_binary, start_wait)


def plugin_build_openvix_softcam_restart_command(process_name, binary_path):
    name = os.path.basename(_to_text(process_name or binary_path).strip())
    lower = name.lower()
    quoted_binary = plugin_shell_quote(binary_path)
    kill_sequence = plugin_build_emu_kill_sequence(name or binary_path)
    cleanup = "rm -rf /tmp/.oscam /tmp/.ncam /tmp/*.pid* /tmp/oscam.* /tmp/*.oscam /tmp/ncam.* /tmp/*.ncam /tmp/status.* /tmp/frozen >/dev/null 2>&1"
    stop_wait = plugin_shell_short_wait(220000)
    start_wait = plugin_shell_short_wait(450000)

    if lower.endswith('.sh'):
        return (
            "%s stop >/dev/null 2>&1; "
            "%s; "
            "%s; "
            "%s; "
            "%s start >/dev/null 2>&1; "
            "%s; "
            "(sync >/dev/null 2>&1 &)"
        ) % (quoted_binary, stop_wait, kill_sequence, cleanup, quoted_binary, start_wait)

    if lower.startswith('oscam') or lower.startswith('ncam'):
        start_command = "(ulimit -s 1024; %s -b) >/dev/null 2>&1" % quoted_binary
    elif lower.startswith('gbox'):
        start_command = "(ulimit -s 1024; %s >/dev/null 2>&1 &) ; %s; [ -x /usr/bin/gbox ] && start-stop-daemon --start --quiet --background --exec /usr/bin/gbox >/dev/null 2>&1 || true" % (quoted_binary, start_wait)
    else:
        start_command = "(ulimit -s 1024; nohup %s >/dev/null 2>&1 &)" % quoted_binary

    return (
        "%s; "
        "%s; "
        "%s; "
        "%s; "
        "(sync >/dev/null 2>&1 &)"
    ) % (kill_sequence, cleanup, start_command, start_wait)


def plugin_add_emu_candidate(candidates, value):
    value = _to_text(value).strip()
    if not value:
        return
    value = value.replace('\r', '\n').replace(',', '\n').replace(';', '\n')
    for part in value.split('\n'):
        part = _to_text(part).strip().strip('[](){}').strip('"\'')
        if not part:
            continue
        base = os.path.basename(part).strip()
        if not base:
            continue
        variants = [base, base.replace('softcam.', ''), base.replace('.sh', '')]
        normalized_base = plugin_normalize_emu_identifier(base)
        if normalized_base:
            variants.append(normalized_base)
        for item in variants:
            item = _to_text(item).strip().lower()
            if item and item != 'none' and item not in candidates:
                candidates.append(item)


def plugin_get_openvix_softcam_candidates():
    candidates = []
    try:
        scm = getattr(config, 'softcammanager', None)
        value_obj = getattr(getattr(scm, 'softcams_autostart', None), 'value', '')
        if isinstance(value_obj, (list, tuple)):
            for item in value_obj:
                plugin_add_emu_candidate(candidates, item)
        else:
            plugin_add_emu_candidate(candidates, value_obj)
    except Exception:
        pass

    for path in ('/tmp/SoftcamsScriptsRunning', '/etc/SoftcamsAutostart'):
        try:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    plugin_add_emu_candidate(candidates, f.read())
        except Exception:
            pass

    try:
        if os.path.exists('/etc/enigma2/settings'):
            with open('/etc/enigma2/settings', 'r') as f:
                for line in f:
                    if line.startswith('config.softcammanager.softcams_autostart='):
                        plugin_add_emu_candidate(candidates, line.split('=', 1)[1])
                    elif line.startswith('config.misc.softcams='):
                        plugin_add_emu_candidate(candidates, line.split('=', 1)[1])
    except Exception:
        pass

    try:
        misc_section = getattr(config, 'misc', None)
        softcams_value = getattr(getattr(misc_section, 'softcams', None), 'value', '')
        plugin_add_emu_candidate(candidates, softcams_value)
    except Exception:
        pass

    return candidates


def plugin_stop_current_service_for_emu():
    oldref = None
    try:
        nav = getattr(NavigationInstance, 'instance', None)
        if nav:
            try:
                oldref = nav.getCurrentlyPlayingServiceOrGroup()
            except Exception:
                oldref = None
            try:
                try:
                    from twisted.internet import reactor
                    reactor.callFromThread(nav.stopService)
                except Exception:
                    nav.stopService()
            except Exception:
                pass
    except Exception:
        oldref = None
    return oldref


def plugin_resume_current_service_after_emu(oldref):
    try:
        nav = getattr(NavigationInstance, 'instance', None)
        if nav and oldref:
            try:
                try:
                    from twisted.internet import reactor
                    reactor.callFromThread(nav.playService, oldref, adjust=False)
                except TypeError:
                    try:
                        from twisted.internet import reactor
                        reactor.callFromThread(nav.playService, oldref)
                    except Exception:
                        nav.playService(oldref)
                except Exception:
                    try:
                        nav.playService(oldref, adjust=False)
                    except TypeError:
                        nav.playService(oldref)
            except Exception:
                pass
    except Exception:
        pass


def plugin_run_emu_restart_worker(command_str, lock=None, locked=False):
    oldref = None
    try:
        try:
            os.system("sync >/dev/null 2>&1 &")
        except Exception:
            pass

        is_direct_restart = 'FURYBISS_DIRECT_RESTART=1' in command_str
        needs_service_restart = (
            not is_direct_restart and
            ('/usr/softcams/' in command_str or '/usr/script/' in command_str)
        )
        if needs_service_restart:
            oldref = plugin_stop_current_service_for_emu()
            try:
                time.sleep(0.15)
            except Exception:
                pass

        try:
            subprocess.call(command_str, shell=True)
        except Exception:
            try:
                os.system(command_str)
            except Exception:
                pass

        try:
            if oldref:
                time.sleep(0.35)
                plugin_resume_current_service_after_emu(oldref)
        except Exception:
            pass
    finally:
        if locked and lock is not None:
            try:
                lock.release()
            except Exception:
                pass


def plugin_start_emu_restart_thread(command_str):
    command_str = _to_text(command_str).strip()
    if not command_str:
        return False

    lock = plugin_get_emu_restart_lock()
    locked = False
    try:
        if lock is not None:
            try:
                locked = lock.acquire(False)
                if not locked:
                    return True
            except TypeError:
                lock.acquire()
                locked = True

        import threading
        worker = threading.Thread(target=plugin_run_emu_restart_worker, args=(command_str, lock, locked))
        try:
            worker.setDaemon(True)
        except Exception:
            pass
        worker.start()
        return True
    except Exception:
        if locked and lock is not None:
            try:
                lock.release()
            except Exception:
                pass
        try:
            subprocess.Popen(command_str, shell=True)
            return True
        except Exception:
            try:
                return os.system(command_str) == 0
            except Exception:
                return False


def plugin_get_emus():
    emus_dict = {}
    try:
        # Real restart commands: stop the softcam, force-kill old processes,
        # wait long enough for the process table to clear, then start again.
        script_paths = [
            "/usr/script",
            "/usr/camscript",
            "/etc/rc.d",
            "/etc/init.d"
        ]
        
        script_emus = []

        # OpenViX SoftcamManager uses /usr/softcams and starts OSCam/NCam with -b.
        openvix_dir = "/usr/softcams"
        if os.path.isdir(openvix_dir):
            for name in os.listdir(openvix_dir):
                lower = name.lower()
                if "none" in lower or lower.endswith(".bak") or lower.endswith(".pid"):
                    continue
                if lower.endswith('.sh') or "oscam" in lower or "ncam" in lower or "gcam" in lower or "cccam" in lower or "wicardd" in lower or "gbox" in lower:
                    full_path = os.path.join(openvix_dir, name)
                    if os.path.isfile(full_path) and os.access(full_path, os.X_OK):
                        display_name = name.replace(".sh", "").replace("softcam.", "").replace("_cam", "")
                        if display_name not in emus_dict:
                            emus_dict[display_name] = plugin_build_openvix_softcam_restart_command(name, full_path)
                            script_emus.append(display_name.lower())
                            script_emus.append(name.lower())

        for script_dir in script_paths:
            if os.path.isdir(script_dir):
                for name in os.listdir(script_dir):
                    lower = name.lower()
                    if "none" in lower or lower.endswith(".bak") or lower.endswith(".pid") or "volatiles" in lower or "bootup" in lower: continue
                    if "cam" in lower or "oscam" in lower or "ncam" in lower or "gbox" in lower or "wicardd" in lower:
                        full_path = os.path.join(script_dir, name)
                        if os.path.isfile(full_path) and os.access(full_path, os.X_OK):
                            display_name = name.replace(".sh", "").replace("softcam.", "").replace("_cam", "")
                            bin_name = display_name
                            if "oscam" in lower: bin_name = "oscam"
                            elif "ncam" in lower: bin_name = "ncam"
                            elif "gcam" in lower: bin_name = "gcam"
                            elif "cccam" in lower: bin_name = "cccam"
                            elif "wicardd" in lower: bin_name = "wicardd"
                            elif "gbox" in lower: bin_name = "gbox"
                            
                            if display_name not in emus_dict:
                                emus_dict[display_name] = plugin_build_emu_script_restart_command(full_path, bin_name)
                                script_emus.append(display_name.lower())

        bin_dirs = ["/usr/bin", "/usr/bin/cam", "/usr/bin/cams", "/usr/bin/emu", "/var/bin", "/var/emu"]
        for b_dir in bin_dirs:
            if os.path.isdir(b_dir):
                for name in os.listdir(b_dir):
                    lower = name.lower()
                    if lower.endswith(".sh") or lower.endswith(".bak"): continue
                    if "oscam" in lower or "ncam" in lower or "gcam" in lower or "cccam" in lower or "wicardd" in lower or "gbox" in lower:
                        is_duplicate = False
                        if lower not in PLUGIN_EMU_BASE_NAMES:
                            for s_name in script_emus:
                                if lower in s_name or s_name in lower:
                                    is_duplicate = True
                                    break
                        if not is_duplicate:
                            full_path = os.path.join(b_dir, name)
                            if os.path.isfile(full_path) and os.access(full_path, os.X_OK):
                                if name not in emus_dict:
                                    emus_dict[name] = plugin_build_emu_binary_restart_command(name, full_path)

        specific_found = any(x for x in emus_dict.keys() if "oscam" in x.lower() or "ncam" in x.lower() or "gcam" in x.lower() or "cccam" in x.lower() or "wicardd" in x.lower() or "gbox" in x.lower())
        if specific_found:
            for generic in ["cams", "softcam", "cam", "softcams"]:
                if generic in emus_dict: del emus_dict[generic]
    except: pass
    return emus_dict

def plugin_restart_active_emu():
    global _emu_container

    # Fast path: restart the process that is actually running now.
    # This avoids slow/blocking image scripts and removes the need for a manual restart
    # on images that launch OSCam/NCam in foreground mode.
    try:
        comm_p, bin_path_p, extra_args_p = plugin_get_active_emu_proc_info()
        if comm_p and bin_path_p:
            direct_cmd = plugin_build_direct_proc_restart_command(bin_path_p, extra_args_p)
            if direct_cmd:
                try:
                    _emu_container = None
                except Exception:
                    pass
                return plugin_start_emu_restart_thread(direct_cmd)
    except Exception:
        pass

    emus = plugin_get_emus()
    if not emus:
        return False

    import os
    active_bin = None
    try:
        for pid in os.listdir('/proc'):
            if pid.isdigit():
                try:
                    with open(os.path.join('/proc', pid, 'comm'), 'r') as f:
                        comm = f.read().strip()
                        comm_lower = comm.lower()
                        if any(x in comm_lower for x in ["oscam", "ncam", "gcam", "wicardd", "cccam", "gbox"]):
                            active_bin = comm
                            break
                except Exception:
                    pass
    except Exception:
        pass

    bh_cam = None
    active_candidates = []
    try:
        if os.path.exists("/etc/CurrentBhCamName"):
            with open("/etc/CurrentBhCamName", "r") as f:
                bh_cam = f.read().strip().lower()
        elif os.path.exists("/etc/init.d/softcam"):
            bh_cam = os.path.realpath("/etc/init.d/softcam").split('/')[-1].lower()
        if bh_cam:
            plugin_add_emu_candidate(active_candidates, bh_cam)
    except Exception:
        pass

    try:
        for pid in os.listdir('/proc'):
            if pid.isdigit():
                try:
                    exe_path = os.path.realpath(os.path.join('/proc', pid, 'exe'))
                    if exe_path and '/usr/softcams/' in exe_path:
                        plugin_add_emu_candidate(active_candidates, os.path.basename(exe_path))
                except Exception:
                    pass
        if active_bin:
            plugin_add_emu_candidate(active_candidates, active_bin)
    except Exception:
        pass

    try:
        for item in plugin_get_openvix_softcam_candidates():
            plugin_add_emu_candidate(active_candidates, item)
    except Exception:
        pass

    cmd_to_run = None

    best_score = 0
    for candidate in active_candidates:
        for name, cmd in emus.items():
            score = plugin_score_emu_match(candidate, name)
            if score > best_score:
                best_score = score
                cmd_to_run = cmd

    if not cmd_to_run and active_bin:
        for name, cmd in emus.items():
            score = plugin_score_emu_match(active_bin, name)
            if score > best_score:
                best_score = score
                cmd_to_run = cmd

    if not cmd_to_run:
        for name, cmd in emus.items():
            lower_name = name.lower()
            if "ci" not in lower_name and ("oscam" in lower_name or "ncam" in lower_name):
                cmd_to_run = cmd
                break

    if not cmd_to_run:
        cmd_to_run = emus[sorted(emus.keys())[0]]

    if not cmd_to_run:
        return False

    # Remove old background wrappers if they exist in saved/generated settings.
    cmd_to_run = _to_text(cmd_to_run).strip()
    if cmd_to_run.startswith("(") and cmd_to_run.endswith(") &"):
        cmd_to_run = cmd_to_run[1:-3].strip()

    # Last fallback for old script-based images: if the selected command is a
    # /usr/script cam script, still try the direct /proc restart before running it.
    try:
        is_openvix = os.path.isdir('/usr/softcams')
        cmd_str_lower = cmd_to_run.lower()
        uses_usr_script = '/usr/script/' in cmd_str_lower
        if not is_openvix and uses_usr_script:
            comm_p, bin_path_p, extra_args_p = plugin_get_active_emu_proc_info()
            if comm_p and bin_path_p:
                direct_cmd = plugin_build_direct_proc_restart_command(bin_path_p, extra_args_p)
                if direct_cmd:
                    cmd_to_run = direct_cmd
    except Exception:
        pass

    try:
        _emu_container = None
    except Exception:
        pass

    return plugin_start_emu_restart_thread(cmd_to_run)


def plugin_get_local_day_key(timestamp=None):
    if timestamp is None:
        timestamp = plugin_get_utc_time()   # NTP-corrected, falls back to device clock
    try:
        # Use UTC so we do not depend on the receiver clock
        # which can change when switching from one satellite to another
        return time.strftime('%Y-%m-%d', time.gmtime(int(timestamp)))
    except:
        return ''


def plugin_get_local_datetime_text(timestamp=None):
    if timestamp is None:
        timestamp = plugin_get_utc_time()   # NTP-corrected, falls back to device clock
    try:
        # Use UTC for compatibility with plugin_get_local_day_key
        return time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(int(timestamp)))
    except:
        return ''


def plugin_is_furybiss_managed_line(line):
    line_text = _to_text(line).strip()
    if not line_text or line_text.startswith(';'):
        return False
    parts = line_text.split(';', 1)
    main_tokens = parts[0].strip().split()
    if len(main_tokens) < 4 or main_tokens[0].upper() != 'F':
        return False
    comment = parts[1].strip().lower() if len(parts) > 1 else ''
    return 'added by furybiss' in comment


def plugin_extract_furybiss_day_from_line(line):
    line_text = _to_text(line).strip()
    if not plugin_is_furybiss_managed_line(line_text):
        return ''
    match = re.search(r'Added by FuryBiss on (\d{4}-\d{2}-\d{2})(?:\s+\d{2}:\d{2}:\d{2})?', line_text, re.IGNORECASE)
    if match:
        return match.group(1)
    return ''


def plugin_stamp_biss_line(line, timestamp=None):
    line_text = _to_text(line).strip()
    if not line_text:
        return line_text

    parts = line_text.split(';', 1)
    main_part = parts[0].strip()
    comment_part = parts[1].strip() if len(parts) > 1 else ''
    main_tokens = main_part.split()
    if len(main_tokens) < 4 or main_tokens[0].upper() != 'F':
        return line_text

    stamp_text = plugin_get_local_datetime_text(timestamp)
    if not stamp_text:
        return line_text

    extra_comment = comment_part
    extra_comment = re.sub(r'(?i)^added by furybiss(?:\s+on\s+\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}:\d{2})?)?', '', extra_comment).strip()
    extra_comment = re.sub(r'^for\s+', '', extra_comment, flags=re.IGNORECASE).strip()
    extra_comment = re.sub(r'^\|\s*', '', extra_comment).strip()

    stamped_comment = 'Added by FuryBiss on %s' % stamp_text
    if extra_comment:
        stamped_comment += ' | %s' % extra_comment

    return '%s ; %s' % (main_part, stamped_comment)


def plugin_prepare_biss_lines(lines, timestamp=None):
    prepared_lines = []
    for line in (lines or []):
        line_text = plugin_stamp_biss_line(line, timestamp)
        if line_text:
            prepared_lines.append(line_text)
    return prepared_lines


def plugin_get_key_cleanup_paths():
    paths = []
    try:
        for path in get_storage_write_paths() or []:
            if path and path not in paths:
                paths.append(path)
    except:
        pass
    try:
        current_path = get_storage_path()
        if current_path and current_path not in paths:
            paths.append(current_path)
    except:
        pass
    return paths


def plugin_cleanup_old_furybiss_keys_in_file(path, today_key=None):
    if not path or not os.path.exists(path):
        return 0

    try:
        with open(path, 'r') as f:
            original_lines = f.readlines()
    except:
        return 0

    if not today_key:
        today_key = plugin_get_local_day_key()

    fury_lines_today = []
    fury_lines_old = []
    other_lines = []

    # Separate plugin-managed keys from other manually added keys
    # and distinguish between current-day keys and previous-day keys
    for raw_line in original_lines:
        stripped_line = _to_text(raw_line).strip()
        if stripped_line and plugin_is_furybiss_managed_line(stripped_line):
            line_day = plugin_extract_furybiss_day_from_line(stripped_line)
            if today_key and line_day and line_day < today_key:
                # Key from a previous day -> remove it
                fury_lines_old.append(raw_line if raw_line.endswith('\n') else raw_line + '\n')
            else:
                # Current-day key or key without a date -> keep it
                fury_lines_today.append(raw_line if raw_line.endswith('\n') else raw_line + '\n')
        else:
            other_lines.append(raw_line if raw_line.endswith('\n') else raw_line + '\n')

    removed_count = len(fury_lines_old)

    if removed_count > 0:
        final_lines = other_lines + fury_lines_today
        try:
            with open(path, 'w') as f:
                f.writelines(final_lines)
            os.system('sync')
        except:
            return 0

    return removed_count


def plugin_run_daily_key_cleanup(today_key=None):
    global _runtime_feed_cache, global_opened_feeds
    if today_key is None:
        today_key = plugin_get_local_day_key()

    # Clear feed cache from memory and disk when the day changes
    try:
        saved_day = ''
        if os.path.exists(_FEED_DISK_CACHE_FILE):
            with open(_FEED_DISK_CACHE_FILE, 'r') as f:
                data = json.load(f)
            saved_day = data.get('day_key', '')
        if saved_day and saved_day != today_key:
            _runtime_feed_cache = []
            plugin_clear_feed_disk_cache()
    except Exception:
        pass

    # Clear opened feeds (dots) from memory and disk when the day changes
    try:
        opened_day = ''
        if os.path.exists(_OPENED_FEEDS_FILE):
            with open(_OPENED_FEEDS_FILE, 'r') as f:
                opened_data = json.load(f)
            opened_day = opened_data.get('day_key', '')
        if opened_day and opened_day != today_key:
            global_opened_feeds = {}
            try:
                os.remove(_OPENED_FEEDS_FILE)
            except Exception:
                pass
    except Exception:
        pass

    total_removed = 0
    visited_paths = {}
    for path in plugin_get_key_cleanup_paths():
        if not path or path in visited_paths:
            continue
        visited_paths[path] = True
        total_removed += plugin_cleanup_old_furybiss_keys_in_file(path, today_key)

    if total_removed > 0:
        try:
            plugin_restart_active_emu()
        except:
            pass

    return total_removed


def plugin_clear_saved_proxy_settings():
    """Clear the saved proxy URL and remove its lines from Enigma2 settings."""
    removed_lines = 0

    try:
        config.plugins.furybiss.proxy_url.value = ""
        config.plugins.furybiss.proxy_url.save()
    except Exception:
        pass

    try:
        config.plugins.furybis.use_proxy.value = False
        config.plugins.furybis.use_proxy.save()
    except Exception:
        pass

    try:
        if configfile:
            configfile.save()
    except Exception:
        pass

    settings_path = "/etc/enigma2/settings"
    prefixes = (
        "config.plugins.furybiss.proxy_url=",
        "config.plugins.furybis.proxy_url=",
        "config.plugins.furybis.use_proxy=",
    )

    try:
        if os.path.exists(settings_path):
            with open(settings_path, "r") as f:
                lines = f.readlines()

            kept_lines = []
            for line in lines:
                stripped = line.strip()
                if any(stripped.startswith(prefix) for prefix in prefixes):
                    removed_lines += 1
                    continue
                kept_lines.append(line)

            if removed_lines > 0:
                with open(settings_path, "w") as f:
                    f.writelines(kept_lines)
    except Exception:
        pass

    try:
        os.system("sync")
    except Exception:
        pass

    return removed_lines


def plugin_clear_all_furybiss_keys():
    """Remove every SoftCam key line created by FuryBiss."""
    total_removed = 0
    modified_paths = []
    visited_paths = {}

    for path in plugin_get_key_cleanup_paths():
        if not path or path in visited_paths or not os.path.exists(path):
            continue
        visited_paths[path] = True

        try:
            with open(path, "r") as f:
                original_lines = f.readlines()
        except Exception:
            continue

        kept_lines = []
        removed_here = 0
        for raw_line in original_lines:
            line_text = _to_text(raw_line).strip()
            if line_text and plugin_is_furybiss_managed_line(line_text):
                removed_here += 1
                continue
            kept_lines.append(raw_line if raw_line.endswith("\n") else raw_line + "\n")

        if removed_here > 0:
            try:
                with open(path, "w") as f:
                    f.writelines(kept_lines)
                total_removed += removed_here
                modified_paths.append(path)
            except Exception:
                pass

    try:
        os.system("sync >/dev/null 2>&1 &")
    except Exception:
        pass

    if total_removed > 0:
        try:
            plugin_restart_active_emu()
        except Exception:
            pass

    return total_removed, modified_paths


def plugin_clear_feeds_cache_file():
    """Clear the runtime feed cache and remove the daily feed cache file."""
    global _runtime_feed_cache
    removed_file = False
    _runtime_feed_cache = []

    try:
        if os.path.exists(_FEED_DISK_CACHE_FILE):
            os.remove(_FEED_DISK_CACHE_FILE)
            removed_file = True
    except Exception:
        removed_file = False

    try:
        os.system("sync")
    except Exception:
        pass

    return removed_file

def plugin_append_key_lines(path, lines):
    lines = plugin_prepare_biss_lines(lines)
    existing_content = []
    if os.path.exists(path):
        try:
            with open(path, 'r') as f: existing_content = f.readlines()
        except: return
    new_prefixes = []
    for line in lines:
        parts = line.strip().split()
        if len(parts) >= 3 and parts[0].upper() == 'F': new_prefixes.append(" ".join(parts[:3]).upper())
    final_lines = []
    for line in existing_content:
        line_strip = line.strip()
        if not line_strip: continue
        parts = line_strip.split()
        is_replacement = False
        if len(parts) >= 3 and parts[0].upper() == 'F':
            prefix = " ".join(parts[:3]).upper()
            if prefix in new_prefixes: is_replacement = True
        
        # Add the old line only once if there is no new key for the same channel
        if not is_replacement: final_lines.append(line_strip + "\n")
        
    for line in lines:
        # Add the new key line only once
        if line.strip(): final_lines.append(line.strip() + "\n")
        
    try:
        with open(path, 'w') as f: f.writelines(final_lines)
        os.system("sync")
    except: pass


def plugin_extract_scan_data(feed):
    if not isinstance(feed, dict):
        return None

    freq = _to_text(feed.get('freq_val', '')).strip()
    pol = _to_text(feed.get('pol_val', '')).strip().upper()
    sr = _to_text(feed.get('sr_val', '')).strip()
    sat_str = _to_text(feed.get('sat', '')).strip()
    full_text = _to_text(feed.get('full_text', ''))

    if not freq or not sr:
        return None

    try:
        freq_int = int(float(freq))
        sr_int = int(float(sr))
    except:
        return None

    orb_pos = None
    sat_match = re.search(r'(\d{1,3}(?:\.\d+)?)\s*[°]?\s*([EWew])', sat_str)
    if sat_match:
        try:
            deg = float(sat_match.group(1))
            direction = sat_match.group(2).upper()
            calc_pos = int(round(deg * 10))
            if direction == 'W':
                calc_pos = 3600 - calc_pos
            orb_pos = calc_pos
        except:
            orb_pos = None

    pol_idx = 0 if pol == 'H' else 1
    
    # ==========================================
    # Start of adjustment: detect the broadcast system automatically
    # ==========================================
    system_val = 0      # Default value 0 means DVB-S
    modulation_val = 1  # Default value 1 means QPSK
    
    # Convert text to uppercase for more accurate matching
    full_text_upper = full_text.upper()
    
    if "DVB-S2" in full_text_upper or "8PSK" in full_text_upper or "16APSK" in full_text_upper:
        system_val = 1  # Value 1 means DVB-S2
        
        if "8PSK" in full_text_upper:
            modulation_val = 2 # Value 2 means 8PSK
        elif "16APSK" in full_text_upper:
            modulation_val = 3 # Value 3 means 16APSK
        elif "QPSK" in full_text_upper:
            modulation_val = 1 # QPSK in DVB-S2
    # ==========================================
    # End of adjustment
    # ==========================================

    return {
        'frequency': freq_int,
        'symbolrate': sr_int,
        'polarization': pol_idx,
        'orb_pos': orb_pos,
        'system': system_val,
        'modulation': modulation_val,
        'sat_text': sat_str,
        'freq_text': '%s %s %s' % (freq_int, pol or '?', sr_int),
    }


def plugin_set_config_value(element, value):
    try:
        if hasattr(element, 'setValue'):
            element.setValue(value)
            return True
    except:
        pass
    try:
        element.value = value
        return True
    except:
        return False


def plugin_set_choice_value(element, desired_values=None, desired_texts=None):
    desired_values = list(desired_values or [])
    desired_texts = [_to_text(item).lower() for item in (desired_texts or []) if _to_text(item)]

    try:
        choices = getattr(element, 'choices', None)
    except:
        choices = None

    try:
        iterable = list(choices) if choices is not None else []
    except:
        iterable = []

    for item in iterable:
        if isinstance(item, tuple):
            key = item[0]
            label = _to_text(item[1]).lower()
        else:
            key = item
            label = _to_text(item).lower()
        key_text = _to_text(key).lower()

        for wanted in desired_values:
            wanted_text = _to_text(wanted).lower()
            if key == wanted or key_text == wanted_text:
                return plugin_set_config_value(element, key)

        for wanted_text in desired_texts:
            if wanted_text and (wanted_text == key_text or wanted_text in label):
                return plugin_set_config_value(element, key)

    for wanted in desired_values:
        if plugin_set_config_value(element, wanted):
            return True
    return False


def plugin_set_first_attr_value(containers, attr_names, value):
    for container in containers:
        if container is None:
            continue
        for attr_name in attr_names:
            if hasattr(container, attr_name):
                element = getattr(container, attr_name)
                if plugin_set_config_value(element, value):
                    return True
    return False


def plugin_set_first_attr_choice(containers, attr_names, desired_values=None, desired_texts=None):
    for container in containers:
        if container is None:
            continue
        for attr_name in attr_names:
            if hasattr(container, attr_name):
                element = getattr(container, attr_name)
                if plugin_set_choice_value(element, desired_values, desired_texts):
                    return True
    return False


def plugin_find_satellite_match(screen, orb_pos):
    if orb_pos is None:
        return (None, None, None)

    try:
        if hasattr(screen, 'updateSatList'):
            screen.updateSatList()
    except:
        pass

    sat_lists = getattr(screen, 'satList', []) or []
    sat_selections = getattr(screen, 'scan_satselection', []) or []
    max_len = min(len(sat_lists), len(sat_selections))

    for tuner_index in range(max_len):
        sat_list = sat_lists[tuner_index] or []
        for sat_index in range(len(sat_list)):
            sat_item = sat_list[sat_index]
            try:
                sat_pos = int(sat_item[0])
            except:
                try:
                    sat_pos = int(sat_item)
                except:
                    continue
            if abs(sat_pos - int(orb_pos)) <= 5:
                return (tuner_index, sat_index, sat_pos)

    return (None, None, None)


def plugin_apply_satellite_selection(selection, sat_index, sat_value):
    changed = False
    if selection is None:
        return changed

    if sat_value is not None:
        if plugin_set_choice_value(selection, [sat_value, str(sat_value)], [str(sat_value)]):
            changed = True

    if hasattr(selection, 'setIndex'):
        try:
            selection.setIndex(int(sat_index))
            changed = True
        except:
            pass

    if hasattr(selection, 'index'):
        try:
            selection.index = int(sat_index)
            changed = True
        except:
            pass

    return changed


def plugin_refresh_scan_screen(screen):
    for method_name in ('createSetup', 'newConfig', 'updateStatus'):
        if hasattr(screen, method_name):
            try:
                getattr(screen, method_name)()
            except:
                pass


def plugin_get_scan_config_entries(screen):
    try:
        config_widget = screen["config"]
    except:
        return []

    try:
        entries = list(getattr(config_widget, 'list', []) or [])
        if entries:
            return entries
    except:
        pass

    for method_name in ('getList',):
        try:
            getter = getattr(config_widget, method_name, None)
            if getter is None:
                continue
            entries = list(getter() or [])
            if entries:
                return entries
        except:
            pass
    return []


def plugin_find_config_entry(screen, label_patterns):
    patterns = []
    for item in (label_patterns or []):
        item_text = _to_text(item).strip().lower()
        if item_text:
            patterns.append(item_text)
    if not patterns:
        return None

    for entry in plugin_get_scan_config_entries(screen):
        try:
            label = _to_text(entry[0]).strip().lower()
            element = entry[1]
        except:
            continue

        for pattern in patterns:
            exact = pattern.startswith('=')
            wanted = pattern[1:] if exact else pattern
            if not wanted:
                continue
            if exact:
                if label == wanted:
                    return element
            else:
                if wanted in label:
                    return element
    return None


def plugin_set_config_value_by_label(screen, label_patterns, value):
    element = plugin_find_config_entry(screen, label_patterns)
    if element is None:
        return False
    return plugin_set_config_value(element, value)


def plugin_set_config_choice_by_label(screen, label_patterns, desired_values=None, desired_texts=None):
    element = plugin_find_config_entry(screen, label_patterns)
    if element is None:
        return False
    return plugin_set_choice_value(element, desired_values, desired_texts)


def plugin_find_config_entry_info(screen, label_patterns):
    patterns = []
    for item in (label_patterns or []):
        item_text = _to_text(item).strip().lower()
        if item_text:
            patterns.append(item_text)
    if not patterns:
        return None

    entries = plugin_get_scan_config_entries(screen)
    for index in range(len(entries)):
        entry = entries[index]
        try:
            label = _to_text(entry[0]).strip().lower()
            element = entry[1]
        except:
            continue

        for pattern in patterns:
            exact = pattern.startswith('=')
            wanted = pattern[1:] if exact else pattern
            if not wanted:
                continue
            if exact:
                matched = (label == wanted)
            else:
                matched = (wanted in label)
            if matched:
                return (index, element, entry)
    return None


def plugin_trigger_config_rebuild(screen, label_patterns):
    info = plugin_find_config_entry_info(screen, label_patterns)
    if info is None:
        return False

    config_widget = None
    try:
        config_widget = screen['config']
    except:
        config_widget = None

    old_index = None
    try:
        if config_widget is not None and hasattr(config_widget, 'getCurrentIndex'):
            old_index = config_widget.getCurrentIndex()
    except:
        old_index = None

    try:
        if config_widget is not None:
            if hasattr(config_widget, 'setCurrentIndex'):
                config_widget.setCurrentIndex(info[0])
            elif hasattr(config_widget, 'instance') and config_widget.instance is not None:
                config_widget.instance.moveSelectionTo(info[0])
    except:
        pass

    triggered = False
    try:
        if hasattr(screen, 'newConfig'):
            screen.newConfig()
            triggered = True
        elif hasattr(screen, 'entryChanged'):
            screen.entryChanged()
            triggered = True
    except:
        pass

    try:
        if config_widget is not None:
            if old_index is not None and hasattr(config_widget, 'setCurrentIndex'):
                config_widget.setCurrentIndex(old_index)
            elif old_index is not None and hasattr(config_widget, 'instance') and config_widget.instance is not None:
                config_widget.instance.moveSelectionTo(old_index)
            if hasattr(config_widget, 'invalidateCurrent'):
                config_widget.invalidateCurrent()
    except:
        pass

    return triggered


_PLUGIN_FORCE_SATFINDER_MANUAL_MODE = False


def plugin_patch_satfinder_class(screen_class):
    if screen_class is None or getattr(screen_class, '_fury_manual_satfinder_patch', False):
        return False

    original_createConfig = getattr(screen_class, 'createConfig', None)
    original_createSetup = getattr(screen_class, 'createSetup', None)

    if not callable(original_createConfig) or not callable(original_createSetup):
        return False

    def _force_manual_mode(instance):
        changed = False
        try:
            if hasattr(instance, 'tuning_type'):
                try:
                    instance.tuning_type.default = 'single_transponder'
                except:
                    pass
                if plugin_set_choice_value(instance.tuning_type, ['single_transponder'], ['user defined transponder', 'single transponder', 'manual', 'single']):
                    changed = True
        except:
            pass

        try:
            if hasattr(instance, 'scan_type'):
                if plugin_set_choice_value(instance.scan_type, ['single_transponder'], ['user defined transponder', 'single transponder', 'manual', 'single']):
                    changed = True
        except:
            pass
        return changed

    def patched_createConfig(self, *args, **kwargs):
        result = original_createConfig(self, *args, **kwargs)
        if globals().get('_PLUGIN_FORCE_SATFINDER_MANUAL_MODE'):
            try:
                _force_manual_mode(self)
            except:
                pass
        return result

    def patched_createSetup(self, *args, **kwargs):
        if globals().get('_PLUGIN_FORCE_SATFINDER_MANUAL_MODE'):
            try:
                _force_manual_mode(self)
            except:
                pass

        result = original_createSetup(self, *args, **kwargs)

        if globals().get('_PLUGIN_FORCE_SATFINDER_MANUAL_MODE'):
            try:
                forced = _force_manual_mode(self)
                current_value = None
                try:
                    current_value = getattr(getattr(self, 'tuning_type', None), 'value', None)
                except:
                    current_value = None
                if (forced or current_value != 'single_transponder') and not getattr(self, '_fury_manual_setup_rebuild_done', False):
                    self._fury_manual_setup_rebuild_done = True
                    result = original_createSetup(self, *args, **kwargs)
            except:
                pass

        return result

    screen_class.createConfig = patched_createConfig
    screen_class.createSetup = patched_createSetup
    screen_class._fury_manual_satfinder_patch = True
    return True


def plugin_apply_scan_data_to_screen(screen, scan_data):
    if screen is None or not scan_data:
        return False

    applied = False
    layout_changed = False
    tune_changed = False
    dvb_changed = False

    # OpenBH Satfinder uses DVB_type + tuning_type instead of scan_type.
    if plugin_set_first_attr_choice([screen], ('DVB_type', 'dvb_type', 'scan_dvb_type', 'nim_type'), ['DVB-S', 'dvb-s'], ['dvb-s', 'satellite']):
        applied = True
        layout_changed = True
        dvb_changed = True
    elif plugin_set_config_choice_by_label(screen, ('=dvb type',), ['DVB-S', 'dvb-s'], ['dvb-s', 'satellite']):
        applied = True
        layout_changed = True
        dvb_changed = True

    if dvb_changed:
        plugin_trigger_config_rebuild(screen, ('=dvb type',))

    if plugin_set_first_attr_choice([screen], ('scan_type', 'type', 'scan_typesat', 'tune_type', 'tuning_type'), ['single_transponder'], ['user defined transponder', 'single transponder', 'manual', 'single']):
        applied = True
        layout_changed = True
        tune_changed = True
    elif plugin_set_config_choice_by_label(screen, ('=tune',), ['single_transponder'], ['user defined transponder', 'single transponder', 'manual', 'single']):
        applied = True
        layout_changed = True
        tune_changed = True

    if tune_changed:
        plugin_trigger_config_rebuild(screen, ('=tune',))

    if layout_changed:
        plugin_refresh_scan_screen(screen)
        if plugin_find_config_entry(screen, ('=frequency',)) is None:
            plugin_trigger_config_rebuild(screen, ('=tune',))

    if hasattr(screen, 'scan_networkScan'):
        plugin_set_config_value(screen.scan_networkScan, False)
    else:
        plugin_set_config_value_by_label(screen, ('network scan',), False)

    tuner_index = None
    sat_index = None
    sat_value = None
    orb_pos = scan_data.get('orb_pos')

    if orb_pos is not None:
        tuner_index, sat_index, sat_value = plugin_find_satellite_match(screen, orb_pos)
        if tuner_index is not None:
            tuner_changed = False
            if plugin_set_first_attr_choice([screen], ('scan_nims', 'satfinder_scan_nims'), [tuner_index, str(tuner_index)], [str(tuner_index)]):
                tuner_changed = True
                applied = True
            elif plugin_set_config_choice_by_label(screen, ('=tuner',), [tuner_index, str(tuner_index)], [str(tuner_index)]):
                tuner_changed = True
                applied = True

            if tuner_changed:
                if not plugin_trigger_config_rebuild(screen, ('=tuner',)):
                    plugin_refresh_scan_screen(screen)
                tuner_index, sat_index, sat_value = plugin_find_satellite_match(screen, orb_pos)

    if tuner_index is not None and sat_index is not None:
        selections = getattr(screen, 'scan_satselection', []) or []
        if tuner_index < len(selections):
            if plugin_apply_satellite_selection(selections[tuner_index], sat_index, sat_value):
                applied = True
        sat_changed = False
        if hasattr(screen, 'tuning_sat'):
            try:
                if plugin_apply_satellite_selection(screen.tuning_sat, sat_index, sat_value):
                    applied = True
                    sat_changed = True
            except:
                pass
        if sat_value is not None:
            if plugin_set_config_choice_by_label(screen, ('=satellite',), [sat_value, str(sat_value)], [str(sat_value)]):
                sat_changed = True
        if sat_changed:
            plugin_trigger_config_rebuild(screen, ('=satellite',))

    containers = []
    if hasattr(screen, 'scan_sat'):
        containers.append(getattr(screen, 'scan_sat'))
    containers.append(screen)

    freq_value = scan_data.get('frequency')
    sr_value = scan_data.get('symbolrate')
    pol_value = scan_data.get('polarization')
    pol_text = 'horizontal' if int(pol_value or 0) == 0 else 'vertical'
    pol_short = 'h' if int(pol_value or 0) == 0 else 'v'

    # force satellite orbital position into config containers when present
    if orb_pos is not None:
        if plugin_set_first_attr_value(containers, ('orbpos', 'orb_pos', 'orbital_position'), orb_pos):
            applied = True
        else:
            plugin_set_config_value_by_label(screen, ('orbital position',), orb_pos)

    if plugin_set_first_attr_value(containers, ('frequency', 'freq'), freq_value):
        applied = True
    elif plugin_set_config_value_by_label(screen, ('=frequency',), freq_value):
        applied = True

    if plugin_set_first_attr_value(containers, ('symbolrate', 'symbol_rate', 'sr'), sr_value):
        applied = True
    elif plugin_set_config_value_by_label(screen, ('=symbol rate',), sr_value):
        applied = True

    if plugin_set_first_attr_choice(containers, ('polarization', 'polarisation', 'pol'), [pol_value, str(pol_value)], [pol_text, pol_short]):
        applied = True
    elif plugin_set_config_choice_by_label(screen, ('=polarization', '=polarisation'), [pol_value, str(pol_value)], [pol_text, pol_short]):
        applied = True

    system_value = scan_data.get('system')
    modulation_value = scan_data.get('modulation')

    if system_value is not None:
        system_text = 'dvb-s2' if int(system_value) == 1 else 'dvb-s'
        if plugin_set_first_attr_choice(containers, ('system',), [system_value, str(system_value)], [system_text]):
            applied = True
        elif plugin_set_config_choice_by_label(screen, ('=system',), [system_value, str(system_value)], [system_text]):
            applied = True

    if modulation_value is not None:
        modulation_text = '8psk' if int(modulation_value) == 2 else 'qpsk'
        if plugin_set_first_attr_choice(containers, ('modulation',), [modulation_value, str(modulation_value)], [modulation_text]):
            applied = True
        elif plugin_set_config_choice_by_label(screen, ('=modulation',), [modulation_value, str(modulation_value)], [modulation_text]):
            applied = True

    plugin_set_first_attr_choice(containers, ('fec', 'fec_s2', 'fec_inner'), [0, '0'], ['auto'])
    plugin_set_config_choice_by_label(screen, ('=fec',), [0, '0'], ['auto'])
    plugin_set_first_attr_choice(containers, ('inversion',), [], ['auto', 'unknown'])
    plugin_set_config_choice_by_label(screen, ('=inversion',), [], ['auto', 'unknown'])

    try:
        if hasattr(screen, 'transponder'):
            original = getattr(screen, 'transponder')
            values = list(original) if isinstance(original, (list, tuple)) else []
            while len(values) < 12:
                values.append(0)
            values[0] = int(freq_value or 0)
            values[1] = int(sr_value or 0)
            values[2] = int(pol_value or 0)
            values[3] = 0
            values[4] = 2
            if len(values) > 5 and orb_pos is not None:
                values[5] = int(orb_pos)
            if len(values) > 6 and system_value is not None:
                values[6] = int(system_value)
            if len(values) > 7 and modulation_value is not None:
                values[7] = int(modulation_value)
            if len(values) > 8:
                values[8] = 0
            if len(values) > 9:
                values[9] = 2
            if isinstance(original, tuple):
                values = tuple(values)
            setattr(screen, 'transponder', values)
            applied = True
    except:
        pass

    try:
        if hasattr(screen, 'frontendData') and isinstance(screen.frontendData, dict):
            screen.frontendData['tuner_type'] = 'DVB-S'
            screen.frontendData['frequency'] = int(freq_value or 0) * 1000
            screen.frontendData['symbol_rate'] = int(sr_value or 0) * 1000
            screen.frontendData['polarization'] = int(pol_value or 0)
            if orb_pos is not None:
                screen.frontendData['orbital_position'] = int(orb_pos)
                screen.frontendData['orb_position'] = int(orb_pos)
            if system_value is not None:
                screen.frontendData['system'] = int(system_value)
            if modulation_value is not None:
                screen.frontendData['modulation'] = int(modulation_value)
            applied = True
    except:
        pass

    plugin_refresh_scan_screen(screen)

    # Re-apply after createSetup/newConfig in images like OpenBH that may rebuild the config list.
    if plugin_set_first_attr_value(containers, ('frequency', 'freq'), freq_value):
        applied = True
    elif plugin_set_config_value_by_label(screen, ('=frequency',), freq_value):
        applied = True

    if plugin_set_first_attr_value(containers, ('symbolrate', 'symbol_rate', 'sr'), sr_value):
        applied = True
    elif plugin_set_config_value_by_label(screen, ('=symbol rate',), sr_value):
        applied = True

    if plugin_set_first_attr_choice(containers, ('polarization', 'polarisation', 'pol'), [pol_value, str(pol_value)], [pol_text, pol_short]):
        applied = True
    elif plugin_set_config_choice_by_label(screen, ('=polarization', '=polarisation'), [pol_value, str(pol_value)], [pol_text, pol_short]):
        applied = True

    if system_value is not None:
        if plugin_set_first_attr_choice(containers, ('system',), [system_value, str(system_value)], [system_text]):
            applied = True
        else:
            plugin_set_config_choice_by_label(screen, ('=system',), [system_value, str(system_value)], [system_text])

    if modulation_value is not None:
        if plugin_set_first_attr_choice(containers, ('modulation',), [modulation_value, str(modulation_value)], [modulation_text]):
            applied = True
        else:
            plugin_set_config_choice_by_label(screen, ('=modulation',), [modulation_value, str(modulation_value)], [modulation_text])

    if sat_value is not None:
        plugin_set_config_choice_by_label(screen, ('=satellite',), [sat_value, str(sat_value)], [str(sat_value)])

    try:
        plugin_refresh_scan_screen(screen)
    except:
        pass
    return applied


def plugin_attach_scan_injector(screen, scan_data):
    if screen is None or not scan_data:
        return False

    retry_state = {'count': 0, 'applied': False}

    def _inject_once():
        applied = False
        try:
            applied = bool(plugin_apply_scan_data_to_screen(screen, scan_data))
        except:
            applied = False
        if applied:
            retry_state['applied'] = True
            try:
                retry_timer = getattr(screen, '_fury_scan_retry_timer', None)
                if retry_timer is not None:
                    retry_timer.stop()
            except:
                pass
        return applied

    for callback_list_name in ('onFirstExecBegin', 'onLayoutFinish', 'onShown'):
        try:
            callback_list = getattr(screen, callback_list_name, None)
            if callback_list is not None and _inject_once not in callback_list:
                callback_list.append(_inject_once)
        except:
            pass

    # Some images rebuild Satfinder widgets shortly after the screen opens.
    # Retry only until the first successful apply instead of re-injecting for
    # several seconds, because repeated retunes can delay the signal lock.
    try:
        retry_timer = eTimer()

        def _retry_inject():
            retry_state['count'] += 1
            if retry_state.get('applied'):
                try:
                    retry_timer.stop()
                except:
                    pass
                return

            applied = _inject_once()
            if applied or retry_state['count'] >= 4:
                try:
                    retry_timer.stop()
                except:
                    pass
                return

            try:
                retry_timer.start(150, True)
            except:
                pass

        try:
            screen._fury_scan_retry_timer = retry_timer
            screen._fury_scan_retry_cb = _retry_inject
        except:
            pass

        try:
            retry_timer.timeout.connect(_retry_inject)
        except:
            try:
                retry_timer.callback.append(_retry_inject)
            except:
                pass
    except:
        retry_timer = None

    applied = _inject_once()

    if not applied and retry_timer is not None:
        try:
            retry_timer.start(120, True)
        except:
            pass

    return applied

# =================================================================
# Plugin screen classes
# =================================================================

# Safe icon paths used by the feeds screen
ICON_DIR = os.path.join(_plugin_dir(), "icon")
ICON_CLOCK = os.path.join(ICON_DIR, "clock.png")
ICON_SATELLITE = os.path.join(ICON_DIR, "satellite.png")
ICON_FREQUENCY = os.path.join(ICON_DIR, "dish.png")
ICON_FEED_TYPE = os.path.join(ICON_DIR, "film.png")
ICON_BISS_KEY = os.path.join(ICON_DIR, "key.png")


def plugin_get_full_text_first_line(feed):
    """أول سطر غير فاضي من full_text = الاسم الحقيقي للحدث."""
    full_text = _to_text(feed.get('full_text', '')).strip()
    for line in full_text.splitlines():
        line = line.strip()
        if line:
            return line
    return ''


def plugin_get_feed_event_name(feed):
    freq_val = _to_text(feed.get('freq_val', '')).strip()
    # 1) أول سطر من Full Post هو الاسم الحقيقي
    first_line = plugin_get_full_text_first_line(feed)
    if first_line and not plugin_is_generic_feed_name(first_line, freq_val):
        return first_line
    # 2) fallback: اسم الفيد المعتاد
    name = _to_text(feed.get('name', '')).strip()
    if not name or "unnamed" in name.lower() or plugin_is_generic_feed_name(name, freq_val):
        return plugin_extract_event_name_from_info(feed.get('full_text', ''), freq_val) or ''
    return name


def plugin_get_feed_satellite_text(feed):
    sat_text = _to_text(feed.get('sat', '')).strip() or 'Unknown'
    event_name = plugin_get_feed_event_name(feed)
    if event_name:
        return '%s | Event: %s' % (sat_text, event_name)
    return sat_text


def plugin_get_feed_full_post_text(feed):
    full_text = _to_text(feed.get('full_text', '')).strip()
    if full_text:
        return 'Full Post:\n%s' % full_text

    lines = []
    sat_text = _to_text(feed.get('sat', '')).strip()
    freq_text = _to_text(feed.get('freq_str', '')).strip()
    feed_type_text = _to_text(feed.get('feed_type', '')).strip()
    event_name = plugin_get_feed_event_name(feed)
    key_text = _to_text(feed.get('key', '')).strip()

    if sat_text:
        lines.append('Satellite: %s' % sat_text)
    if freq_text:
        lines.append('Frequency: %s' % freq_text)
    if feed_type_text and feed_type_text != 'Unknown':
        lines.append('Feed Type: %s' % feed_type_text)
    if event_name:
        lines.append('Event: %s' % event_name)
    if key_text:
        if key_text.upper() == 'FTA':
            lines.append('CW: FTA')
        else:
            lines.append('CW: %s' % plugin_format_key_display(key_text))

    if not lines:
        lines.append('-')
    return 'Full Post:\n%s' % '\n'.join(lines)


def plugin_collect_candidate_feeds(preferred_feed=None, available_feeds=None, fetched_feeds=None):
    candidate_feeds = []
    seen_ids = {}

    def add_feed(feed):
        if not isinstance(feed, dict):
            return
        cache_key = plugin_make_feed_cache_key(feed)
        if not cache_key:
            cache_key = '%s|%s|%s|%s' % (
                _to_text(feed.get('freq_val', '')).strip(),
                plugin_compact_key_text(feed.get('key', '')),
                _to_text(feed.get('name', '')).strip(),
                int(feed.get('timestamp', 0) or 0),
            )
        if cache_key in seen_ids:
            return
        seen_ids[cache_key] = True
        candidate_feeds.append(feed)

    add_feed(preferred_feed)
    for collection in (available_feeds or [], plugin_get_runtime_feeds(), fetched_feeds or []):
        for feed in collection:
            add_feed(feed)

    return candidate_feeds


def plugin_score_feed_match(feed, current_sid, current_name, current_freq, preferred_feed=None):
    if not isinstance(feed, dict):
        return -1

    raw_key = plugin_compact_key_text(feed.get('key', ''))
    if not raw_key:
        return -1

    score = 0
    feed_name = _to_text(feed.get('name', '')).strip()
    feed_text = _to_text(feed.get('full_text', '')).strip()
    feed_freq = _to_text(feed.get('freq_val', '')).strip()

    if preferred_feed is not None:
        if feed is preferred_feed:
            score += 250
        else:
            preferred_freq = _to_text(preferred_feed.get('freq_val', '')).strip()
            preferred_key = plugin_compact_key_text(preferred_feed.get('key', ''))
            if preferred_freq and preferred_key and preferred_freq == feed_freq and preferred_key == raw_key:
                score += 180

    current_sid = _to_text(current_sid).upper().zfill(4)
    if current_sid and current_sid != '0000':
        sid_match = re.search(r'\bSID\s*[:\-]?\s*([0-9A-Fa-f]{1,4})\b', feed_text, re.IGNORECASE)
        if sid_match and sid_match.group(1).upper().zfill(4) == current_sid:
            score += 140

    current_freq = _to_text(current_freq).strip()
    if current_freq.isdigit() and feed_freq.isdigit():
        diff = abs(int(feed_freq) - int(current_freq))
        if diff == 0:
            score += 90
        elif diff <= 2:
            score += 70

    current_name = _to_text(current_name).strip()
    if current_name and current_name.lower() != 'unknown' and len(current_name) > 2:
        if plugin_names_match(current_name, feed_name):
            score += 70
        elif plugin_names_match(current_name, feed_text):
            score += 45

    if feed_name and not plugin_is_generic_feed_name(feed_name, feed_freq):
        score += 5

    return score


def plugin_find_matching_feed_key(current_sid, current_name, current_freq, feeds=None, preferred_feed=None):
    best_key = None
    best_score = -1

    for feed in (feeds or []):
        score = plugin_score_feed_match(feed, current_sid, current_name, current_freq, preferred_feed)
        if score > best_score:
            best_score = score
            best_key = plugin_compact_key_text(feed.get('key', ''))

    if best_score >= 60:
        return best_key
    return None

def plugin_extract_sat_position_text(value):
    value = _to_text(value).strip()
    if not value or value == 'Unknown':
        return ''

    import re
    match = re.search(r'(\d{1,3}(?:\.\d+)?)\s*(?:°|º)?\s*([EWew])\b', value)
    if match:
        # Normalize degree to always have one decimal place: 16E → 16.0E, 16.0E → 16.0E
        deg_str = '%.1f' % float(match.group(1))
        return '%s%s' % (deg_str, match.group(2).upper())

    match = re.search(r'(\d{1,3}(?:\.\d+)?)\s*(East|West)\b', value, re.IGNORECASE)
    if match:
        deg_str = '%.1f' % float(match.group(1))
        return '%s%s' % (deg_str, 'E' if match.group(2).lower() == 'east' else 'W')

    return value


def plugin_get_enigma2_sat_name(orb_pos_text):
    """
    يجيب اسم القمر الرسمي من قاعدة بيانات enigma2
    بناءً على نص الموقع المداري زي '7.0E' أو '19.2E'
    بيرجع نص فاضي لو مش لاقي حاجة
    """
    try:
        match = re.match(r'([\d.]+)\s*([EWew])', orb_pos_text.strip())
        if not match:
            return ''
        orb_deg = float(match.group(1))
        direction = match.group(2).upper()
        # enigma2 بيخزن الموضع كـ integer بالعشر درجة
        # الغرب بيكون سالب (أو 3600 - pos)
        if direction == 'W':
            orb_int = 3600 - int(round(orb_deg * 10))
        else:
            orb_int = int(round(orb_deg * 10))
    except Exception:
        return ''

    # محاولة 1: من SATELLITES_MAP المدمجة (الأولوية الأولى دايمًا)
    # بنبحث بمقارنة رقمية ±1 وحدة (= ±0.1 درجة) لتغطية التقريب
    try:
        for map_key, map_name in SATELLITES_MAP.items():
            m = re.match(r'([\d.]+)\s*([EWew])', map_key.strip())
            if not m:
                continue
            map_deg = float(m.group(1))
            map_dir = m.group(2).upper()
            if map_dir == 'W':
                map_int = 3600 - int(round(map_deg * 10))
            else:
                map_int = int(round(map_deg * 10))
            if abs(map_int - orb_int) <= 1:
                return _to_text(map_name).strip()
    except Exception:
        pass

    # محاولة 2: من eDVBDB (fallback لو القمر مش في الخريطة)
    try:
        from enigma import eDVBDB
        db = eDVBDB.getInstance()
        sat_list = db.getSatellites()
        for sat in sat_list:
            try:
                pos = int(sat.orb_position)
                if abs(pos - orb_int) <= 1:
                    name = _to_text(getattr(sat, 'name', '') or '').strip()
                    if name:
                        return name
            except Exception:
                continue
    except Exception:
        pass

    # محاولة 3: من satellites.xml (آخر fallback)
    try:
        import xml.etree.ElementTree as ET
        for xml_path in [
            '/etc/tuxbox/satellites.xml',
            '/usr/share/enigma2/satellites.xml',
        ]:
            if not os.path.exists(xml_path):
                continue
            try:
                tree = ET.parse(xml_path)
                root = tree.getroot()
                for sat_elem in root.findall('sat'):
                    try:
                        pos = int(sat_elem.get('position', '9999'))
                        if abs(pos - orb_int) <= 1:
                            name = _to_text(sat_elem.get('name', '')).strip()
                            if name:
                                return name
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception:
        pass

    return ''


def plugin_get_feed_type_color(feed_type):
    feed_type = _to_text(feed_type).strip()
    if feed_type == '4:2:0':
        return 0x32CD32
    if feed_type == '4:2:2':
        return 0xFF4A4A
    return 0xD6D6D6


def plugin_build_feed_list_entry(feed, opened_feeds_list=None):
    freq_val = _to_text(feed.get('freq_val', '')).strip()

    # 1) أول سطر من Full Post هو الاسم الحقيقي
    name = plugin_get_full_text_first_line(feed)

    # 2) لو أول سطر generic أو فاضي → نجرب اسم الفيد العادي
    if not name or plugin_is_generic_feed_name(name, freq_val):
        name = _to_text(feed.get('name', '')).strip()

    # 3) لو مازال مش كويس → نجرب extraction من full_text
    if not name or "unnamed" in name.lower() or plugin_is_generic_feed_name(name, freq_val):
        name = plugin_extract_event_name_from_info(feed.get('full_text', ''), freq_val) or "Feed Unknown"

    # 4) لو source = Blogger وال name لسه FuryBiss-IslamSalama:
    #    - لو في اسم حدث حقيقي في الفيد → نعرضه
    #    - غير كده → نعرض اسم القمر
    source = _to_text(feed.get('source', '')).strip()
    if source == 'website' and name.lower().startswith('furybiss'):
        real_name = _to_text(feed.get('name', '')).strip()
        if real_name and not plugin_is_generic_feed_name(real_name, freq_val) and not real_name.lower().startswith('livefeed'):
            name = real_name
        else:
            sat_name = _to_text(feed.get('sat', '')).strip()
            if sat_name and sat_name != 'Unknown':
                name = sat_name

    time_text = plugin_extract_list_time_text(feed)
    group_text = ""
    source_channel = feed.get("source_channel", "")
    if source_channel == "biss2key":
        group_text = "1-"
    elif source_channel in ("live_sat_feeds", "live_7_feeds"):
        group_text = "2-"

    sat_text = plugin_extract_sat_position_text(feed.get('sat', ''))
    if not sat_text or sat_text == 'Unknown':
        sat_text = ''

    feed_type = _to_text(feed.get('feed_type', '')).strip()
    type_text = '[%s]' % feed_type if feed_type and feed_type != 'Unknown' else ''
    type_color = plugin_get_feed_type_color(feed_type)
    
    # حالة النقطة: 0=لا شيء / 1=خضراء / 2=حمراء
    dot_state = plugin_get_dot_state(feed, opened_feeds_list)

    return (dot_state, group_text, time_text, sat_text, type_text, name, type_color)


def plugin_render_feed_list_entry(dot_state, group_text, time_text, sat_text, type_text, name, type_color):
    # dot_state: 0=لا نقطة  1=خضراء (شغال)  2=حمراء (انتهى)
    if dot_state == 1:
        dot_char  = u"\u25CF"   # ●
        dot_color = 0x00FF00    # أخضر
    elif dot_state == 2:
        dot_char  = u"\u25CF"   # ●
        dot_color = 0xFF3030    # أحمر
    else:
        dot_char  = u""
        dot_color = 0x00FF00

    return [
        None,

        # 1. النقطة (خضراء أو حمراء)
        MultiContentEntryText(
            pos=(5, 0), size=(20, 46), font=0,
            flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER,
            text=dot_char,
            color=dot_color,
            color_sel=dot_color,
        ),
        # 2. Group number (تم تشفيتها لليمين لتوفير مساحة للدائرة)
        MultiContentEntryText(
            pos=(25, 0), size=(30, 46), font=0,
            flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER,
            text=_to_text(group_text),
            color=0xFFFFFF,
            color_sel=0xFFFFFF,
        ),
        # 3. Time
        MultiContentEntryText(
            pos=(55, 0), size=(85, 46), font=0,
            flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER,
            text=_to_text(time_text),
            color=0xFFD34D,
            color_sel=0xFFD34D,
        ),
        # 4. Feed type
        MultiContentEntryText(
            pos=(140, 0), size=(90, 46), font=0,
            flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER,
            text=_to_text(type_text),
            color=type_color,
            color_sel=type_color,
        ),
        # 5. Satellite
        MultiContentEntryText(
            pos=(230, 0), size=(110, 46), font=0,
            flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER,
            text=_to_text(sat_text),
            color=0x00D2FF,
            color_sel=0x00D2FF,
        ),
        # 6. Channel name
        MultiContentEntryText(
            pos=(345, 0), size=(365, 46), font=0,
            flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER,
            text=_to_text(name),
            color=0xFFFFFF,
            color_sel=0xFFCC00,
        ),
    ]
class FuryBissFeedsMenuList(MenuList):
    def __init__(self, listdata=None):
        MenuList.__init__(self, listdata or [], False, eListboxPythonMultiContent)
        try:
            self.l.setBuildFunc(plugin_render_feed_list_entry)
        except:
            pass
        try:
            self.l.setFont(0, gFont('Regular', 26))
        except:
            try:
                self.l.setFont(0, gFont('Regular', 24))
            except:
                pass
        try:
            self.l.setItemHeight(46)
        except:
            pass

# ── وقت البث المتوقع: بعد كذا ساعة من نشر الفيد نعتبره "انتهى" وتتحول النقطة لحمرا
_FEED_CLOSED_AFTER_SECONDS = 5 * 3600  # 5 ساعات


def plugin_save_opened_feeds():
    """
    حفظ قائمة الفيدات المفتوحة على الديسك.
    الشكل: { dedup_id -> feed_timestamp_int }
    """
    try:
        today_key = plugin_get_local_day_key()
        with open(_OPENED_FEEDS_FILE, 'w') as f:
            json.dump({'day_key': today_key, 'feeds': global_opened_feeds}, f)
    except Exception:
        pass


def plugin_load_opened_feeds():
    """
    تحميل الفيدات من الديسك.
    يدعم الشكل القديم (list) والجديد (dict).
    """
    global global_opened_feeds
    try:
        if not os.path.exists(_OPENED_FEEDS_FILE):
            return
        with open(_OPENED_FEEDS_FILE, 'r') as f:
            data = json.load(f)
        today_key = plugin_get_local_day_key()
        if data.get('day_key', '') != today_key:
            try:
                os.remove(_OPENED_FEEDS_FILE)
            except Exception:
                pass
            return
        feeds = data.get('feeds', {})
        # backward compat: لو الشكل القديم list
        if isinstance(feeds, list):
            global_opened_feeds = {did: 0 for did in feeds if isinstance(did, str)}
        elif isinstance(feeds, dict):
            global_opened_feeds = {k: int(v or 0) for k, v in feeds.items()}
        else:
            global_opened_feeds = {}
    except Exception:
        pass


def plugin_register_opened_feed(dedup_id, feed_timestamp=0):
    """تسجيل فيد كـ 'مفتوح' مع حفظ timestamp نشره."""
    global global_opened_feeds
    if not dedup_id:
        return
    try:
        feed_timestamp = int(feed_timestamp or 0)
    except Exception:
        feed_timestamp = 0
    global_opened_feeds[dedup_id] = feed_timestamp
    plugin_save_opened_feeds()


def plugin_get_dot_state(feed, opened_feeds_dict):
    """
    إرجاع حالة النقطة:
      0 = لا نقطة
      1 = خضراء  (فتحنا الكي والبث لسه جاري)
      2 = حمراء  (فتحنا الكي لكن مضى وقت كافٍ = البث انتهى)
    """
    if not opened_feeds_dict:
        return 0
    dedup_id = "%s|%s|%s|%s" % (
        _to_text(feed.get("freq_val", "")).strip(),
        _to_text(feed.get("pol_val", "")).strip(),
        _to_text(feed.get("sr_val", "")).strip(),
        plugin_compact_key_text(feed.get("key", "")) or _to_text(feed.get("name", "")).strip()
    )
    if dedup_id not in opened_feeds_dict:
        return 0
    # حساب الوقت اللي مضى على نشر الفيد
    try:
        feed_ts = int(opened_feeds_dict[dedup_id] or feed.get('timestamp', 0) or 0)
    except Exception:
        feed_ts = 0
    if feed_ts > 0:
        elapsed = int(time.time()) - feed_ts
        if elapsed >= _FEED_CLOSED_AFTER_SECONDS:
            return 2   # حمراء = انتهى البث
    return 1   # خضراء = لسه شغال


# ── قاموس global_opened_feeds: { dedup_id -> feed_publish_timestamp }
global_opened_feeds = {}
plugin_load_opened_feeds()

class FuryBissSatelliteFilterScreen(Screen):
    """شاشة اختيار القمر لفلترة الفيدات"""
    skin = """
        <screen position="center,center" size="900,680" title="Filter by Satellite" backgroundColor="#151515" cornerRadius="10">
            <widget name="sat_list" position="30,20" size="840,590" scrollbarMode="showOnDemand"
                font="Regular;28" itemHeight="50" backgroundColor="#151515" foregroundColor="#ffffff"
                backgroundColorSelected="#1b3c85" foregroundColorSelected="#ffcc00" cornerRadius="8" />
            <widget name="key_red"    position="30,622"  size="240,44" backgroundColor="#7a0000" foregroundColor="white" font="Regular;22" halign="center" valign="center" cornerRadius="12" />
            <widget name="key_green"  position="330,622" size="240,44" backgroundColor="#005a00" foregroundColor="white" font="Regular;22" halign="center" valign="center" cornerRadius="12" />
            <widget name="key_yellow" position="630,622" size="240,44" backgroundColor="#a07400" foregroundColor="white" font="Regular;22" halign="center" valign="center" cornerRadius="12" />
        </screen>
    """

    def __init__(self, session, satellites):
        Screen.__init__(self, session)
        self.satellites = [u"-- All Satellites --"] + satellites

        self["sat_list"] = MenuList(self.satellites)
        self["key_red"]    = Button("Cancel")
        self["key_green"]  = Button("Select")
        self["key_yellow"] = Button("All Feeds")

        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions"],
            {
                "ok":     self.selectSat,
                "green":  self.selectSat,
                "yellow": self.showAll,
                "red":    self.doCancel,
                "cancel": self.doCancel,
                "up":     self.keyUp,
                "down":   self.keyDown,
                "left":   self.keyPageUp,
                "right":  self.keyPageDown,
            },
            -2,
        )

    def keyUp(self):
        self["sat_list"].up()

    def keyDown(self):
        self["sat_list"].down()

    def keyPageUp(self):
        self["sat_list"].pageUp()

    def keyPageDown(self):
        self["sat_list"].pageDown()

    def doCancel(self):
        # يجب نبعت None صراحةً للـ callback عشان متحصلش كراش
        self.close(None)

    def selectSat(self):
        idx = self["sat_list"].getSelectedIndex()
        if idx == 0:
            self.close(None)
        else:
            self.close(self.satellites[idx])

    def showAll(self):
        self.close(None)


class FuryBissFeedsScreen(Screen):
    skin = ("""
        <screen position="83,180" size="1760,760" title="Latest Server Feeds - FuryBiss" backgroundColor="#151515" cornerRadius="0">
                <widget name="list" position="24,32" size="920,632" scrollbarMode="showOnDemand" font="Regular;32" itemHeight="46" backgroundColor="#151515" foregroundColor="white" backgroundColorSelected="#2a2a2a" foregroundColorSelected="#001b3c85" cornerRadius="8" />
                <eLabel position="960,24" size="2,630" backgroundColor="#333333" />
                <ePixmap pixmap="%s" position="975,28" size="28,28" alphatest="blend" scale="1" />
                <ePixmap pixmap="%s" position="975,87" size="28,28" alphatest="blend" scale="1" />
                <ePixmap pixmap="%s" position="975,150" size="28,28" alphatest="blend" scale="1" />
                <ePixmap pixmap="%s" position="975,206" size="28,28" alphatest="blend" scale="1" />
                <ePixmap pixmap="%s" position="975,272" size="28,28" alphatest="blend" scale="1" />
                <widget name="detail_published" position="1020,26" size="700,34" font="Regular;24" halign="left" valign="center" foregroundColor="#e0e0e0" backgroundColor="#151515" transparent="1" />
                <widget name="detail_satellite" position="1020,82" size="700,54" font="Regular;24" halign="left" valign="center" foregroundColor="yellow" backgroundColor="#151515" transparent="1" />
                <widget name="detail_frequency" position="1020,148" size="700,34" font="Regular;24" halign="left" valign="center" foregroundColor="#e0e0e0" backgroundColor="#151515" transparent="1" />
                <widget name="detail_feed_type" position="1020,204" size="700,34" font="Regular;24" halign="left" valign="center" foregroundColor="#e0e0e0" backgroundColor="#151515" transparent="1" />
                <widget name="detail_biss_key" position="1020,270" size="700,34" font="Regular;24" halign="left" valign="center" foregroundColor="#e0e0e0" backgroundColor="#151515" transparent="1" />
                
                
                <widget name="full_post" position="973,314" size="755,350" font="Regular;25" halign="left" valign="top" foregroundColor="yellow" backgroundColor="#151515" transparent="1" />
                <widget name="key_red" position="80,692" size="320,44" backgroundColor="#7a0000" foregroundColor="white" font="Regular;22" halign="center" valign="center" zPosition="1" cornerRadius="14" />
                <widget name="key_green" position="507,692" size="320,44" backgroundColor="#005a00" foregroundColor="white" font="Regular;22" halign="center" valign="center" zPosition="1" cornerRadius="14" />
                <widget name="key_yellow" position="934,692" size="320,44" backgroundColor="#a07400" foregroundColor="white" font="Regular;22" halign="center" valign="center" zPosition="1" cornerRadius="14" />
                <widget name="key_blue" position="1361,692" size="320,44" backgroundColor="#00007a" foregroundColor="white" font="Regular;22" halign="center" valign="center" zPosition="1" cornerRadius="14" />
                <!-- Header bar: feed count (left) + clock (right) -->
                <eLabel position="0,0" size="1760,32" backgroundColor="#1a1a2e" zPosition="0" />
                <widget name="feed_count_lbl" position="10,0" size="160,32" font="Regular;24" halign="left" valign="center" foregroundColor="#cccccc" backgroundColor="#1a1a2e" transparent="0" zPosition="1" />
                <widget name="feed_count_num" position="168,0" size="90,32" font="Regular;24" halign="left" valign="center" foregroundColor="#4da6ff" backgroundColor="#1a1a2e" transparent="0" zPosition="1" />
                <widget name="clock_label" position="1100,0" size="650,32" font="Regular;24" halign="right" valign="center" foregroundColor="#cccccc" backgroundColor="#1a1a2e" transparent="0" zPosition="1" />
        </screen>
    """ % (
        ICON_CLOCK,
        ICON_SATELLITE,
        ICON_FREQUENCY,
        ICON_FEED_TYPE,
        ICON_BISS_KEY,
    ))

    def __init__(self, session):
        Screen.__init__(self, session)
        self.feeds = []
        self.all_feeds = []       # كل الفيدات بدون فلتر
        self.sat_filter = None    # None = عرض الكل  /  نص = اسم القمر المختار
        self.list = []
        self["list"] = FuryBissFeedsMenuList(self.list)
        self["detail_published"] = Label("Published: -")
        self["detail_satellite"] = Label("Satellite: -")
        self["detail_frequency"] = Label("Frequency: -")
        self["detail_feed_type"] = Label("Feed Type: -")
        self["detail_biss_key"] = Label("BISS Key: -")
        self["full_post"] = Label("") # This line was added
        self["full_post_sat"] = Label("")
        self["full_post_title"] = Label("")
        self["feed_count_lbl"] = Label(u"📡  Feeds:")
        self["feed_count_num"] = Label("0")
        self["clock_label"] = Label("")
        # Clock timer - يحدث كل ثانية
        self._clock_timer = eTimer()
        try:
            self._clock_conn = self._clock_timer.timeout.connect(self._updateClock)
        except:
            self._clock_timer.callback.append(self._updateClock)
        self._clock_timer.start(1000, False)
        plugin_ensure_my_country()
        self._updateClock()
        global global_opened_feeds
        self.opened_feeds = global_opened_feeds   # dict: {dedup_id -> feed_ts}
        self.pending_scan_data = None
        self._feed_fetch_busy = False
        self._auto_biss_busy = False
        self._auto_biss_pending_marker = None
        
        self["key_red"] = Button("Close")
        self["key_green"] = Button("Auto BISS")
        self["key_yellow"] = Button("Scan Feed")
        self["key_blue"] = Button("Settings")
        
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "DirectionActions", "MenuActions"], {
            "red": self.close,
            "cancel": self.close,
            "green": self.autoFetch,
            "yellow": self.scanFeed,
            "blue": self.openSettings,
            "ok": self.injectSelectedKey,  # <--- adjustment here
            "menu": self.openSatelliteFilter,   # زر MENU → قايمة الأقمار
            "up": self.keyUp,
            "down": self.keyDown,
            "left": self.keyPageUp,
            "right": self.keyPageDown,
        }, -2)
        
        self.timer = eTimer()
        try:
            self.timer_conn = self.timer.timeout.connect(self.doFetch)
        except:
            self.timer.callback.append(self.doFetch)
        self.timer.start(100, True)

        # Register this instance so the notifier can push live updates
        global _active_feeds_screen
        _active_feeds_screen = self

    def close(self):
        global _active_feeds_screen
        try:
            if _active_feeds_screen is self:
                _active_feeds_screen = None
        except Exception:
            pass
        Screen.close(self)

    def _updateClock(self):
        try:
            self["clock_label"].setText(plugin_get_my_country_clock_text())
        except Exception:
            pass

    def _triggerLiveRefresh(self):
        """
        Called by FuryBissNotifier when new feeds land while this screen is open.
        Reloads the list instantly from the runtime cache — no extra network request.
        Preserves the current scroll position.
        """
        if getattr(self, '_feed_fetch_busy', False):
            # A full network fetch is already running; it will include the new feeds
            return
        try:
            day_start, day_end = plugin_get_today_feed_window()
            fresh_feeds = plugin_get_runtime_feeds(day_start, day_end)
            if fresh_feeds and len(fresh_feeds) > len(self.all_feeds):
                # Save position before refresh
                try:
                    current_idx = self["list"].getSelectedIndex()
                except Exception:
                    current_idx = 0
                self.all_feeds = fresh_feeds
                self._applyFilter()
                # Restore position (new feeds appear at top, so shift index by delta)
                try:
                    delta = len(self.feeds) - (len(self.all_feeds) - len(fresh_feeds) + len(self.all_feeds) - len(self.feeds))
                    new_idx = max(0, min(current_idx, len(self.feeds) - 1))
                    self["list"].moveToIndex(new_idx)
                except Exception:
                    pass
        except Exception:
            pass

    def doFetch(self):
        try:
            self.timer.stop()
        except Exception:
            pass

        if getattr(self, '_feed_fetch_busy', False):
            return

        self._feed_fetch_busy = True
        try:
            self["full_post_title"].setText("")
            self["full_post_sat"].setText("")
            self["full_post"].setText("Loading feeds in background...")
        except Exception:
            pass

        try:
            deferred = threads.deferToThread(plugin_fetch_all_feeds)
            deferred.addCallback(self._onFeedsFetched)
            deferred.addErrback(self._onFeedsFetchError)
        except Exception as error:
            self._feed_fetch_busy = False
            try:
                self["full_post"].setText("Feed loading error: %s" % _to_text(error))
            except Exception:
                pass

    def _onFeedsFetched(self, fetched):
        self._feed_fetch_busy = False
        self.all_feeds = fetched if fetched else []

        # تطبيق الفلتر الحالي
        self._applyFilter()

    def _onFeedsFetchError(self, failure):
        self._feed_fetch_busy = False
        self.all_feeds = []
        try:
            self["full_post_title"].setText("")
            self["full_post_sat"].setText("")
            self["full_post"].setText("Feed loading error: %s" % _to_text(failure))
        except Exception:
            pass
        try:
            self._applyFilter()
        except Exception:
            pass

    def _applyFilter(self):
        """تصفية self.feeds بناءً على self.sat_filter ثم تحديث الشاشة."""
        if self.sat_filter:
            sat_pos_key = self.sat_filter   # مثال: '7.0E'
            def _feed_matches_sat(f):
                sat_raw = _to_text(f.get('sat', '')).strip()
                if not sat_raw:
                    return False
                # قارن الموضع المداري المستخرج من الفيد بالـ pos_key المختار
                feed_pos = plugin_extract_sat_position_text(sat_raw) or sat_raw
                return feed_pos == sat_pos_key
            self.feeds = [f for f in self.all_feeds if _feed_matches_sat(f)]
        else:
            self.feeds = list(self.all_feeds)

        # تحديث عنوان الشاشة ليعكس الفلتر النشط
        try:
            label = getattr(self, '_sat_filter_label', None) or self.sat_filter
            if label:
                self.setTitle(u"Latest Server Feeds \u2013 %s" % label)
            else:
                self.setTitle("Latest Server Feeds - FuryBiss")
        except Exception:
            pass

        # تحديث عداد الفيدات
        try:
            self["feed_count_num"].setText(str(len(self.feeds)))
        except Exception:
            pass

        if not self.feeds:
            self["detail_published"].setText("Published: -")
            self["detail_satellite"].setText("Satellite: -")
            self["detail_frequency"].setText("Frequency: -")
            self["detail_feed_type"].setText("Feed Type: -")
            self["detail_biss_key"].setText("BISS Key: -")
            if self.sat_filter:
                self["full_post"].setText("No feeds found for: %s" % self.sat_filter)
            else:
                self["full_post"].setText("No feeds have been published today - FuryBiss")
            self["full_post_sat"].setText("")
            self["full_post_title"].setText("")
            self["list"].setList([])
            return

        self.list = []
        for f in self.feeds:
            self.list.append(plugin_build_feed_list_entry(f, getattr(self, 'opened_feeds', [])))

        self["list"].setList(self.list)
        self.updateDetails()

    def keyUp(self):
        self["list"].up()
        self.pending_scan_data = None
        self.updateDetails()

    def keyDown(self):
        self["list"].down()
        self.pending_scan_data = None
        self.updateDetails()
        
    def keyPageUp(self):
        self["list"].pageUp()
        self.pending_scan_data = None
        self.updateDetails()

    def keyPageDown(self):
        self["list"].pageDown()
        self.pending_scan_data = None
        self.updateDetails()

    def updateDetails(self):
        import time
        idx = self["list"].getSelectedIndex()
        if 0 <= idx < len(self.feeds):
            f = self.feeds[idx]

            full_time_str = plugin_extract_published_display_text(f)
            published_text = 'Published: %s' % full_time_str if full_time_str else 'Published: -'
            satellite_text = 'Satellite: %s' % plugin_get_feed_satellite_text(f)
            frequency_text = 'Frequency: %s' % (_to_text(f.get('freq_str', '')).strip() or '-')
            feed_type_text = 'Feed Type: %s' % (_to_text(f.get('feed_type', '')).strip() or 'Unknown')

            key_value = _to_text(f.get('key', '')).strip().upper()
            if key_value == 'FTA':
                key_display = 'FTA'
            elif key_value:
                key_display = plugin_format_key_display(key_value)
            else:
                key_display = '-'
            biss_key_text = 'BISS Key: %s' % key_display

            full_post_text = plugin_get_feed_full_post_text(f)

            self['detail_published'].setText(published_text)
            self['detail_satellite'].setText(satellite_text)
            self['detail_frequency'].setText(frequency_text)
            self['detail_feed_type'].setText(feed_type_text)
            self['detail_biss_key'].setText(biss_key_text)

            # Show sat name in white above full_post for Blogger/website source
            source = _to_text(f.get('source', '')).strip()
            if source == 'website':
                sat_header = _to_text(f.get('sat', '')).strip() or '-'
                self['full_post_title'].setText('Full Post:')
                self['full_post_sat'].setText(sat_header)
                # Strip "Full Post:\n" prefix — it's now shown in full_post_title
                body = full_post_text
                if body.startswith('Full Post:\n'):
                    body = body[len('Full Post:\n'):]
                self['full_post'].setText(body)
            else:
                self['full_post_title'].setText('')
                self['full_post_sat'].setText('')
                self['full_post'].setText(full_post_text)


    def openSatelliteFilter(self):
        """فتح شاشة اختيار القمر وتصفية الفيدات بناءً على الاختيار."""
        # ---- توحيد الأقمار بالموضع المداري (مش الاسم الخام) ----
        seen_pos = {}
        for f in self.all_feeds:
            sat = _to_text(f.get('sat', '')).strip()
            if not sat or sat == 'Unknown':
                continue
            pos_key = plugin_extract_sat_position_text(sat) or sat
            if pos_key not in seen_pos:
                seen_pos[pos_key] = sat

        if not seen_pos:
            self.session.open(MessageBox, "No satellite data available in current feeds.", MessageBox.TYPE_INFO, timeout=4)
            return

        # بناء قايمة العرض
        sats = []
        self._sat_pos_map = {}   # display_name -> pos_key
        self._sat_label_map = {} # pos_key -> display_name

        for pos_key in sorted(seen_pos.keys()):
            # اولاً: نجرب SATELLITES_MAP أو Enigma2
            clean_name = plugin_get_enigma2_sat_name(pos_key)

            if clean_name:
                display = u'%s \u2022 %s' % (clean_name, pos_key)
            else:
                # مش موجود -> نجرب نستخرج درجة من الاسم الخام ونبحث فيها
                raw = seen_pos[pos_key]
                extracted = plugin_extract_sat_position_text(raw)
                if extracted and extracted != pos_key:
                    fallback_name = plugin_get_enigma2_sat_name(extracted)
                    if fallback_name:
                        display = u'%s \u2022 %s' % (fallback_name, extracted)
                    else:
                        display = extracted
                else:
                    # آخر حل: نظّف الاسم الخام
                    raw_clean = re.sub(r'\s*\([^)]*$', '', raw).strip()
                    raw_clean = re.sub(r'\s*\(\s*KU[\s\-]*BAND\s*\)', '', raw_clean, flags=re.IGNORECASE).strip()
                    display = raw_clean if raw_clean else pos_key

            sats.append(display)
            self._sat_pos_map[display] = pos_key
            self._sat_label_map[pos_key] = display

        self.session.openWithCallback(self._onSatSelected, FuryBissSatelliteFilterScreen, sats)

    def _onSatSelected(self, sat_name):
        """Callback بعد اختيار القمر من الشاشة الفرعية."""
        # sat_name = None → كل الأقمار  /  نص → اسم العرض المختار
        if sat_name:
            # احفظ pos_key للفلترة (مثال: '7.0E') مش اسم العرض الكامل
            pos_map = getattr(self, '_sat_pos_map', {})
            self.sat_filter = pos_map.get(sat_name, sat_name)
            # احفظ اسم العرض لعنوان الشاشة
            self._sat_filter_label = sat_name
        else:
            self.sat_filter = None
            self._sat_filter_label = None
        self._applyFilter()

    def openSettings(self):
        self.session.open(FuryBisSetup)
        
    def _makeAutoBissMarker(self, feed):
        if not isinstance(feed, dict):
            return None
        try:
            dedup_id = "%s|%s|%s|%s" % (
                _to_text(feed.get("freq_val", "")).strip(),
                _to_text(feed.get("pol_val", "")).strip(),
                _to_text(feed.get("sr_val", "")).strip(),
                plugin_compact_key_text(feed.get("key", "")) or _to_text(feed.get("name", "")).strip()
            )
            feed_ts = int(feed.get('timestamp', 0) or 0)
            return (dedup_id, feed_ts)
        except Exception:
            return None

    def _refreshAutoBissDotsOnly(self):
        global global_opened_feeds
        try:
            self.opened_feeds = global_opened_feeds
        except Exception:
            pass
        try:
            current_index = self["list"].getSelectedIndex()
        except Exception:
            current_index = 0
        try:
            self.list = []
            for f in self.feeds:
                self.list.append(plugin_build_feed_list_entry(f, getattr(self, 'opened_feeds', [])))
            self["list"].setList(self.list)
            try:
                if 0 <= current_index < len(self.list):
                    self["list"].moveToIndex(current_index)
            except Exception:
                pass
        except Exception:
            pass

    def _startAutoBissAsync(self, info, selected_feed=None, selected_key='', available_feeds=None, searching_allowed=True, success_text=None):
        if getattr(self, '_auto_biss_busy', False):
            self.session.open(MessageBox, "Auto BISS is already running...", MessageBox.TYPE_INFO, timeout=3)
            return

        self._auto_biss_busy = True
        self._auto_biss_pending_marker = self._makeAutoBissMarker(selected_feed)
        selected_key = plugin_compact_key_text(selected_key) or _to_text(selected_key).strip()

        try:
            name = info.get("name", "Unknown")
            freq = info.get("freq", "")
            sid = info.get("sid", "0000")
            self["detail_published"].setText("Auto BISS is working in background...")
            self["detail_satellite"].setText("Name: %s" % name)
            self["detail_frequency"].setText("Freq: %s" % freq)
            self["detail_feed_type"].setText("SID: %s" % sid)
            self["detail_biss_key"].setText("Adding Biss Key... ")
            self["full_post"].setText("")
            self["full_post_sat"].setText("")
            self["full_post_title"].setText("")
        except Exception:
            pass

        try:
            feeds_snapshot = list(available_feeds or [])
        except Exception:
            feeds_snapshot = []

        try:
            deferred = threads.deferToThread(
                self._autoBissWorker,
                dict(info or {}),
                dict(selected_feed or {}) if isinstance(selected_feed, dict) else None,
                selected_key,
                feeds_snapshot,
                bool(searching_allowed),
                success_text or ''
            )
            deferred.addCallback(self._onAutoBissDone)
            deferred.addErrback(self._onAutoBissError)
        except Exception as error:
            self._auto_biss_busy = False
            self.session.open(MessageBox, "Auto BISS start error: %s" % _to_text(error), MessageBox.TYPE_ERROR)
            self.updateDetails()

    def _autoBissWorker(self, info, selected_feed=None, selected_key='', available_feeds=None, searching_allowed=True, success_text=''):
        try:
            sid = info.get("sid", "0000")
            name = info.get("name", "Unknown")
            freq = info.get("freq", "")

            if selected_key:
                fetched_key = selected_key
            elif searching_allowed:
                fetched_key = plugin_fetch_telegram_key(
                    sid,
                    name,
                    freq,
                    preferred_feed=selected_feed,
                    available_feeds=available_feeds or []
                )
            else:
                fetched_key = ''

            key_text = _to_text(fetched_key).strip()
            if not key_text:
                return {'status': 'not_found'}
            if key_text.startswith('ERROR'):
                return {'status': 'error', 'message': key_text}
            if key_text.upper() == 'FTA':
                return {'status': 'fta'}

            compact_key = plugin_compact_key_text(key_text) or key_text
            target_paths = get_storage_write_paths()
            lines, _ = build_biss_lines(info, compact_key)
            for path in target_paths:
                plugin_append_key_lines(path, lines)

            restart_ok = plugin_restart_active_emu()
            return {
                'status': 'success',
                'key': compact_key,
                'restart_ok': restart_ok,
                'success_text': success_text,
            }
        except Exception as error:
            return {'status': 'error', 'message': _to_text(error)}

    def _onAutoBissDone(self, result):
        self._auto_biss_busy = False
        if not isinstance(result, dict):
            result = {'status': 'error', 'message': _to_text(result)}

        status = result.get('status', '')
        if status == 'success':
            marker = getattr(self, '_auto_biss_pending_marker', None)
            if marker:
                try:
                    plugin_register_opened_feed(marker[0], marker[1])
                except Exception:
                    pass

            key_text = _to_text(result.get('key', '')).strip()
            message = result.get('success_text') or "Success! Key Found and Applied:\n%s" % key_text
            if result.get('restart_ok') is False:
                message += "\n\nNote: EMU restart command was not confirmed."
            self.session.open(MessageBox, message, MessageBox.TYPE_INFO, timeout=5)
            self._refreshAutoBissDotsOnly()
            self.updateDetails()
        elif status == 'fta':
            self.session.open(MessageBox, "Free Channel", MessageBox.TYPE_INFO, timeout=5)
            self.updateDetails()
        elif status == 'not_found':
            self.session.open(MessageBox, "Key not found on Server for this Channel!", MessageBox.TYPE_ERROR)
            self.updateDetails()
        else:
            self.session.open(MessageBox, "Auto BISS error: %s" % _to_text(result.get('message', 'Unknown error')), MessageBox.TYPE_ERROR)
            self.updateDetails()

        self._auto_biss_pending_marker = None

    def _onAutoBissError(self, failure):
        self._auto_biss_busy = False
        self._auto_biss_pending_marker = None
        self.session.open(MessageBox, "Auto BISS error: %s" % _to_text(failure), MessageBox.TYPE_ERROR)
        self.updateDetails()

    def autoFetch(self):
        info = plugin_get_current_channel()
        selected_feed = None
        selected_key = ''
        idx = self["list"].getSelectedIndex()
        if 0 <= idx < len(self.feeds):
            selected_feed = self.feeds[idx]
            raw_key = _to_text(selected_feed.get("key", "")).strip()
            if raw_key.upper() == "FTA":
                self.session.open(MessageBox, "Free Channel", MessageBox.TYPE_INFO, timeout=5)
                self.updateDetails()
                return
            selected_key = plugin_compact_key_text(raw_key)

        self._startAutoBissAsync(
            info,
            selected_feed=selected_feed,
            selected_key=selected_key,
            available_feeds=list(self.feeds),
            searching_allowed=True,
            success_text=''
        )

    def injectSelectedKey(self):
        idx = self["list"].getSelectedIndex()
        if 0 <= idx < len(self.feeds):
            feed = self.feeds[idx]
            raw_key = _to_text(feed.get("key", "")).strip()

            if raw_key.upper() == "FTA":
                self.session.open(MessageBox, "Free Channel", MessageBox.TYPE_INFO, timeout=5)
                return

            compact_key = plugin_compact_key_text(raw_key)
            if compact_key and len(compact_key) >= 16:
                info = plugin_get_current_channel()
                self._startAutoBissAsync(
                    info,
                    selected_feed=feed,
                    selected_key=compact_key,
                    available_feeds=list(self.feeds),
                    searching_allowed=False,
                    success_text="✅ The key was injected successfully for the current channel!\n\n%s" % compact_key
                )
            else:
                self.session.open(MessageBox, "❌ This feed does not contain a key", MessageBox.TYPE_ERROR)

    def injectData(self):
        idx = self["list"].getSelectedIndex()
        if 0 <= idx < len(self.feeds):
            scan_data = plugin_extract_scan_data(self.feeds[idx])
            if not scan_data:
                self.session.open(MessageBox, "No valid frequency data available for extraction!", MessageBox.TYPE_ERROR)
                return

            self.pending_scan_data = scan_data

            freq_text = _to_text(self.feeds[idx].get('freq_val', '')).strip() or _to_text(scan_data.get('frequency', '')).strip() or '--'
            sr_text = _to_text(self.feeds[idx].get('sr_val', '')).strip() or _to_text(scan_data.get('symbolrate', '')).strip() or '--'
            try:
                sr_text = str(int(float(sr_text))).zfill(5)
            except:
                pass

            pol_raw = _to_text(self.feeds[idx].get('pol_val', '')).strip().upper()
            if not pol_raw:
                pol_raw = 'H' if int(scan_data.get('polarization', 0)) == 0 else 'V'
            pol_text = 'Horizontal' if pol_raw == 'H' else 'Vertical' if pol_raw == 'V' else 'Unknown'

            sat_text = _to_text(self.feeds[idx].get('sat', '')).strip() or _to_text(scan_data.get('sat_text', '')).strip() or 'Unknown'

            msg = "Frequency data was successfully written\n\n"
            msg += "Freq: %s | SR: %s\n" % (freq_text, sr_text)
            msg += "Pol: %s\n" % pol_text
            msg += "Sat: %s\n\n" % sat_text
            msg += "Now press Yellow Button to Scan!"
            self.session.open(MessageBox, msg, MessageBox.TYPE_INFO, timeout=7)

    def scanFeed(self):
        try:
            idx = self["list"].getSelectedIndex()
            if self.pending_scan_data:
                scan_data = self.pending_scan_data
            elif 0 <= idx < len(self.feeds):
                scan_data = plugin_extract_scan_data(self.feeds[idx])
            else:
                scan_data = None

            try:
                from Plugins.SystemPlugins.Satfinder.plugin import Satfinder
                TargetScreen = Satfinder
            except ImportError:
                try:
                    from Screens.Satfinder import Satfinder
                    TargetScreen = Satfinder
                except ImportError:
                    from Screens.ScanSetup import ScanSetup
                    TargetScreen = ScanSetup

            force_manual_mode = False
            try:
                screen_module = _to_text(getattr(TargetScreen, '__module__', ''))
                screen_name = _to_text(getattr(TargetScreen, '__name__', ''))
                if 'Satfinder' in screen_name or 'Satfinder' in screen_module:
                    plugin_patch_satfinder_class(TargetScreen)
                    force_manual_mode = True
            except:
                force_manual_mode = False

            global _PLUGIN_FORCE_SATFINDER_MANUAL_MODE
            previous_force_flag = _PLUGIN_FORCE_SATFINDER_MANUAL_MODE
            if force_manual_mode:
                _PLUGIN_FORCE_SATFINDER_MANUAL_MODE = True
            try:
                screen = self.session.open(TargetScreen)
            finally:
                _PLUGIN_FORCE_SATFINDER_MANUAL_MODE = previous_force_flag

            if scan_data:
                applied = plugin_attach_scan_injector(screen, scan_data)
                if not applied:
                    self.session.open(MessageBox, "The scan screen was opened, but this image does not fully allow automatic value injection. Enter the satellite manually if needed.", MessageBox.TYPE_INFO, timeout=6)
            else:
                self.session.open(MessageBox, "The scan screen was opened, but there is no valid frequency data for the selected feed.", MessageBox.TYPE_ERROR, timeout=5)
        except Exception as e:
            self.session.open(MessageBox, "Error launching scanner: " + str(e), MessageBox.TYPE_ERROR)
            
class FuryUpdater(Screen):
    skin = """
        <screen position="center,center" size="600,150" title="FuryBiss Update" backgroundColor="#151515">
            <widget source="progress" render="Progress" position="20,40" size="560,20" borderWidth="1" borderColor="#cccccc" backgroundColor="#222222" />
            <widget source="progresstext" render="Label" position="20,70" size="560,30" font="Regular;22" foregroundColor="#ffffff" backgroundColor="#151515" transparent="1" halign="center" />
        </screen>
    """
    def __init__(self, session, download_url, expected_version=None):
        Screen.__init__(self, session)
        self.download_url = download_url
        self.expected_version = _to_text(expected_version or "").strip()
        self["progress"] = Progress()
        self["progresstext"] = StaticText("Downloading update...")
        self.onLayoutFinish.append(self.startDownload)

    def startDownload(self):
        self.ipk_path = "/tmp/furybiss_update.ipk"
        self.dl = downloadWithProgress(self.download_url, self.ipk_path)
        self.dl.addProgress(self.downloadProgress)
        self.dl.start().addCallback(self.downloadFinished).addErrback(self.downloadFailed)

    def downloadProgress(self, recvbytes, totalbytes):
        percent = 0
        try:
            if totalbytes:
                percent = int(100 * recvbytes / float(totalbytes))
        except Exception:
            percent = 0
        self["progress"].value = percent
        self["progresstext"].text = "Downloading... %d%%" % percent

    def _run_cmd(self, cmd):
        try:
            process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            output = process.communicate()[0]
            code = process.returncode
            if PY3 and isinstance(output, bytes):
                output = output.decode('utf-8', 'ignore')
            elif not PY3 and not isinstance(output, str):
                try:
                    output = output.encode('utf-8')
                except Exception:
                    output = str(output)
            return code, output or ""
        except Exception as e:
            return 999, str(e)

    def _detect_installed_package_name(self):
        default_name = "enigma2-plugin-extensions-furybiss"
        code, output = self._run_cmd("opkg list-installed | grep -i 'furybiss'")
        if code == 0 and output:
            for line in output.splitlines():
                line = line.strip()
                if not line:
                    continue
                package_name = line.split(" - ", 1)[0].strip()
                if package_name:
                    return package_name
        return default_name

    def downloadFinished(self, result):
        package_name = self._detect_installed_package_name()

        self["progress"].value = 55
        self["progresstext"].text = "Removing old version, please wait..."
        remove_cmd = "opkg remove --force-depends '%s'" % package_name
        remove_code, remove_output = self._run_cmd(remove_cmd)

        remove_failed = remove_code != 0 and "Cannot find package" not in remove_output and "No packages removed" not in remove_output
        if remove_failed:
            message = "Failed to remove old version first.\n\nCommand output:\n%s" % (remove_output[-1200:] or "Unknown error")
            self.session.openWithCallback(self.close, MessageBox, message, MessageBox.TYPE_ERROR)
            return

        _cleanup_plugin_bytecode()
        try:
            self._run_cmd("sync")
        except Exception:
            pass

        self["progress"].value = 80
        self["progresstext"].text = "Installing new version, please wait..."
        install_cmd = "opkg install --force-reinstall --force-overwrite '%s'" % self.ipk_path
        code, output = self._run_cmd(install_cmd)

        try:
            self._run_cmd("sync")
        except Exception:
            pass

        _cleanup_plugin_bytecode()
        installed_version = _read_installed_plugin_version()

        if code != 0:
            message = "Update installation failed after removing old version.\n\nCommand output:\n%s" % (output[-1200:] or "Unknown error")
            self.session.openWithCallback(self.close, MessageBox, message, MessageBox.TYPE_ERROR)
            return

        if self.expected_version and _ver_tuple(installed_version) < _ver_tuple(self.expected_version):
            message = (
                "The old version was removed and the package was installed, but FuryBiss version on disk is still %s instead of %s.\n\n"
                "This usually means the IPK on the server was built with an old PLUGIN_VERSION or old files inside the package.\n\n"
                "Installer output:\n%s"
            ) % (installed_version or "Unknown", self.expected_version, output[-900:] or "No output")
            self.session.openWithCallback(self.close, MessageBox, message, MessageBox.TYPE_ERROR)
            return

        self["progress"].value = 100
        success_version = installed_version or self.expected_version or "updated"
        message = "Old version removed successfully. Installed version: %s\nDo you want to restart GUI now?" % success_version
        self.session.openWithCallback(self.restartGUI, MessageBox, message, MessageBox.TYPE_YESNO)

    def downloadFailed(self, error):
        self.session.openWithCallback(self.close, MessageBox, "Download failed!\n" + str(error), MessageBox.TYPE_ERROR)

    def restartGUI(self, answer):
        if answer:
            self.session.open(TryQuitMainloop, 3)
        else:
            self.close()
            
class FuryBisPathBrowser(Screen):
    skin = """
        <screen position="center,center" size="820,560" title="Choose key file location">
            <widget name="current_path" position="20,20" size="780,30" font="Regular;22" halign="left" valign="center" />
            <widget name="help" position="20,58" size="780,24" font="Regular;18" halign="left" valign="center" />
            <widget name="filelist" position="20,95" size="780,355" scrollbarMode="showOnDemand" />
            <widget name="preview" position="20,465" size="780,28" font="Regular;20" halign="left" valign="center" />
            <widget name="key_red" position="20,510" size="170,40" backgroundColor="red" font="Regular;20" halign="center" valign="center" />
            <widget name="key_green" position="210,510" size="230,40" backgroundColor="green" font="Regular;20" halign="center" valign="center" />
            <widget name="key_yellow" position="460,510" size="340,40" backgroundColor="yellow" foregroundColor="black" font="Regular;20" halign="center" valign="center" />
        </screen>
    """

    def __init__(self, session, start_path=None):
        Screen.__init__(self, session)
        self.base_path = BASE_CONFIG_DIR
        self.current_path = self._sanitize_start_path(start_path)
        self.entries = []
        self["current_path"] = Label("")
        self["help"] = Label("OK: open folder or choose file   Green: save selected path   Red: cancel")
        self["filelist"] = MenuList([])
        self["preview"] = Label("")
        self["key_red"] = Button("Cancel")
        self["key_green"] = Button("Save selected")
        self["key_yellow"] = Button("Save current folder as %s" % DEFAULT_KEY_FILE)
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "DirectionActions"], {
            "ok": self.keyOk, "cancel": self.keyCancel, "red": self.keyCancel, "green": self.keySaveSelected,
            "yellow": self.keySaveCurrentFolder, "up": self.keyUp, "down": self.keyDown, "left": self.keyPageUp, "right": self.keyPageDown,
        }, -2)
        self.refreshList()

    def _sanitize_start_path(self, path):
        path = os.path.normpath(path or self.base_path)
        if os.path.isdir(path): candidate = path
        else: candidate = os.path.dirname(path)
        if candidate != self.base_path and not candidate.startswith(self.base_path + os.sep): candidate = self.base_path
        return candidate

    def _current_selection_index(self):
        try: return self["filelist"].getSelectionIndex()
        except: return 0

    def _get_current_entry(self):
        index = self._current_selection_index()
        if 0 <= index < len(self.entries): return self.entries[index]
        return None

    def refreshList(self):
        self.entries = []
        if self.current_path != self.base_path:
            parent = os.path.dirname(self.current_path)
            if parent != self.base_path and not parent.startswith(self.base_path + os.sep): parent = self.base_path
            self.entries.append({"display": "[..] Parent directory", "path": parent, "is_dir": True})
        names = []
        try: names = sorted(os.listdir(self.current_path), key=lambda value: value.lower())
        except: names = []
        for name in names:
            full_path = os.path.join(self.current_path, name)
            if os.path.isdir(full_path): self.entries.append({"display": "[DIR] %s/" % name, "path": full_path, "is_dir": True})
        for name in names:
            full_path = os.path.join(self.current_path, name)
            if os.path.isfile(full_path): self.entries.append({"display": name, "path": full_path, "is_dir": False})
        if not self.entries: self.entries.append({"display": "<empty folder>", "path": self.current_path, "is_dir": True})
        self["filelist"].setList([entry["display"] for entry in self.entries])
        self.updateLabels()

    def updateLabels(self):
        self["current_path"].setText("Current folder: %s" % self.current_path)
        entry = self._get_current_entry()
        if entry is None: preview_path = os.path.join(self.current_path, DEFAULT_KEY_FILE)
        elif entry["is_dir"]: preview_path = os.path.join(entry["path"], DEFAULT_KEY_FILE)
        else: preview_path = entry["path"]
        self["preview"].setText("Will save to: %s" % preview_path)

    def keyUp(self):
        self["filelist"].up()
        self.updateLabels()

    def keyDown(self):
        self["filelist"].down()
        self.updateLabels()

    def keyPageUp(self):
        self["filelist"].pageUp()
        self.updateLabels()

    def keyPageDown(self):
        self["filelist"].pageDown()
        self.updateLabels()

    def keyOk(self):
        entry = self._get_current_entry()
        if entry is None: return
        if entry["is_dir"]:
            self.current_path = entry["path"]
            self.refreshList()
        else: self.close(entry["path"])

    def keySaveSelected(self):
        entry = self._get_current_entry()
        if entry is None: target = os.path.join(self.current_path, DEFAULT_KEY_FILE)
        elif entry["is_dir"]: target = os.path.join(entry["path"], DEFAULT_KEY_FILE)
        else: target = entry["path"]
        self.close(target)

    def keySaveCurrentFolder(self):
        self.close(os.path.join(self.current_path, DEFAULT_KEY_FILE))

    def keyCancel(self):
        self.close(None)

class FuryChannelInfoScreen(Screen):
    # New design based on a dark theme with elegant golden touches
    skin = """
        <screen position="center,center" size="700,450" title="Channel Info" flags="wfNoBorder" backgroundColor="#151515">
            <eLabel position="0,0" size="700,60" backgroundColor="#222222" zPosition="-1"/>
            <eLabel position="0,58" size="700,2" backgroundColor="#ffcc00" zPosition="1"/>
            <widget name="title_label" position="0,0" size="700,60" font="Regular;32" foregroundColor="#ffcc00" backgroundColor="#222222" halign="center" valign="center" transparent="1" />
            
            <widget name="lbl_channel" position="40,90" size="220,40" font="Regular;26" foregroundColor="#ffcc00" backgroundColor="#151515" transparent="1" halign="left" />
            <widget name="val_channel" position="270,90" size="400,40" font="Regular;26" foregroundColor="#ffffff" backgroundColor="#151515" transparent="1" halign="left" />

            <widget name="lbl_sat" position="40,150" size="220,40" font="Regular;26" foregroundColor="#ffcc00" backgroundColor="#151515" transparent="1" halign="left" />
            <widget name="val_sat" position="270,150" size="400,40" font="Regular;26" foregroundColor="#ffffff" backgroundColor="#151515" transparent="1" halign="left" />

            <widget name="lbl_freq" position="40,210" size="220,40" font="Regular;26" foregroundColor="#ffcc00" backgroundColor="#151515" transparent="1" halign="left" />
            <widget name="val_freq" position="270,210" size="400,40" font="Regular;26" foregroundColor="#ffffff" backgroundColor="#151515" transparent="1" halign="left" />

            <widget name="lbl_sid" position="40,270" size="220,40" font="Regular;26" foregroundColor="#ffcc00" backgroundColor="#151515" transparent="1" halign="left" />
            <widget name="val_sid" position="270,270" size="400,40" font="Regular;26" foregroundColor="#ffffff" backgroundColor="#151515" transparent="1" halign="left" />

            <widget name="lbl_key" position="40,330" size="220,40" font="Regular;26" foregroundColor="#ffcc00" backgroundColor="#151515" transparent="1" halign="left" />
            <widget name="val_key" position="270,330" size="400,40" font="Regular;26" foregroundColor="#00ff00" backgroundColor="#151515" transparent="1" halign="left" />

            <widget name="key_red" position="250,390" size="200,45" backgroundColor="#8b0000" foregroundColor="#ffffff" font="Regular;24" halign="center" valign="center" />
        </screen>
    """

    def __init__(self, session):
        Screen.__init__(self, session)
        
        self["title_label"] = Label("Channel Info")
        
        self["lbl_channel"] = Label("Channel Name:")
        self["lbl_sat"] = Label("Satellite:")
        self["lbl_freq"] = Label("Frequency:")
        self["lbl_sid"] = Label("SID (Hex):")
        self["lbl_key"] = Label("Current Key:")

        self["val_channel"] = Label("Loading...")
        self["val_sat"] = Label("--")
        self["val_freq"] = Label("--")
        self["val_sid"] = Label("--")
        self["val_key"] = Label("--")

        self["key_red"] = Button("Close")

        self["actions"] = ActionMap(["OkCancelActions", "ColorActions"], {
            "red": self.close,
            "cancel": self.close,
            "ok": self.close,
        }, -2)

        self.onLayoutFinish.append(self.loadInfo)

    def loadInfo(self):
        try:
            # Basic channel information
            info = plugin_get_current_channel()
            storage_path = get_storage_path()
            current_key = plugin_get_current_biss_key(info, storage_path)

            name = info.get("name", "Unknown")
            sid = info.get("sid", "0000")
            freq_val = info.get("freq", "")
            
            # --- Get the full frequency (frequency, polarization, symbol rate) ---
            freq_display = freq_val + " MHz" if freq_val else "Unknown"
            try:
                import NavigationInstance
                nav_instance = getattr(NavigationInstance, "instance", None)
                if nav_instance:
                    service = nav_instance.getCurrentlyPlayingServiceReference()
                    if service:
                        from enigma import eServiceCenter, iServiceInformation
                        info_center = eServiceCenter.getInstance().info(service)
                        if info_center:
                            tp_data = info_center.getInfoObject(service, iServiceInformation.sTransponderData)
                            if tp_data:
                                f_val = int(tp_data.get("frequency", 0) / 1000)
                                sr_val = int(tp_data.get("symbol_rate", 0) / 1000)
                                pol = tp_data.get("polarization", 0)
                                # Determine polarization
                                pol_str = "H" if pol == 0 else "V" if pol == 1 else "L" if pol == 2 else "R" if pol == 3 else "?"
                                
                                # Build the full frequency string
                                if f_val > 0 and sr_val > 0:
                                    freq_display = "%d %s %d" % (f_val, pol_str, sr_val)
            except Exception as e:
                pass
            # ---------------------------------------------------------

            # Calculate the satellite position and name
            namespace = info.get("namespace", "00000000")
            orbital = "Unknown"
            try:
                ns = int(namespace, 16)
                if ns != 0:
                    orb = ns >> 16
                    if orb != 0xFFFF and orb != 0xEEEE:
                        if orb > 1800:
                            orb_calc = 3600 - orb
                            orbital = "%.1f° W" % (orb_calc / 10.0)
                        else:
                            orbital = "%.1f° E" % (orb / 10.0)
            except:
                pass

            self["val_channel"].setText(name)
            self["val_sat"].setText(orbital)
            self["val_freq"].setText(freq_display)
            self["val_sid"].setText(sid.upper())
            
            # Format the key with spacing for readability 
            if current_key and current_key != "Not Found":
                formatted_key = " ".join([current_key[i:i+4] for i in range(0, len(current_key), 4)])
                self["val_key"].setText(formatted_key)
            else:
                self["val_key"].setText("Not Found")
                
        except Exception as e:
            self["val_channel"].setText("Error: " + str(e))
            

class FuryBissMaintenanceScreen(Screen):
    skin = """
        <screen position="center,center" size="820,440" title="FuryBiss Proxy &amp; Cleanup Tools" backgroundColor="#151515">
            <widget name="title" position="20,20" size="780,35" font="Regular;26" foregroundColor="#ffcc00" backgroundColor="#151515" transparent="1" halign="center" valign="center" />
            <widget name="list" position="40,75" size="740,220" scrollbarMode="showOnDemand" font="Regular;25" itemHeight="42" backgroundColor="#151515" foregroundColor="#ffffff" backgroundColorSelected="#001b3c85" foregroundColorSelected="#ffcc00" />
            <widget name="hint" position="40,310" size="740,42" font="Regular;21" foregroundColor="#cccccc" backgroundColor="#151515" transparent="1" halign="center" valign="center" />
            <widget name="key_red" position="60,370" size="200,45" backgroundColor="#8b0000" foregroundColor="#ffffff" font="Regular;22" halign="center" valign="center" cornerRadius="10" />
            <widget name="key_green" position="310,370" size="200,45" backgroundColor="#006400" foregroundColor="#ffffff" font="Regular;22" halign="center" valign="center" cornerRadius="10" />
            <widget name="key_yellow" position="560,370" size="200,45" backgroundColor="#b8860b" foregroundColor="#ffffff" font="Regular;22" halign="center" valign="center" cornerRadius="10" />
        </screen>
    """

    def __init__(self, session):
        Screen.__init__(self, session)
        self.actions_list = [
            ("Import proxy from proxy.txt", self.importProxyFromFile),
            ("Clear saved proxy from settings", self.confirmClearProxy),
            ("Delete FuryBiss keys from SoftCam.key", self.confirmClearFuryKeys),
            ("Delete daily feeds cache file", self.confirmClearFeedsCache),
            ("Delete opened feeds file (reset dots)", self.confirmClearOpenedFeeds),
        ]
        self["title"] = Label("Choose a tool")
        self["list"] = MenuList([item[0] for item in self.actions_list])
        self["hint"] = Label("OK: run selected tool   |   Green: Save & close   |   Red/Cancel: close")
        self["key_red"] = Button("Close")
        self["key_green"] = Button("Save")
        self["key_yellow"] = Button("Feeds Cache")
        self._maintenance_busy = False
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "DirectionActions"], {
            "ok": self.runSelected,
            "green": self.saveAndClose,
            "yellow": self.confirmClearFeedsCache,
            "red": self.close,
            "cancel": self.close,
            "up": self.keyUp,
            "down": self.keyDown,
            "left": self.keyPageUp,
            "right": self.keyPageDown,
        }, -2)

    def keyUp(self):
        self["list"].up()

    def keyDown(self):
        self["list"].down()

    def keyPageUp(self):
        self["list"].pageUp()

    def keyPageDown(self):
        self["list"].pageDown()

    def runSelected(self):
        if getattr(self, '_maintenance_busy', False):
            try:
                self.session.open(MessageBox, "Please wait, the current maintenance task is still running.", MessageBox.TYPE_INFO, timeout=3)
            except Exception:
                pass
            return
        index = 0
        try:
            index = self["list"].getSelectedIndex()
        except Exception:
            index = 0
        if 0 <= index < len(self.actions_list):
            self.actions_list[index][1]()

    def saveAndClose(self):
        try:
            if configfile:
                configfile.save()
        except Exception:
            pass
        self.session.openWithCallback(self._closeAfterDone, MessageBox, "Done", MessageBox.TYPE_INFO, timeout=2)

    def _closeAfterDone(self, *args):
        self.close()

    def importProxyFromFile(self):
        if not os.path.exists(PROXY_FILE):
            try:
                with open(PROXY_FILE, "w") as f:
                    f.write("https://your-proxy-url-here.workers.dev")
                self.session.open(MessageBox, "proxy.txt was created automatically in the plugin path.\nPlease open it, add your proxy URL, then open this menu and import again.", MessageBox.TYPE_INFO)
                return
            except Exception as e:
                self.session.open(MessageBox, "Error: Could not create proxy.txt automatically!\n" + str(e), MessageBox.TYPE_ERROR)
                return

        try:
            with open(PROXY_FILE, "r") as f:
                content = f.read().strip()

            if content == "https://your-proxy-url-here.workers.dev" or content == "":
                self.session.open(MessageBox, "Please open proxy.txt and write your proxy URL inside it first.", MessageBox.TYPE_WARNING)
            elif content.startswith("http"):
                config.plugins.furybiss.proxy_url.value = content
                config.plugins.furybiss.proxy_url.save()
                plugin_apply_proxy_runtime_change(clear_feed_cache=True)
                try:
                    plugin_get_proxy_connection_status(force=True)
                except Exception:
                    pass
                self.session.open(MessageBox, "Proxy imported successfully:\n" + content, MessageBox.TYPE_INFO, timeout=5)
            else:
                self.session.open(MessageBox, "Error: Invalid URL.\nIt must start with http or https", MessageBox.TYPE_ERROR)
        except Exception as e:
            self.session.open(MessageBox, "An error occurred while reading proxy.txt:\n" + str(e), MessageBox.TYPE_ERROR)

    def confirmClearProxy(self):
        message = "This will clear the saved proxy URL and remove proxy settings from /etc/enigma2/settings.\n\nContinue?"
        self.session.openWithCallback(self.clearProxy, MessageBox, message, MessageBox.TYPE_YESNO)

    def clearProxy(self, answer):
        if not answer:
            return
        removed_lines = plugin_clear_saved_proxy_settings()
        try:
            plugin_apply_proxy_runtime_change(clear_feed_cache=True)
        except Exception:
            pass
        message = "Saved proxy cleared successfully."
        if removed_lines > 0:
            message += "\nRemoved settings lines: %d" % removed_lines
        else:
            message += "\nNo saved proxy line was found in settings."
        self.session.open(MessageBox, message, MessageBox.TYPE_INFO, timeout=6)

    def confirmClearFuryKeys(self):
        message = "This will delete all SoftCam.key lines that contain:\nAdded by FuryBiss\n\nManual keys will stay untouched. Continue?"
        self.session.openWithCallback(self.clearFuryKeys, MessageBox, message, MessageBox.TYPE_YESNO)

    def clearFuryKeys(self, answer):
        if not answer:
            return
        if getattr(self, '_maintenance_busy', False):
            return

        self._maintenance_busy = True
        try:
            self["hint"].setText("Deleting FuryBiss keys in background...")
        except Exception:
            pass

        deferred = threads.deferToThread(plugin_clear_all_furybiss_keys)
        deferred.addCallback(self._clearFuryKeysDone)
        deferred.addErrback(self._clearFuryKeysError)

    def _clearFuryKeysDone(self, result):
        self._maintenance_busy = False
        try:
            self["hint"].setText("OK: run selected tool   |   Green: Save & close   |   Red/Cancel: close")
        except Exception:
            pass

        try:
            removed_count, modified_paths = result
        except Exception:
            removed_count, modified_paths = 0, []

        if removed_count > 0:
            message = "Deleted %d FuryBiss key line(s)." % removed_count
            if modified_paths:
                message += "\n\nUpdated file(s):\n" + "\n".join(modified_paths[:4])
        else:
            message = "No FuryBiss key lines were found."
        self.session.open(MessageBox, message, MessageBox.TYPE_INFO, timeout=7)

    def _clearFuryKeysError(self, failure):
        self._maintenance_busy = False
        try:
            self["hint"].setText("OK: run selected tool   |   Green: Save & close   |   Red/Cancel: close")
        except Exception:
            pass
        try:
            error_text = failure.getErrorMessage()
        except Exception:
            error_text = _to_text(failure)
        self.session.open(MessageBox, "Error deleting FuryBiss keys:\n%s" % error_text, MessageBox.TYPE_ERROR, timeout=7)

    def confirmClearFeedsCache(self):
        message = "This will delete the feeds cache file:\n%s\n\nContinue?" % _FEED_DISK_CACHE_FILE
        self.session.openWithCallback(self.clearFeedsCache, MessageBox, message, MessageBox.TYPE_YESNO)

    def clearFeedsCache(self, answer):
        if not answer:
            return
        removed_file = plugin_clear_feeds_cache_file()
        if removed_file:
            message = "Feeds cache file deleted successfully."
        else:
            message = "Feeds cache memory cleared. The cache file was not found."
        self.session.open(MessageBox, message, MessageBox.TYPE_INFO, timeout=6)

    def confirmClearOpenedFeeds(self):
        path_line = "\n%s" % _OPENED_FEEDS_FILE if _OPENED_FEEDS_FILE else ""
        message = ("This will reset all green/red dots (opened feeds list).%s\n\nContinue?" % path_line)
        self.session.openWithCallback(self.clearOpenedFeeds, MessageBox, message, MessageBox.TYPE_YESNO)

    def clearOpenedFeeds(self, answer):
        if not answer:
            return
        global global_opened_feeds
        global_opened_feeds = {}
        removed = False
        try:
            if _OPENED_FEEDS_FILE and os.path.exists(_OPENED_FEEDS_FILE):
                os.remove(_OPENED_FEEDS_FILE)
                removed = True
        except Exception:
            pass
        msg = "Dots reset successfully." if removed else "Dots cleared from memory (file not found on disk)."
        self.session.open(MessageBox, msg, MessageBox.TYPE_INFO, timeout=5)

class FuryBisSetup(Screen, ConfigListScreen):
    skin = """
        <screen position="500,190" size="980,700" title="FuryBiss v%s" backgroundColor="#151515">
            <widget name="config" position="29,10" size="920,245" itemHeight="35" font="Regular;28" scrollbarMode="showOnDemand" backgroundColor="#151515" foregroundColor="#ffcc00" backgroundColorSelected="#001b3c85" cornerRadius="10" />
            <eLabel text=" " position="30,258" size="920,2" backgroundColor="white" />
            <widget name="channel_info" position="30,263" size="920,35" font="Regular;26" foregroundColor="#00d2ff" halign="left" transparent="1" />
            <widget name="sid_info" position="30,301" size="460,30" font="Regular;22" foregroundColor="#ffffff" halign="left" transparent="1" />
            <widget name="freq_info" position="493,301" size="458,30" font="Regular;22" foregroundColor="#ffcc00" halign="left" transparent="1" />
            <widget name="key_info" position="30,336" size="920,30" font="Regular;22" foregroundColor="#00ff00" halign="left" transparent="1" />
            <eLabel text=" " position="30,375" size="920,2" backgroundColor="white" />
            <widget name="status_info" position="30,386" size="920,35" font="Regular;22" foregroundColor="#ffcc00" halign="left" transparent="1" />
            <widget name="ip_info" position="30,430" size="920,35" font="Regular;22" foregroundColor="#cccccc" halign="left" transparent="1" />
            <widget name="path_info" position="30,475" size="920,35" font="Regular;22" foregroundColor="#cccccc" halign="left" transparent="1" />
            <widget name="error_info" position="30,520" size="920,55" font="Regular;20" foregroundColor="#ff6666" halign="left" transparent="1" />
            <ePixmap pixmap="/usr/lib/enigma2/python/Plugins/Extensions/FuryBiss/icon/menu.png" position="30,583" size="170,38" alphatest="blend" zPosition="1" />
            <widget name="proxy_hint" position="72,588" size="95,24" font="Regular;21" foregroundColor="#ffffff" halign="center" valign="center" transparent="1" zPosition="2" />
            <ePixmap pixmap="/usr/lib/enigma2/python/Plugins/Extensions/FuryBiss/icon/info_hint.png" position="785,583" size="135,38" alphatest="blend" zPosition="1" />
            <widget name="info_hint" position="830,588" size="70,24" font="Regular;21" foregroundColor="#ffffff" backgroundColor="transparent" halign="center" valign="center" transparent="1" zPosition="2" />
            <widget name="key_red" position="50,640" size="200,45" backgroundColor="#8b0000" foregroundColor="#ffffff" font="Regular;22" halign="center" valign="center" cornerRadius="10" />
            <widget name="key_green" position="280,640" size="200,45" backgroundColor="#006400" foregroundColor="#ffffff" font="Regular;22" halign="center" valign="center" cornerRadius="10" />
            <widget name="key_yellow" position="510,640" size="200,45" backgroundColor="#b8860b" foregroundColor="#ffffff" font="Regular;22" halign="center" valign="center" cornerRadius="10" />
            <widget name="key_blue" position="740,640" size="200,45" backgroundColor="#00008b" foregroundColor="#ffffff" font="Regular;22" halign="center" valign="center" cornerRadius="10" />
        </screen>
    """ % _read_installed_plugin_version()

    def __init__(self, session):
        Screen.__init__(self, session)
        self.list = []
        self.pathChooserEntry = None
        self.runtime_status = {}
        
        self["channel_info"] = Label("Channel: Loading...")
        self["sid_info"] = Label("SID: --")
        self["freq_info"] = Label("Frequency: --") 
        self["key_info"] = Label("Current Key: --")
        
        self["status_info"] = Label("")
        self["ip_info"] = Label("")
        self["path_info"] = Label("")
        self["error_info"] = Label("")
        self["info_hint"] = Label("")
        self["proxy_hint"] = Label("")
        
        ConfigListScreen.__init__(self, self.list, session=session)
        self["key_red"] = Button("Cancel")
        self["key_green"] = Button("Save")
        self["key_yellow"] = Button("Feeds List")
        self["key_blue"] = Button("Check Update")
        
        self._pending_update_version = ""
        self._auto_biss_busy = False

        self["setupActions"] = ActionMap(["SetupActions", "ColorActions", "OkCancelActions", "DirectionActions", "EPGSelectActions", "InfobarEPGActions", "MenuActions", "NumberActions"], {
            "red": self.cancel,
            "green": self.save,
            "yellow": self.showFeedsList,
            "blue": self.checkUpdate,
            "info": self.showChannelInfo,
            "showEventInfo": self.showChannelInfo,
            "menu": self.openMaintenanceTools,
            "save": self.save,
            "cancel": self.cancel,
            "left": self.keyLeft,
            "right": self.keyRight,
            "ok": self.keyOk,
        }, -2)
        
        self.refreshRuntimeStatus(start_if_needed=True, force_test=True)
        self.createSetup()
        self.updateChannelDisplay()


    def openMaintenanceTools(self):
        self.session.openWithCallback(self._afterMaintenanceTools, FuryBissMaintenanceScreen)

    def _afterMaintenanceTools(self, *args):
        try:
            self.refreshRuntimeStatus(force_test=False)
            self.updateInfo()
        except Exception:
            pass

    def importProxyFromFile(self):
        # 1. Check whether the file exists; if not, create it automatically
        if not os.path.exists(PROXY_FILE):
            try:
                # Create the file and write a placeholder text inside it
                with open(PROXY_FILE, "w") as f:
                    f.write("https://your-proxy-url-here.workers.dev")
                
                self.session.open(MessageBox, "proxy.txt was created automatically in the plugin path.\nPlease open it, add your proxy URL, then open MENU and import again.", MessageBox.TYPE_INFO)
                return # Stop the function here so the user can write the URL first
            except Exception as e:
                self.session.open(MessageBox, "Error: Could not create the file automatically!\n" + str(e), MessageBox.TYPE_ERROR)
                return

        # 2. If the file already exists, read its contents normally
        try:
            with open(PROXY_FILE, "r") as f:
                content = f.read().strip()
            
            # Make sure the user did not leave the placeholder text unchanged and actually added a URL
            if content == "https://your-proxy-url-here.workers.dev" or content == "":
                self.session.open(MessageBox, "Please open proxy.txt and write your proxy URL inside it first.", MessageBox.TYPE_WARNING)
            elif content.startswith("http"):
                # Save the URL in settings
                config.plugins.furybiss.proxy_url.value = content
                config.plugins.furybiss.proxy_url.save()
                if configfile:
                    configfile.save()
                
                self.session.open(MessageBox, "Proxy imported successfully:\n" + content, MessageBox.TYPE_INFO, timeout=5)
            else:
                self.session.open(MessageBox, "Error: Invalid URL.\nIt must start with http or https", MessageBox.TYPE_ERROR)
        except Exception as e:
            self.session.open(MessageBox, "An error occurred while reading the file:\n" + str(e), MessageBox.TYPE_ERROR)

    def updateChannelDisplay(self):
        try:
            info = plugin_get_current_channel()
            storage_path = get_storage_path()
            current_key = plugin_get_current_biss_key(info, storage_path)
            
            freq_val = info.get("freq", "")
            freq_display = (freq_val + " MHz") if freq_val else "Unknown"
            
            self["channel_info"].setText("Channel: %s" % info.get("name", "Unknown"))
            self["sid_info"].setText("SID (Hex): %s" % info.get("sid", "0000"))
            self["freq_info"].setText("Frequency: %s" % freq_display)
            self["key_info"].setText("Current Key: %s" % current_key)
        except Exception as e:
            self["error_info"].setText("Display Error: %s" % str(e))

    def _setupAutoFetchWorker(self, info):
        try:
            sid = info.get("sid", "0000")
            name = info.get("name", "Unknown")
            freq = info.get("freq", "")
            fetched_key = plugin_fetch_telegram_key(sid, name, freq)
            key_text = _to_text(fetched_key).strip()
            if not key_text:
                return {'status': 'not_found'}
            if key_text.startswith('ERROR'):
                return {'status': 'error', 'message': key_text}
            if key_text.upper() == 'FTA':
                return {'status': 'fta'}

            compact_key = plugin_compact_key_text(key_text) or key_text
            target_paths = get_storage_write_paths()
            lines, _ = build_biss_lines(info, compact_key)
            for path in target_paths:
                plugin_append_key_lines(path, lines)
            restart_ok = plugin_restart_active_emu()
            return {'status': 'success', 'key': compact_key, 'restart_ok': restart_ok}
        except Exception as error:
            return {'status': 'error', 'message': _to_text(error)}

    def _onSetupAutoFetchDone(self, result):
        self._auto_biss_busy = False
        if not isinstance(result, dict):
            result = {'status': 'error', 'message': _to_text(result)}
        status = result.get('status', '')
        if status == 'success':
            key_text = _to_text(result.get('key', '')).strip()
            message = "Success! Key Found and Applied:\n%s" % key_text
            if result.get('restart_ok') is False:
                message += "\n\nNote: EMU restart command was not confirmed."
            self.session.open(MessageBox, message, MessageBox.TYPE_INFO, timeout=5)
            self["error_info"].setText("Auto Fetch completed.")
            self.updateChannelDisplay()
        elif status == 'fta':
            self.session.open(MessageBox, "Free Channel", MessageBox.TYPE_INFO, timeout=5)
            self["error_info"].setText("Free Channel")
        elif status == 'not_found':
            self.session.open(MessageBox, "Key not found on Server for this Channel!", MessageBox.TYPE_ERROR)
            self["error_info"].setText("Auto Fetch Failed.")
        else:
            self.session.open(MessageBox, "Error applying key: %s" % _to_text(result.get('message', 'Unknown error')), MessageBox.TYPE_ERROR)
            self["error_info"].setText("Auto Fetch Error.")

    def _onSetupAutoFetchError(self, failure):
        self._auto_biss_busy = False
        self.session.open(MessageBox, "Error applying key: %s" % _to_text(failure), MessageBox.TYPE_ERROR)
        self["error_info"].setText("Auto Fetch Error.")

    def autoFetch(self):
        if getattr(self, '_auto_biss_busy', False):
            self.session.open(MessageBox, "Auto BISS is already running...", MessageBox.TYPE_INFO, timeout=3)
            return

        info = plugin_get_current_channel()
        sid = info.get("sid", "0000")
        name = info.get("name", "Unknown")
        freq = info.get("freq", "")

        self._auto_biss_busy = True
        self["error_info"].setText("Searching in background for: %s | %s | %s" % (name, freq, sid))

        try:
            deferred = threads.deferToThread(self._setupAutoFetchWorker, dict(info or {}))
            deferred.addCallback(self._onSetupAutoFetchDone)
            deferred.addErrback(self._onSetupAutoFetchError)
        except Exception as error:
            self._auto_biss_busy = False
            self.session.open(MessageBox, "Auto Fetch start error: %s" % _to_text(error), MessageBox.TYPE_ERROR)
            self["error_info"].setText("Auto Fetch Error.")

    def showFeedsList(self):
        self.session.open(FuryBissFeedsScreen)
        
    def showChannelInfo(self):
        self.session.open(FuryChannelInfoScreen)
            
    def createSetup(self):
        self.pathChooserEntry = getConfigListEntry("Choose key file location", NoSave(ConfigNothing()))
        self.updateCheckEntry = getConfigListEntry("Check Update Now", NoSave(ConfigNothing()))
        self.channelInfoEntry = getConfigListEntry("Channel Info", NoSave(ConfigNothing()))
        self.proxyToggleEntry = getConfigListEntry("Enable Proxy:", config.plugins.furybis.use_proxy)
        self.list = [
            getConfigListEntry("Enable FuryBiss plugin:", config.plugins.furybis.enabled),
            getConfigListEntry("Enable New Feeds Notifications:", config.plugins.furybis.notifications),
            getConfigListEntry("Feeds Source:", config.plugins.furybis.feed_source),
            self.proxyToggleEntry,
            self.pathChooserEntry,
            self.updateCheckEntry,
            self.channelInfoEntry,
        ]
        self["config"].list = self.list
        self["config"].l.setList(self.list)
        self.updateInfo()

    def refreshRuntimeStatus(self, start_if_needed=False, force_test=False):
        snapshot = {
            "enabled_setting": bool(config.plugins.furybis.enabled.value),
            "running": False,
            "primary_url": "http://127.0.0.1:8088",
            "self_test_ok": None,
            "self_test_message": "",
            "last_error": "",
            "last_request_at": "",
            "log_file": "/tmp/furybis_web.log",
        }
        try:
            if start_if_needed and config.plugins.furybis.enabled.value:
                from .web_server import ensure_server_state
                ensure_server_state()
                time.sleep(0.2)
            from .web_server import get_status_snapshot
            snapshot = get_status_snapshot(run_self_test=force_test)
        except Exception as error:
            snapshot["last_error"] = str(error)
        self.runtime_status = snapshot

    def updateInfo(self):
        status = self.runtime_status or {}
        desired_enabled = bool(config.plugins.furybis.enabled.value)
        running = bool(status.get("running"))
        primary_url = status.get("primary_url") or "http://127.0.0.1:8088"
        self_test_ok = status.get("self_test_ok")
        self_test_message = status.get("self_test_message") or ""

        # Get the expiration date from the smart activation file
        expire_date = "Lifetime"
        import time, os
        try:
            if os.path.exists("/etc/tuxbox/config/furybis.license"):
                with open("/etc/tuxbox/config/furybis.license", "r") as f:
                    code = f.read().strip()
                    if len(code) == 16:
                        expire_ts = int(code[:10])
                        expire_date = time.strftime('%Y-%m-%d  %I:%M %p', time.localtime(expire_ts))
        except:
            pass

        # Merge the expiration date with the plugin status
        if desired_enabled:
            plugin_status = "Plugin status: Enabled   |   VIP Expires: %s" % expire_date
            if running:
                if self_test_ok is True: ip_status = "IP/Web status: Connected - %s" % primary_url
                elif self_test_ok is False:
                    if self_test_message: ip_status = "IP/Web status: Disconnected - %s" % self_test_message
                    else: ip_status = "IP/Web status: Disconnected"
                else: ip_status = "IP/Web status: Starting - %s" % primary_url
            else: ip_status = "IP/Web status: Disconnected - server is not running"
        else:
            plugin_status = "Plugin status: Disabled   |   VIP Expires: %s" % expire_date
            if running: ip_status = "IP/Web status: Still running now, but it will stop after Save"
            else: ip_status = "IP/Web status: Disconnected"

        proxy_status = plugin_get_proxy_connection_status(force=False)
        self["status_info"].setText(plugin_status)
        self["ip_info"].setText("%s   |   %s" % (ip_status, proxy_status))
        plugin_set_widget_foreground(self["ip_info"], plugin_get_proxy_status_color(proxy_status))
        receiver_model = plugin_get_receiver_model()
        self["path_info"].setText("Active key file: %s   |   Receiver: %s" % (get_storage_path(), receiver_model))

        last_error = status.get("last_error") or ""
        if not last_error and desired_enabled and self_test_ok is False and self_test_message: last_error = self_test_message
        if last_error: footer = "Last error: %s" % last_error
        else:
            last_request = status.get("last_request_at") or "No web request yet"
            footer = "Last web request: %s\nLog file: %s" % (last_request, status.get("log_file") or "/tmp/furybis_web.log")
        self["error_info"].setText(footer)

    def _applyProxyToggleIfNeeded(self, current):
        try:
            if current == getattr(self, 'proxyToggleEntry', None):
                plugin_apply_proxy_runtime_change(clear_feed_cache=True)
        except Exception:
            pass

    def keyLeft(self):
        current = self["config"].getCurrent()
        if current != self.pathChooserEntry:
            ConfigListScreen.keyLeft(self)
            self._applyProxyToggleIfNeeded(current)
            self.refreshRuntimeStatus(force_test=False)
            self.updateInfo()

    def keyRight(self):
        current = self["config"].getCurrent()
        if current != self.pathChooserEntry:
            ConfigListScreen.keyRight(self)
            self._applyProxyToggleIfNeeded(current)
            self.refreshRuntimeStatus(force_test=False)
            self.updateInfo()

    def keyOk(self):
        current = self["config"].getCurrent()
        if current == self.pathChooserEntry:
            self.session.openWithCallback(self.onPathSelected, FuryBisPathBrowser, get_storage_path())
        elif current == self.updateCheckEntry:
            self.checkUpdate()
        elif current == self.channelInfoEntry:
            self.showChannelInfo()
        else:
            self.keyRight()

    def onPathSelected(self, selected_path):
        if selected_path:
            set_storage_path(selected_path)
            normalize_stored_values()
            self.refreshRuntimeStatus(force_test=False)
            self.updateInfo()

    def checkUpdate(self):
        local_version = _read_installed_plugin_version()
        remote_version = _read_remote_version()

        if not remote_version:
            self.session.open(MessageBox, "Update check failed. Could not read version.txt from GitHub.", MessageBox.TYPE_ERROR, timeout=6)
            return

        if _ver_tuple(remote_version) <= _ver_tuple(local_version):
            message = "Installed version: %s\nServer version: %s\n\nYou already have the latest version." % (local_version or "Unknown", remote_version)
            self.session.open(MessageBox, message, MessageBox.TYPE_INFO, timeout=7)
            return

        self._pending_update_version = remote_version
        message = "New version found.\n\nInstalled version: %s\nServer version: %s\n\nDo you want to download and install it now?" % (local_version or "Unknown", remote_version)
        self.session.openWithCallback(self._confirmUpdateInstall, MessageBox, message, MessageBox.TYPE_YESNO)

    def _confirmUpdateInstall(self, answer):
        if not answer:
            return
        command = _build_installer_command()
        if Console is not None:
            self.session.openWithCallback(self._afterUpdateInstaller, Console, title="FuryBiss Update", cmdlist=[command])
            return

        code, output = _run_shell_capture(command)
        self._afterUpdateInstaller((code, output))

    def _afterUpdateInstaller(self, result=None):
        installed_version = _read_installed_plugin_version()
        expected_version = _to_text(getattr(self, '_pending_update_version', '')).strip()
        if expected_version and _ver_tuple(installed_version) >= _ver_tuple(expected_version):
            message = "Update installed successfully.\nInstalled version: %s\n\nDo you want to restart GUI now?" % installed_version
            self.session.openWithCallback(self._restartAfterUpdate, MessageBox, message, MessageBox.TYPE_YESNO)
            return

        if expected_version and _ver_tuple(installed_version) < _ver_tuple(expected_version):
            message = "Update finished, but the installed version is still %s instead of %s.\n\nMake sure the new IPK and version.txt were uploaded to GitHub correctly." % (installed_version or "Unknown", expected_version)
            self.session.open(MessageBox, message, MessageBox.TYPE_ERROR, timeout=8)
            return

        self.session.open(MessageBox, "Update command finished.", MessageBox.TYPE_INFO, timeout=5)

    def _restartAfterUpdate(self, answer):
        if answer:
            self.session.open(TryQuitMainloop, 3)

    def save(self):
        normalize_stored_values()
        config.plugins.furybis.enabled.save()
        config.plugins.furybis.notifications.save()
        config.plugins.furybis.use_proxy.save()
        plugin_apply_proxy_runtime_change(clear_feed_cache=True)
        config.plugins.furybis.feed_source.save() 
        config.plugins.furybis.storage_relative_path.save()
        config.plugins.furybis.save()
        try: configfile.save()
        except: pass
        try:
            # Adjustment here too: prevent manual server start if the plugin is not activated
            if not REQUIRE_ACTIVATION or is_vip_active():
                from .web_server import ensure_server_state
                ensure_server_state()
        except: pass
        time.sleep(0.25)
        self.refreshRuntimeStatus(force_test=True)
        self.updateInfo()
        if config.plugins.furybis.enabled.value:
            if not self.runtime_status.get("running") or self.runtime_status.get("self_test_ok") is False: return
        self.close()

    def cancel(self):
        config.plugins.furybis.enabled.cancel()
        config.plugins.furybis.notifications.cancel()
        config.plugins.furybis.use_proxy.cancel()
        plugin_apply_proxy_runtime_change(clear_feed_cache=True)
        config.plugins.furybis.feed_source.cancel()        
        config.plugins.furybis.storage_relative_path.cancel()
        self.close()


# =================================================================
# Smart time-based activation system (Time-Based VIP Activation)
# =================================================================

def verify_vip_code(entered_code, device_id):
    import time
    import hashlib
    import sys
    
    # The code must be 16 digits
    if not entered_code or len(entered_code) != 16 or not entered_code.isdigit():
        return False, "Invalid Code Format! Must be 16 digits."
        
    expire_timestamp_str = entered_code[:10]
    verification_pin = entered_code[10:]
    
    try:
        expire_timestamp = int(expire_timestamp_str)
    except:
        return False, "Invalid Code Data."
        
    # Rebuild the signature to verify that the client did not forge a code
    SECRET_KEY = "FuryBiss2026_VIP" # Must match your script
    raw_string = "{0}-{1}-{2}".format(device_id, expire_timestamp, SECRET_KEY)
    
    # Support Python 2 and Python 3 in hashing
    if sys.version_info[0] >= 3:
        hash_hex = hashlib.md5(raw_string.encode('utf-8')).hexdigest()
    else:
        hash_hex = hashlib.md5(raw_string).hexdigest()
        
    expected_pin = str(int(hash_hex, 16))[:6].zfill(6)
    
    if expected_pin != verification_pin:
        return False, "Code is fake or for another device!"
        
    # Check the expiration date
    current_time = int(time.time())
    if current_time > expire_timestamp:
        return False, "This subscription has expired!"
        
    return True, "Subscription Active"


from Components.ActionMap import NumberActionMap

from Components.ActionMap import NumberActionMap

class FuryBisActivationScreen(Screen):
    skin = """
        <screen position="center,center" size="650,420" title="FuryBiss VIP Activation" backgroundColor="#151515">
            <widget name="info1" position="20,20" size="610,35" font="Regular;26" foregroundColor="#ff4444" backgroundColor="#151515" transparent="1" halign="center" valign="center" />
            <widget name="info2" position="20,70" size="610,45" font="Regular;32" foregroundColor="#ffff00" backgroundColor="#151515" transparent="1" halign="center" valign="center" />
            <widget name="info3" position="20,135" size="610,30" font="Regular;22" foregroundColor="#ffffff" backgroundColor="#151515" transparent="1" halign="center" valign="center" />
            
            <eLabel position="125,185" size="400,50" backgroundColor="#222222" zPosition="-1" />
            <widget name="code_display" position="125,185" size="400,50" font="Regular;32" foregroundColor="#00ff00" backgroundColor="#222222" halign="center" valign="center" transparent="0" />
            
            <widget name="contact" position="20,255" size="610,35" font="Regular;24" foregroundColor="#25D366" backgroundColor="#151515" transparent="1" halign="center" valign="center" />
            
            <widget name="key_red" position="60,345" size="200,45" backgroundColor="#aa0000" font="Regular;22" halign="center" valign="center" />
            <widget name="key_green" position="390,345" size="200,45" backgroundColor="#00aa00" font="Regular;22" halign="center" valign="center" />
        </screen>
    """

    def __init__(self, session, device_id, license_file):
        Screen.__init__(self, session)
        self.device_id = device_id
        self.license_file = license_file
        self.entered_code = ""
        
        self["info1"] = Label("Plugin is Locked! VIP Activation Required")
        self["info2"] = Label("Device ID: %s" % self.device_id)
        self["info3"] = Label("Type the 16-digit code using remote numbers.")
        
        # Contact information line
        self["contact"] = Label("Contact the developer (WhatsApp): +201031546267")
        
        self["code_display"] = Label("Type Code Here...")
        self["key_red"] = Button("Exit")
        self["key_green"] = Button("Activate")
        
        self["actions"] = ActionMap(["SetupActions", "ColorActions", "OkCancelActions", "DirectionActions"], {
            "red": self.cancel,
            "green": self.activate,
            "cancel": self.cancel,
            "ok": self.activate,
            "left": self.deleteLastChar,
        }, -2)
        
        self["NumberActions"] = NumberActionMap(["NumberActions"], {
            "1": self.keyNumberGlobal, "2": self.keyNumberGlobal, "3": self.keyNumberGlobal,
            "4": self.keyNumberGlobal, "5": self.keyNumberGlobal, "6": self.keyNumberGlobal,
            "7": self.keyNumberGlobal, "8": self.keyNumberGlobal, "9": self.keyNumberGlobal,
            "0": self.keyNumberGlobal
        })

    def keyNumberGlobal(self, number):
        if len(self.entered_code) < 16:
            self.entered_code += str(number)
            self.updateDisplay()

    def deleteLastChar(self):
        if len(self.entered_code) > 0:
            self.entered_code = self.entered_code[:-1]
            self.updateDisplay()

    def updateDisplay(self):
        if len(self.entered_code) == 0:
            self["code_display"].setText("Type Code Here...")
        else:
            formatted_code = " ".join([self.entered_code[i:i+4] for i in range(0, len(self.entered_code), 4)])
            self["code_display"].setText(formatted_code)

    def activate(self):
        if len(self.entered_code) != 16:
            self.session.open(MessageBox, "Code must be exactly 16 digits!", MessageBox.TYPE_ERROR)
            return
            
        is_valid, message = verify_vip_code(self.entered_code, self.device_id)
        
        if is_valid:
            try:
                import os
                with open(self.license_file, 'w') as f: f.write(self.entered_code)
                os.system("sync")
                self.session.open(MessageBox, "Activation Successful!\nEnjoy FuryBiss VIP.", MessageBox.TYPE_INFO, timeout=5)
                self.close(True) 
            except Exception as e:
                self.session.open(MessageBox, "Error saving license: " + str(e), MessageBox.TYPE_ERROR)
        else:
            self.session.open(MessageBox, "Activation Failed!\n" + message, MessageBox.TYPE_ERROR)

    def cancel(self):
        self.close(False)

# =================================================================
# General activation functions (Global VIP Checks)
# =================================================================
def get_device_id():
    try:
        with open('/sys/class/net/eth0/address', 'r') as f:
            mac = f.read().strip().replace(':', '').upper()
            if len(mac) >= 6: return mac[-6:]
    except: pass
    return "1A2B3C" 

def is_vip_active():
    import os
    license_file = "/etc/tuxbox/config/furybis.license"
    try:
        if os.path.exists(license_file):
            with open(license_file, 'r') as f:
                saved_code = f.read().strip()
                is_valid, _ = verify_vip_code(saved_code, get_device_id())
                return is_valid
    except: pass
    return False



# Keep the variable global outside the function: True & False
REQUIRE_ACTIVATION = False 
# --- Main interface ---
def main(session, **kwargs):
    plugin_set_runtime_session(session)
    device_id = get_device_id()
    license_file = "/etc/tuxbox/config/furybis.license"

    # =======================================================
    # New addition: delete the activation file if the plugin becomes free
    # =======================================================
    import os
    if not REQUIRE_ACTIVATION:
        try:
            if os.path.exists(license_file):
                os.remove(license_file)
                os.system("sync") # Confirm deletion from memory
        except:
            pass
    # =======================================================

    def activation_callback(success):
        if success:
            # Start the web server automatically after successful activation
            try:
                from .web_server import ensure_server_state
                ensure_server_state()
            except: pass

            plugin_ensure_daily_cleaner_started()
            plugin_ensure_notifier_started()
            session.open(FuryBissFeedsScreen)

    if not REQUIRE_ACTIVATION or is_vip_active():
        plugin_ensure_daily_cleaner_started()
        plugin_ensure_notifier_started()
        session.open(FuryBissFeedsScreen)
    else: 
        session.openWithCallback(activation_callback, FuryBisActivationScreen, device_id, license_file)

class FuryBissNotificationScreen(Screen):
    skin = """
        <screen position="710,18" size="500,80" flags="wfNoBorder" backgroundColor="#1c1c1e" zPosition="200" cornerRadius="20">
            <!-- accent bar -->
            <eLabel position="14,10" size="5,60" backgroundColor="#4da6ff" cornerRadius="2" zPosition="1" />
            <!-- app name row: bold white title -->
            <widget name="title" position="26,6" size="340,30" font="Bold;22" foregroundColor="#ffffff" backgroundColor="#1c1c1e" transparent="1" halign="left" valign="center" zPosition="1" />
            <!-- time: white -->
            <widget name="published" position="356,6" size="132,30" font="Regular;20" foregroundColor="#ffffff" backgroundColor="#1c1c1e" transparent="1" halign="right" valign="center" zPosition="1" />
            <!-- thin separator -->
            <eLabel position="26,40" size="460,1" backgroundColor="#38383a" zPosition="1" />
            <!-- satellite name -->
            <widget name="satellite" position="26,44" size="462,30" font="Regular;26" foregroundColor="#c8ff8c" backgroundColor="#1c1c1e" transparent="1" halign="left" valign="center" zPosition="1" />
        </screen>
    """

    def __init__(self, session, feed=None, timeout=6):
        Screen.__init__(self, session)
        self._fury_session = session
        self._fury_closed = False
        feed = feed or {}

        sat_raw = _to_text(feed.get('sat', '')).strip()
        sat_pos = plugin_extract_sat_position_text(sat_raw) if sat_raw else ''
        sat_name = ''
        if sat_pos:
            sat_name = plugin_get_enigma2_sat_name(sat_pos)
        if not sat_name:
            sat_name = sat_pos or sat_raw or 'Unknown satellite'

        import time as _t
        self['title'] = Label('FuryBiss  •  New Feed')
        self['satellite'] = Label(sat_name)
        self['published'] = Label(_t.strftime('%H:%M'))
        self.closeTimer = eTimer()
        try:
            self.closeTimer.timeout.connect(self.closeTimerFired)
        except:
            self.closeTimer.callback.append(self.closeTimerFired)
        try:
            self.onClose.append(self._cleanup_active_reference)
        except:
            pass
        self.closeTimer.start(max(1, int(timeout)) * 1000, True)

        # Allow user to dismiss notification via remote (OK / Exit / Cancel)
        self["dismissActions"] = ActionMap(
            ["OkCancelActions", "ColorActions"],
            {
                "ok":     self.dismiss,
                "cancel": self.dismiss,
            },
            prio=-1,
        )

    def _cleanup_active_reference(self):
        try:
            if globals().get('_furybiss_active_notification') is self:
                globals()['_furybiss_active_notification'] = None
        except:
            pass

    def dismiss(self):
        if getattr(self, '_fury_closed', False):
            return
        self._fury_closed = True
        try:
            self.closeTimer.stop()
        except:
            pass
        self._cleanup_active_reference()

        # instantiateDialog().show() is not always removed by close() on all images.
        # Hide first, then delete the dialog from the session so the overlay really disappears.
        try:
            self.hide()
        except:
            pass
        try:
            session = getattr(self, '_fury_session', None) or getattr(self, 'session', None)
            if session is not None and hasattr(session, 'deleteDialog'):
                session.deleteDialog(self)
                return
        except:
            pass
        try:
            self.close()
        except:
            pass

    def closeTimerFired(self):
        self.dismiss()


def plugin_strip_html_message(raw_html):
    text = _to_text(raw_html)
    try:
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    except:
        text = text.replace('<br/>', '\n').replace('<br>', '\n')
    text = re.sub(r'</div\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&quot;', '"').replace('&#39;', "'")
    cleaned_lines = []
    for line in text.split('\n'):
        line = u' '.join(_to_text(line).split())
        if line:
            cleaned_lines.append(line)
    return '\n'.join(cleaned_lines).strip()


def plugin_extract_feed_meta_from_text(text):
    text = _to_text(text)
    raw_key = plugin_extract_key_value(text)

    freq_val = ''
    pol_val = ''
    sr_val = ''
    freq_str = 'Unknown'
    # Pattern 1: with separators e.g. "12028 V 4899" or "12028/V/4899"
    freq_pattern = r'\b(\d{4,5})[\s:/\-\|]+(v|h|ver|hor|vertical|horizontal)[\s:/\-\|]+(\d{3,5}(?:\.\d+)?)\b'
    freq_match = re.search(freq_pattern, text, re.IGNORECASE)
    # Pattern 2: compact format without separators e.g. "12028V4899"
    if not freq_match:
        freq_match = re.search(r'(?<!\d)(\d{4,5})([VHvh])(\d{3,5})(?!\d)', text)
    if freq_match:
        freq_val = freq_match.group(1)
        pol_raw = freq_match.group(2).upper()
        pol_val = 'H' if pol_raw.startswith('H') else 'V'
        sr_raw = freq_match.group(3)
        try:
            sr_val = str(int(float(sr_raw)))
        except:
            sr_val = sr_raw
        freq_str = '%s %s %s' % (freq_val, pol_val, sr_val)

    sat = 'Unknown'
    sat_match = re.search(r'(?:Sat|Satellite|%s)[\s:\-]*([^\n]+)' % re.escape(AR_SATELLITE_LABEL), text, re.IGNORECASE)
    if sat_match:
        sat = sat_match.group(1).strip()
    else:
        orb_match = re.search(r'^.*?\b\d{1,3}(?:\.\d+)?\s*[°]?\s*[EWew]\b.*?$', text, re.MULTILINE)
        if orb_match:
            sat = orb_match.group(0).strip()

    feed_type = plugin_extract_feed_type(text) or 'Unknown'

    # --- التعديل: إعطاء الأولوية لاسم الـ Event، ثم السطر الذي يسبق القمر ---
    name = plugin_extract_event_name_from_info(text, freq_val)
    
    if not name or plugin_is_generic_feed_name(name, freq_val):
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        sat_index = -1
        
        # البحث عن رقم السطر الذي يحتوي على القمر
        for i, line in enumerate(lines):
            if (sat != 'Unknown' and sat in line) or re.search(r'\b\d{1,3}(?:\.\d+)?\s*[°]?\s*[EWew]\b', line):
                sat_index = i
                break
        
        if sat_index > 0:
            # جلب السطر الذي يسبق القمر
            name = lines[sat_index - 1]
            # تجاهل الأسماء الافتراضية مثل Biss Feed والنزول للسطر الذي قبله
            if name.lower() in ('biss feed', 'feed', 'new feed', 'live feed') and sat_index > 1:
                name = lines[sat_index - 2]
        else:
            name = lines[0] if lines else 'Feed Unknown'
            
        if name.lower() in ('biss feed', 'feed', 'new feed', 'live feed'):
            name_match = re.search(r'(?:Ch|Channel|%s|%s|%s)[\s:\-]*([^\n]+)' % (re.escape(AR_CHANNEL_LABEL), re.escape(AR_FEED_NAME_LABEL), re.escape(AR_CHANNEL_NAME_LABEL)), text, re.IGNORECASE)
            if name_match:
                name = name_match.group(1).strip()
    # -------------------------------------------------------------

    return {
        'name': name,
        'sat': sat,
        'freq_str': freq_str,
        'freq_val': freq_val,
        'pol_val': pol_val,
        'sr_val': sr_val,
        'feed_type': feed_type,
        'key': raw_key,
        'full_text': text,
    }

def plugin_parse_telegram_message(raw_message):
    if not raw_message:
        return None

    post_id = plugin_extract_telegram_post_id(raw_message)

    # Use only the original publish time to ignore later edits
    time_match = re.search(r'<time datetime="([^"]+)"', raw_message, re.IGNORECASE)
    if not time_match:
        return None

    raw_datetime = _to_text(time_match.group(1)).strip()
    timestamp = plugin_parse_telegram_datetime_to_timestamp(raw_datetime)
    source_day_key = plugin_get_telegram_source_day_key(raw_datetime, timestamp)

    # Build published using Telegram display day offset, not receiver local time or raw UTC date
    published = ''
    if timestamp > 0:
        try:
            published = time.strftime('%Y-%m-%d  %H:%M', time.gmtime(int(timestamp) + plugin_get_effective_feed_utc_offset_seconds()))
        except Exception:
            published = plugin_format_source_published_text(raw_datetime)

    text_match = re.search(r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>', raw_message, re.IGNORECASE | re.DOTALL)
    if not text_match:
        return None

    text = plugin_strip_html_message(text_match.group(1))
    if not text:
        return None

    data = plugin_extract_feed_meta_from_text(text)

    # Ignore 4:2:2 feed notifications
    if data.get('feed_type') == '4:2:2':
        return None

    # === Strict filtering: ignore any chat message that has no frequency or key ===
    if data.get('freq_str') == 'Unknown' and not data.get('key'):
        return None
    # =========================================================

    data['post_id'] = post_id or 0
    data['timestamp'] = timestamp
    data['published'] = published
    data['source_day_key'] = source_day_key
    return data


class FuryBissNotifier:
    POLL_INTERVAL_MS = 15000
    MAX_PAGES = 2

    def __init__(self):
        self.last_timestamp = 0
        self.last_signature = ''
        self.seen_post_ids = []
        self.seen_signatures = []
        self.busy = False
        self._last_reset_day = plugin_get_local_day_key()
        self.timer = eTimer()
        try:
            self.timer.timeout.connect(self.check_updates)
        except:
            self.timer.callback.append(self.check_updates)

    def _trim_seen_cache(self):
        try:
            self.seen_post_ids = self.seen_post_ids[:300]
        except:
            self.seen_post_ids = []
        try:
            self.seen_signatures = self.seen_signatures[:300]
        except:
            self.seen_signatures = []

    def _make_signature(self, feed):
        return '%s|%s|%s|%s' % (
            int(feed.get('timestamp', 0) or 0),
            _to_text(feed.get('name', '')),
            _to_text(feed.get('freq_str', '')),
            _to_text(feed.get('key', '')),
        )

    def _remember_feed(self, feed):
        post_id = int(feed.get('post_id', 0) or 0)
        signature = self._make_signature(feed)

        if post_id > 0 and post_id not in self.seen_post_ids:
            self.seen_post_ids.insert(0, post_id)

        if signature and signature not in self.seen_signatures:
            self.seen_signatures.insert(0, signature)

        feed_time = int(feed.get('timestamp', 0) or 0)
        if feed_time >= self.last_timestamp:
            self.last_timestamp = feed_time
            self.last_signature = signature

        plugin_store_runtime_feed(feed)
        self._trim_seen_cache()

    def _is_known_feed(self, feed):
        post_id = int(feed.get('post_id', 0) or 0)
        signature = self._make_signature(feed)

        if post_id > 0 and post_id in self.seen_post_ids:
            return True
        if signature and signature in self.seen_signatures:
            return True
        if self.last_signature and signature == self.last_signature:
            return True
        if self.last_timestamp and int(feed.get('timestamp', 0) or 0) < self.last_timestamp:
            return True
        return False

    def start(self):
        try:
            self.timer.stop()
        except:
            pass
        self.check_updates()
        self.timer.start(self.POLL_INTERVAL_MS, False)

    def stop(self):
        try:
            self.timer.stop()
        except:
            pass
        self.busy = False

    def _reset_if_new_day(self):
        current_day = plugin_get_local_day_key()
        if current_day and current_day != self._last_reset_day:
            self._last_reset_day = current_day
            self.last_timestamp = 0
            self.last_signature = ''
            self.seen_post_ids = []
            self.seen_signatures = []
            global _runtime_feed_cache
            _runtime_feed_cache = []

    def check_updates(self):
        self._reset_if_new_day()
        if self.busy:
            return
        self.busy = True
        deferred = threads.deferToThread(self.bg_fetch)
        deferred.addCallback(self.on_fetch_done)
        deferred.addErrback(self.on_fetch_error)

    def bg_fetch(self):
        # 1. Read the current setting to know the selected source
        try:
            from Components.config import config
            current_source = config.plugins.furybis.feed_source.value
        except Exception:
            current_source = 'both'

        cache_buster = str(int(time.time()))
        all_feeds = []

        # 2. Fetch Telegram notifications if the source is Telegram or both
        if current_source in ('both', 'telegram'):
            visited_urls = {}
            for channel in FEED_SOURCE_CHANNELS:
                url = plugin_get_feed_source_url(channel, nocache=cache_buster)
                try:
                    for page in range(self.MAX_PAGES):
                        if not url or url in visited_urls:
                            break
                        visited_urls[url] = True

                        req = urllib2.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                        html = urllib2.urlopen(req, timeout=8).read()
                        if PY3:
                            html = html.decode('utf-8', 'ignore')
                        else:
                            html = _to_text(html)

                        messages = html.split('tgme_widget_message_wrap')[1:]
                        if not messages:
                            break

                        oldest_post_id = None
                        for raw_message in messages:
                            post_id = plugin_extract_telegram_post_id(raw_message)
                            if post_id is not None:
                                if oldest_post_id is None or post_id < oldest_post_id:
                                    oldest_post_id = post_id

                            feed = plugin_parse_telegram_message(raw_message)
                            if not feed:
                                continue
                            if int(feed.get('timestamp', 0) or 0) > 0:
                                plugin_refresh_feed_day_window_with_detected_offset('telegram:%s-notifier' % channel)
                            if not plugin_feed_is_in_current_telegram_day(feed):
                                continue
                            feed['source_channel'] = channel
                            all_feeds.append(feed)

                        next_url = plugin_get_telegram_next_page_url(html, channel, oldest_post_id)
                        if not next_url:
                            break
                        url = next_url
                except:
                    continue

        # 3. Fetch Blogger/website notifications if the source is website or both
        if current_source in ('both', 'website'):
            try:
                website_feeds = plugin_fetch_live_feed_net()
                if website_feeds:
                    all_feeds.extend(website_feeds)
            except Exception:
                pass
        
        # 4. Merge and filter feeds to detect new ones
        try:
            if not all_feeds:
                return {'baseline': [], 'new_feeds': []}

            unique_map = {}
            for feed in all_feeds:
                post_id = int(feed.get('post_id', 0) or 0)
                signature = self._make_signature(feed)
                if post_id > 0:
                    dedup_key = 'post:%s_%s' % (feed.get('source_channel', 'unknown'), post_id)
                else:
                    dedup_key = 'sig:%s' % signature

                existing = unique_map.get(dedup_key)
                if existing is None or int(feed.get('timestamp', 0) or 0) > int(existing.get('timestamp', 0) or 0):
                    unique_map[dedup_key] = feed

            feeds = list(unique_map.values())
            feeds.sort(key=lambda item: (int(item.get('timestamp', 0) or 0), int(item.get('post_id', 0) or 0)))

            # Collect live post_ids and signatures to detect deletions
            live_post_ids = set()
            live_signatures = set()
            for feed in feeds:
                pid = int(feed.get('post_id', 0) or 0)
                if pid > 0:
                    live_post_ids.add(pid)
                sig = self._make_signature(feed)
                if sig:
                    live_signatures.add(sig)

            if not self.seen_post_ids and not self.seen_signatures and not self.last_signature:
                return {'baseline': feeds, 'new_feeds': [], 'live_post_ids': live_post_ids, 'live_signatures': live_signatures}

            new_feeds = []
            for feed in feeds:
                if not self._is_known_feed(feed):
                    new_feeds.append(feed)

            return {'baseline': [], 'new_feeds': new_feeds, 'live_post_ids': live_post_ids, 'live_signatures': live_signatures}
        except:
            return None

    def on_fetch_done(self, result):
        self.busy = False
        if not result:
            return

        baseline = result.get('baseline') or []
        new_feeds = result.get('new_feeds') or []
        live_post_ids = result.get('live_post_ids') or set()
        live_signatures = result.get('live_signatures') or set()

        # Prune deleted feeds from seen cache so they re-appear if re-posted
        if live_post_ids or live_signatures:
            try:
                self.seen_post_ids = [pid for pid in self.seen_post_ids if pid in live_post_ids]
            except Exception:
                pass
            try:
                self.seen_signatures = [sig for sig in self.seen_signatures if sig in live_signatures]
            except Exception:
                pass
            try:
                if self.last_signature and self.last_signature not in live_signatures:
                    self.last_signature = ''
                    self.last_timestamp = 0
            except Exception:
                pass
            # Also prune runtime feed cache from deleted posts
            try:
                global _runtime_feed_cache
                _runtime_feed_cache = [
                    f for f in _runtime_feed_cache
                    if int(f.get('post_id', 0) or 0) in live_post_ids
                    or self._make_signature(f) in live_signatures
                ]
                plugin_save_feed_cache_to_disk()
            except Exception:
                pass

        if baseline:
            for feed in baseline:
                self._remember_feed(feed)
            return

        if not new_feeds:
            return

        new_feeds.sort(key=lambda item: (int(item.get('timestamp', 0) or 0), int(item.get('post_id', 0) or 0)))

        from Components.config import config
        notifications_enabled = True
        try:
            notifications_enabled = bool(config.plugins.furybis.notifications.value)
        except:
            notifications_enabled = True

        feed_to_notify = None
        for feed in new_feeds:
            self._remember_feed(feed)
            if notifications_enabled:
                feed_to_notify = feed

        if notifications_enabled and feed_to_notify is not None:
            try:
                plugin_show_fast_feed_notification(feed_to_notify, timeout=6)
            except:
                pass

        # If the feeds screen is open, refresh it instantly from cache
        try:
            global _active_feeds_screen
            if _active_feeds_screen is not None:
                _active_feeds_screen._triggerLiveRefresh()
        except Exception:
            pass

    def on_fetch_error(self, failure):
        self.busy = False
        return None



class FuryBissDailyKeyCleaner:
    CHECK_INTERVAL_MS = 60000

    def __init__(self):
        self.last_day_key = ''
        self.timer = eTimer()
        try:
            self.timer.timeout.connect(self.check_rollover)
        except:
            self.timer.callback.append(self.check_rollover)

    def start(self):
        try:
            self.timer.stop()
        except:
            pass
        self.check_rollover(force=True)
        self.timer.start(self.CHECK_INTERVAL_MS, False)

    def stop(self):
        try:
            self.timer.stop()
        except:
            pass

    def check_rollover(self, force=False):
        current_day_key = plugin_get_local_day_key()
        if not current_day_key:
            return
        if force or current_day_key != self.last_day_key:
            plugin_run_daily_key_cleanup(current_day_key)
            self.last_day_key = current_day_key


global_notifier = None
global_daily_cleaner = None
_furybiss_session = None
_furybiss_active_notification = None
_active_feeds_screen = None   # ref to open FuryBissFeedsScreen — for live refresh


def plugin_set_runtime_session(session):
    global _furybiss_session
    try:
        if session is not None:
            _furybiss_session = session
    except:
        pass


def plugin_close_fast_feed_notification(dialog=None):
    """Hide and remove the current lightweight notification dialog safely."""
    global _furybiss_active_notification, _furybiss_session

    try:
        target = dialog or _furybiss_active_notification
    except:
        target = None

    if target is None:
        return False

    try:
        if hasattr(target, 'dismiss'):
            target.dismiss()
            return True
    except:
        pass

    try:
        close_timer = getattr(target, 'closeTimer', None)
        if close_timer is not None:
            close_timer.stop()
    except:
        pass
    try:
        target.hide()
    except:
        pass
    try:
        session = getattr(target, '_fury_session', None) or getattr(target, 'session', None) or _furybiss_session
        if session is not None and hasattr(session, 'deleteDialog'):
            session.deleteDialog(target)
    except:
        try:
            target.close()
        except:
            pass
    try:
        if _furybiss_active_notification is target:
            _furybiss_active_notification = None
    except:
        pass
    return True


def plugin_show_fast_feed_notification(feed, timeout=6):
    """Show a lightweight overlay without taking remote-control focus."""
    global _furybiss_active_notification, _furybiss_session

    try:
        session = _furybiss_session
    except:
        session = None

    if session is None:
        return False

    try:
        plugin_close_fast_feed_notification(_furybiss_active_notification)
    except:
        _furybiss_active_notification = None

    try:
        dialog = session.instantiateDialog(FuryBissNotificationScreen, feed, timeout)
        _furybiss_active_notification = dialog
        try:
            dialog.show()
        except:
            pass
        return True
    except:
        _furybiss_active_notification = None
        return False




def plugin_plugin_enabled():
    try:
        return bool(config.plugins.furybis.enabled.value)
    except:
        return True


def plugin_notifications_enabled():
    try:
        return bool(config.plugins.furybis.enabled.value) and bool(config.plugins.furybis.notifications.value)
    except:
        return True


def plugin_ensure_notifier_started():
    global global_notifier
    if not plugin_notifications_enabled():
        if global_notifier is not None:
            try:
                global_notifier.stop()
            except:
                pass
        if global_daily_cleaner is not None:
            try:
                global_daily_cleaner.stop()
            except:
                pass
        return

    if global_notifier is None:
        global_notifier = FuryBissNotifier()
    global_notifier.start()


def plugin_ensure_daily_cleaner_started():
    global global_daily_cleaner
    if not plugin_plugin_enabled():
        if global_daily_cleaner is not None:
            try:
                global_daily_cleaner.stop()
            except:
                pass
        return

    if global_daily_cleaner is None:
        global_daily_cleaner = FuryBissDailyKeyCleaner()
    global_daily_cleaner.start()


def fury_autostart(reason, **kwargs):
    global global_notifier, global_daily_cleaner
    if reason == 0:
        # Start NTP sync immediately so accurate time is available ASAP
        try:
            plugin_start_ntp_sync()
        except Exception:
            pass
        try:
            if bool(config.plugins.furybis.enabled.value):
                # Adjustment here: the server will run only if VIP is active or not required
                if not REQUIRE_ACTIVATION or is_vip_active():
                    from .web_server import ensure_server_state
                    ensure_server_state()
        except:
            pass
    elif reason == 1:
        try:
            from .web_server import stop_server
            stop_server()
        except:
            pass
        if global_notifier is not None:
            try:
                global_notifier.stop()
            except:
                pass
        if global_daily_cleaner is not None:
            try:
                global_daily_cleaner.stop()
            except:
                pass


def fury_sessionstart(reason, **kwargs):
    if reason != 0:
        return
    if 'session' not in kwargs:
        return
    plugin_set_runtime_session(kwargs.get('session'))
    plugin_ensure_daily_cleaner_started()
    plugin_ensure_notifier_started()


def Plugins(**kwargs):
    return [
        PluginDescriptor(where=PluginDescriptor.WHERE_AUTOSTART, fnc=fury_autostart),
        PluginDescriptor(where=PluginDescriptor.WHERE_SESSIONSTART, fnc=fury_sessionstart),
        PluginDescriptor(
            name='FuryBiss v%s' % _read_installed_plugin_version(),
            description='Feeds Biss By Islam Salama.',
            where=PluginDescriptor.WHERE_PLUGINMENU,
            icon='plugin.png',
            fnc=main,
        )
    ]