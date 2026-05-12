# -*- coding: utf-8 -*-
##################################################

# Created by islam salama

##################################################

import os
import re
import sys
import ssl
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass
import time
import socket
import threading
import subprocess
import binascii
from array import array

import NavigationInstance
from Components.config import config

from . import ensure_config, get_storage_path, get_storage_write_paths

# معادلة الحساب المعقدة للهاش الخاص بقنوات الفيد
crc_table = array("L")
for byte in range(256):
    crc = 0
    for bit in range(8):
        if (byte ^ crc) & 1:
            crc = (crc >> 1) ^ 0xEDB88320
        else:
            crc >>= 1
        byte >>= 1
    crc_table.append(crc)

PY3 = sys.version_info[0] >= 3

if PY3:
    text_type = str
    binary_type = bytes
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib import parse as urlparse
    from html import escape as _html_escape
else:
    text_type = unicode
    binary_type = str
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
    import urlparse
    import cgi


ensure_config()
BISS_KEY_RE = re.compile(r'^[0-9A-F]{16}$')
INITD_DIR = "/etc/init.d"
HOST = '0.0.0.0'
PORT = 9737
LOG_FILE = "/tmp/furybiss_web.log"
ECM_INFO_FILES = (
    "/tmp/ecm.info",
    "/tmp/ecm0.info",
    "/tmp/ecm1.info",
    "/tmp/.oscam/ecm.info",
    "/tmp/.oscam/ecm0.info",
    "/tmp/.oscam/ecm1.info",
)
ECM_PID_PATTERNS = (
    re.compile(r"(?im)^\s*ecm\s*pid\s*[:=]\s*(?:0x)?([0-9a-f]{1,4})\b"),
    re.compile(r"(?im)^\s*ecmpid\s*[:=]\s*(?:0x)?([0-9a-f]{1,4})\b"),
    re.compile(r"(?im)^\s*pid\s*[:=]\s*(?:0x)?([0-9a-f]{1,4})\b"),
)

_server_lock = threading.Lock()
_httpd = None
_server_thread = None
_last_error = ""
_last_request_at = ""
_last_self_test_ok = None
_last_self_test_message = ""
_emu_restart_lock = threading.Lock()


class ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True



def _now_text():
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""



def _to_text(value):
    if value is None:
        return ""
    if isinstance(value, text_type):
        return value
    if isinstance(value, binary_type):
        try:
            return value.decode("utf-8")
        except Exception:
            try:
                return value.decode("latin-1", "ignore")
            except Exception:
                pass
    try:
        return text_type(value)
    except Exception:
        try:
            return str(value)
        except Exception:
            return ""



def _to_bytes(value):
    if isinstance(value, binary_type):
        return value
    return _to_text(value).encode("utf-8")



def html_escape(value):
    value = _to_text(value)
    if PY3:
        return _html_escape(value, quote=True)
    return cgi.escape(value, True)



def _log(message):
    line = "[{0}] {1}\n".format(_now_text(), _to_text(message))
    try:
        handle = open(LOG_FILE, 'a')
        try:
            handle.write(line)
        finally:
            handle.close()
    except Exception:
        pass



def _set_last_error(message):
    global _last_error
    _last_error = _to_text(message).strip()
    if _last_error:
        _log("ERROR: {0}".format(_last_error))



def _clear_last_error():
    global _last_error
    _last_error = ""



def _set_self_test(ok, message):
    global _last_self_test_ok, _last_self_test_message
    _last_self_test_ok = ok
    _last_self_test_message = _to_text(message).strip()
    if _last_self_test_message:
        _log("SELFTEST: {0}".format(_last_self_test_message))



def _note_request(method, path):
    global _last_request_at
    _last_request_at = "{0} {1} {2}".format(_now_text(), _to_text(method), _to_text(path))



def _thread_is_alive(thread):
    if thread is None:
        return False
    try:
        if hasattr(thread, "is_alive"):
            return thread.is_alive()
        return thread.isAlive()
    except Exception:
        return False



def server_is_running():
    _server_lock.acquire()
    try:
        return _httpd is not None and _thread_is_alive(_server_thread)
    finally:
        _server_lock.release()



def _normalize_ip(value):
    if isinstance(value, (list, tuple)):
        value = ".".join([_to_text(part) for part in value])
    text = _to_text(value).strip()
    if not text:
        return None
    if "/" in text:
        text = text.split("/", 1)[0]
    if text.startswith("127.") or text == "0.0.0.0":
        return None
    pieces = text.split(".")
    if len(pieces) != 4:
        return None
    try:
        octets = [int(part) for part in pieces]
    except Exception:
        return None
    for part in octets:
        if part < 0 or part > 255:
            return None
    return ".".join([str(part) for part in octets])



def get_box_ips():
    ips = []

    def add_ip(candidate):
        ip = _normalize_ip(candidate)
        if ip and ip not in ips:
            ips.append(ip)

    try:
        from Components.Network import iNetwork
        adapter_names = []
        for attr_name in ("getConfiguredAdapters", "getAdapterList"):
            try:
                getter = getattr(iNetwork, attr_name, None)
                if getter is None:
                    continue
                result = getter()
                if isinstance(result, dict):
                    result = result.keys()
                for item in result or []:
                    item_text = _to_text(item)
                    if item_text and item_text != "lo" and item_text not in adapter_names:
                        adapter_names.append(item_text)
            except Exception:
                pass

        for adapter in adapter_names:
            for key_name in ("ip", "ip_address", "address"):
                try:
                    value = iNetwork.getAdapterAttribute(adapter, key_name)
                except Exception:
                    value = None
                add_ip(value)
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        for item in socket.gethostbyname_ex(hostname)[2]:
            add_ip(item)
    except Exception:
        pass

    try:
        info = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_DGRAM)
        for item in info:
            add_ip(item[4][0])
    except Exception:
        pass

    for target in ("10.255.255.255", "192.168.1.1", "8.8.8.8"):
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.4)
            sock.connect((target, 80))
            add_ip(sock.getsockname()[0])
        except Exception:
            pass
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass

    for shell_cmd in (
        "ip -o -4 addr show up scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1",
        "ifconfig 2>/dev/null | awk '/inet addr:/{print substr($2,6)} /inet /{print $2}'",
    ):
        try:
            output = subprocess.check_output(["sh", "-c", shell_cmd])
            for line in _to_text(output).splitlines():
                add_ip(line.strip())
        except Exception:
            pass

    return ips



def get_access_urls():
    return ["http://{0}:{1}".format(ip, PORT) for ip in get_box_ips()]



def get_primary_url():
    urls = get_access_urls()
    if urls:
        return urls[0]
    return "http://127.0.0.1:{0}".format(PORT)


def _add_unique(items, value):
    if value not in items:
        items.append(value)


def _normalize_pid(value):
    value = _to_text(value).strip()
    if value.lower().startswith("0x"):
        value = value[2:]
    if not re.match(r'^[0-9A-Fa-f]{1,4}$', value):
        return None
    value = value.upper().zfill(4)
    if value == "0000":
        return None
    return value


def _read_text_file(path):
    handle = None
    try:
        handle = open(path, 'rb')
        data = handle.read()
        return _to_text(data)
    except Exception:
        return ""
    finally:
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass


def detect_current_ecm_pids():
    pids = []
    for info_path in ECM_INFO_FILES:
        text = _read_text_file(info_path)
        if not text:
            continue
        for pattern in ECM_PID_PATTERNS:
            for match in pattern.findall(text):
                pid = _normalize_pid(match)
                if pid:
                    _add_unique(pids, pid)
        if len(pids) >= 3:
            break

    if "1FFF" not in pids:
        pids.append("1FFF")
    return pids[:4]


def get_orbital(namespace_hex):
    try:
        ns = int(namespace_hex, 16)
        if ns == 0: return ""
        orb = ns >> 16
        if orb == 0xFFFF or orb == 0xEEEE: return "" 
        if orb > 1800:
            orb = 3600 - orb
            return " at {0:.1f}W".format(orb / 10.0)
        else:
            return " at {0:.1f}E".format(orb / 10.0)
    except Exception:
        return ""

def build_biss_lines(info, biss_key):
    sid = info.get("sid", "0000")
    vpid = info.get("vpid", "1FFF")
    channel_name = info.get("name", "Unknown")
    namespace = info.get("namespace", "00000000")
    hash_val = info.get("hash", "")
    
    orbital = get_orbital(namespace)
    comment = "Added by FuryBiss for {0}{1}".format(channel_name, orbital)
    
    lines = []
    ecm_pids = []
    
    # فصل الشفرات
    keys = [k.strip() for k in biss_key.split(',')] if ',' in biss_key else [biss_key]
    keys = [k for k in keys if k and k != "FTA"]
    
    if not keys:
        return [], []

    # تحديد الشفرة الأولى والثانية
    key1 = keys[0]
    # لو فيه شفرة تانية هناخدها، لو مفيش هنكرر الأولى
    key2 = keys[1] if len(keys) >= 2 else keys[0]

    # هنا السر: استخدام (elif) لكتابة معرف واحد فقط والأولوية للـ Hash لتجنب التداخل
    if hash_val:
        lines.append("F {0} 00 {1} ; {2}\n".format(hash_val, key1, comment))
        lines.append("F {0} 01 {1} ; {2}\n".format(hash_val, key2, comment))
        ecm_pids.append("Hash:" + hash_val)
    elif vpid and vpid != "1FFF" and vpid != "0000":
        lines.append("F {0}{1} 00 {2} ; {3}\n".format(sid, vpid, key1, comment))
        lines.append("F {0}{1} 01 {2} ; {3}\n".format(sid, vpid, key2, comment))
        ecm_pids.append(vpid)
    else:
        lines.append("F {0}1FFF 00 {1} ; {2}\n".format(sid, key1, comment))
        lines.append("F {0}1FFF 01 {1} ; {2}\n".format(sid, key2, comment))
        if "1FFF" not in ecm_pids:
            ecm_pids.append("1FFF")
            
    unique_lines = []
    for line in lines:
        if line not in unique_lines:
            unique_lines.append(line)
            
    return unique_lines, ecm_pids
    
def _clean_service_name(name):
    text = _to_text(name)
    for token in (u"\u0086", u"\u0087", "\x86", "\x87"):
        text = text.replace(token, "")
    try:
        text = re.sub(u"[\x00-\x1f]+", u" ", text)
    except Exception:
        pass
    text = u" ".join(text.split())
    return text or u"Unknown"



def run_local_self_test(timeout=1.0):
    if not server_is_running():
        message = "server is not running"
        _set_self_test(False, message)
        return False, message

    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(("127.0.0.1", PORT))
        request_data = "GET / HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
        sock.sendall(_to_bytes(request_data))
        chunks = []
        remaining = 4096
        while remaining > 0:
            piece = sock.recv(min(1024, remaining))
            if not piece:
                break
            chunks.append(piece)
            remaining -= len(piece)
        if PY3:
            raw_response = b"".join(chunks)
        else:
            raw_response = "".join(chunks)
        response_text = _to_text(raw_response)
        lower_text = response_text.lower()
        if "furybis plugin" in lower_text or "<html" in lower_text or "200 ok" in lower_text:
            message = "reachable at {0}".format(get_primary_url())
            _set_self_test(True, message)
            return True, message
        message = "server accepted the connection but returned an unexpected response"
        _set_self_test(False, message)
        return False, message
    except Exception as error:
        message = "self-test failed: {0}".format(_to_text(error))
        _set_self_test(False, message)
        _set_last_error(message)
        return False, message
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass



def get_status_snapshot(run_self_test=False):
    ensure_config()
    running = server_is_running()
    if run_self_test:
        try:
            run_local_self_test()
        except Exception as error:
            _set_last_error("status self-test failed: {0}".format(_to_text(error)))
    return {
        "enabled_setting": bool(config.plugins.furybis.enabled.value),
        "running": running,
        "port": PORT,
        "primary_url": get_primary_url(),
        "access_urls": get_access_urls(),
        "last_error": _last_error,
        "last_request_at": _last_request_at,
        "self_test_ok": _last_self_test_ok,
        "self_test_message": _last_self_test_message,
        "log_file": LOG_FILE,
    }


def _shell_quote(value):
    value = _to_text(value)
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _shell_short_wait(microseconds=200000):
    """Tiny shell wait without falling back to a full one-second sleep."""
    try:
        microseconds = int(microseconds)
    except Exception:
        microseconds = 200000
    if microseconds < 1:
        microseconds = 1
    return "(usleep %d >/dev/null 2>&1 || true)" % microseconds



_EMU_BASE_NAMES = ('oscam', 'ncam', 'gcam', 'cccam', 'wicardd', 'gbox')


def _normalize_emu_identifier(value):
    text = _to_text(value).strip().lower()
    if not text:
        return ''
    text = text.replace('\\', '/')
    base = os.path.basename(text).strip()
    if not base:
        base = text
    if 'none' in base and not any(token in base for token in _EMU_BASE_NAMES):
        return ''
    base = base.replace('softcam.', '').replace('.sh', '').replace('_cam', '')
    for token in _EMU_BASE_NAMES:
        if token in base:
            return token
    return base


def _emu_name_has_ci(value):
    text = _to_text(value).strip().lower().replace('-', '_').replace('.', '_').replace(' ', '_')
    parts = [part for part in text.split('_') if part]
    return 'ci' in parts


def _score_emu_match(candidate, emu_name):
    candidate_base = _normalize_emu_identifier(candidate)
    emu_base = _normalize_emu_identifier(emu_name)
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
    if _emu_name_has_ci(name_lower) and not _emu_name_has_ci(candidate_lower):
        score -= 45
    return score


def _get_active_emu_proc_info():
    """
    Find the real running EMU process.
    Returns (comm, bin_path, extra_args) or (None, None, []).
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
                normalized = _normalize_emu_identifier(comm)
                if normalized not in _EMU_BASE_NAMES:
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


def _build_direct_proc_restart_command(bin_path, extra_args):
    """
    Restart the currently running EMU directly from its real executable.
    This avoids slow/blocking cam scripts and uses the exact running args.
    """
    bin_path = _to_text(bin_path).strip()
    if not bin_path:
        return ''
    bin_name = os.path.basename(bin_path)
    kill_sequence = _build_emu_kill_sequence(bin_name)
    quoted_bin = _shell_quote(bin_path)
    quoted_args = ' '.join([_shell_quote(a) for a in (extra_args or []) if _to_text(a).strip()])
    cleanup = (
        "rm -rf /tmp/.oscam /tmp/.ncam /tmp/*.pid* /tmp/oscam.* "
        "/tmp/*.oscam /tmp/ncam.* /tmp/*.ncam /tmp/status.* /tmp/frozen "
        ">/dev/null 2>&1"
    )
    if quoted_args:
        start_cmd = "(ulimit -s 1024; nohup %s %s >/dev/null 2>&1 &)" % (quoted_bin, quoted_args)
    else:
        start_cmd = "(ulimit -s 1024; nohup %s >/dev/null 2>&1 &)" % quoted_bin
    start_wait = _shell_short_wait(160000)
    return (
        "FURYBISS_DIRECT_RESTART=1; "
        "%s; "
        "%s; "
        "%s; "
        "%s; "
        "(sync >/dev/null 2>&1 &)"
    ) % (kill_sequence, cleanup, start_cmd, start_wait)


def _build_emu_kill_sequence(extra_name=None):
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

    quoted_names = ' '.join([_shell_quote(name) for name in names if name])
    proc_match = '*oscam*|*OSCam*|*OSCAM*|*ncam*|*NCam*|*NCAM*|*gcam*|*GCam*|*GCAM*|*cccam*|*CCcam*|*CCCam*|*CCCAM*|*wicardd*|*gbox*|*GBox*|*GBOX*'
    proc_soft = "for c in /proc/[0-9]*/comm; do [ -r \"$c\" ] || continue; p=${c%%/comm}; p=${p##*/}; n=`cat \"$c\" 2>/dev/null`; case \"$n\" in %s) kill \"$p\" >/dev/null 2>&1;; esac; done" % proc_match
    proc_hard = "for c in /proc/[0-9]*/comm; do [ -r \"$c\" ] || continue; p=${c%%/comm}; p=${p##*/}; n=`cat \"$c\" 2>/dev/null`; case \"$n\" in %s) kill -9 \"$p\" >/dev/null 2>&1;; esac; done" % proc_match
    first_wait = _shell_short_wait(250000)
    second_wait = _shell_short_wait(180000)
    return (
        "for p in %s; do killall \"$p\" >/dev/null 2>&1; done; "
        "%s; "
        "%s; "
        "for p in %s; do killall -9 \"$p\" >/dev/null 2>&1; done; "
        "%s; "
        "%s"
    ) % (quoted_names, proc_soft, first_wait, quoted_names, proc_hard, second_wait)


def _build_emu_script_restart_command(script_path, bin_name):
    quoted_script = _shell_quote(script_path)
    kill_sequence = _build_emu_kill_sequence(bin_name)
    stop_wait = _shell_short_wait(220000)
    start_wait = _shell_short_wait(300000)
    return (
        "%s stop >/dev/null 2>&1; "
        "%s; "
        "%s; "
        "%s start >/dev/null 2>&1; "
        "%s; "
        "(sync >/dev/null 2>&1 &)"
    ) % (quoted_script, stop_wait, kill_sequence, quoted_script, start_wait)


def _build_emu_binary_restart_command(process_name, binary_path):
    kill_sequence = _build_emu_kill_sequence(process_name or binary_path)
    quoted_binary = _shell_quote(binary_path)
    start_wait = _shell_short_wait(300000)
    return (
        "%s; "
        "(nohup %s >/dev/null 2>&1 || %s >/dev/null 2>&1) & "
        "%s; "
        "(sync >/dev/null 2>&1 &)"
    ) % (kill_sequence, quoted_binary, quoted_binary, start_wait)


def _build_openvix_softcam_restart_command(process_name, binary_path):
    name = os.path.basename(_to_text(process_name or binary_path).strip())
    lower = name.lower()
    quoted_binary = _shell_quote(binary_path)
    kill_sequence = _build_emu_kill_sequence(name or binary_path)
    cleanup = "rm -rf /tmp/.oscam /tmp/.ncam /tmp/*.pid* /tmp/oscam.* /tmp/*.oscam /tmp/ncam.* /tmp/*.ncam /tmp/status.* /tmp/frozen >/dev/null 2>&1"
    stop_wait = _shell_short_wait(220000)
    start_wait = _shell_short_wait(450000)

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


def _add_emu_candidate(candidates, value):
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
        normalized_base = _normalize_emu_identifier(base)
        if normalized_base:
            variants.append(normalized_base)
        for item in variants:
            item = _to_text(item).strip().lower()
            if item and item != 'none' and item not in candidates:
                candidates.append(item)


def _get_openvix_softcam_candidates():
    candidates = []
    try:
        scm = getattr(config, 'softcammanager', None)
        value_obj = getattr(getattr(scm, 'softcams_autostart', None), 'value', '')
        if isinstance(value_obj, (list, tuple)):
            for item in value_obj:
                _add_emu_candidate(candidates, item)
        else:
            _add_emu_candidate(candidates, value_obj)
    except Exception:
        pass

    for path in ('/tmp/SoftcamsScriptsRunning', '/etc/SoftcamsAutostart'):
        try:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    _add_emu_candidate(candidates, f.read())
        except Exception:
            pass

    try:
        if os.path.exists('/etc/enigma2/settings'):
            with open('/etc/enigma2/settings', 'r') as f:
                for line in f:
                    if line.startswith('config.softcammanager.softcams_autostart='):
                        _add_emu_candidate(candidates, line.split('=', 1)[1])
                    elif line.startswith('config.misc.softcams='):
                        _add_emu_candidate(candidates, line.split('=', 1)[1])
    except Exception:
        pass

    try:
        misc_section = getattr(config, 'misc', None)
        softcams_value = getattr(getattr(misc_section, 'softcams', None), 'value', '')
        _add_emu_candidate(candidates, softcams_value)
    except Exception:
        pass

    return candidates


def _stop_current_service_for_emu():
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


def _resume_current_service_after_emu(oldref):
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


def _run_emu_restart_worker(command_str, locked=False):
    oldref = None
    try:
        try:
            os.system('sync >/dev/null 2>&1 &')
        except Exception:
            pass
        is_direct_restart = 'FURYBISS_DIRECT_RESTART=1' in command_str
        needs_service_restart = (
            not is_direct_restart and
            ('/usr/softcams/' in command_str or '/usr/script/' in command_str)
        )
        if needs_service_restart:
            oldref = _stop_current_service_for_emu()
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
                _resume_current_service_after_emu(oldref)
        except Exception:
            pass
    finally:
        if locked:
            try:
                _emu_restart_lock.release()
            except Exception:
                pass


def _run_emu_restart_command(command_str):
    command_str = _to_text(command_str).strip()
    if not command_str:
        return False
    if command_str.startswith('(') and command_str.endswith(') &'):
        command_str = command_str[1:-3].strip()

    locked = False
    try:
        try:
            locked = _emu_restart_lock.acquire(False)
            if not locked:
                return True
        except TypeError:
            _emu_restart_lock.acquire()
            locked = True

        worker = threading.Thread(target=_run_emu_restart_worker, args=(command_str, locked))
        try:
            worker.setDaemon(True)
        except Exception:
            pass
        worker.start()
        return True
    except Exception:
        if locked:
            try:
                _emu_restart_lock.release()
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


class FuryBisHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def _send_payload(self, status_code, content_type, payload):
        data = _to_bytes(payload)
        self.send_response(status_code)
        self.send_header('Content-Type', '{0}; charset=utf-8'.format(content_type))
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(data)
        try:
            self.wfile.flush()
        except Exception:
            pass

    def _send_html(self, status_code, html_text):
        self._send_payload(status_code, 'text/html', html_text)

    def _send_text(self, status_code, text):
        self._send_payload(status_code, 'text/plain', text)

    def _send_empty(self, status_code):
        self.send_response(status_code)
        self.send_header('Content-Length', '0')
        self.send_header('Connection', 'close')
        self.end_headers()

    def _send_internal_error_page(self, error):
        error_text = html_escape(_to_text(error))
        page = """
        <!DOCTYPE html>
        <html lang="en" dir="ltr">
        <head>
            <meta charset="UTF-8">
            <title>FuryBiss - Internal Error</title>
            <style>
                body {{ font-family: Arial, sans-serif; background: #1e1e24; color: #fff; text-align: center; margin: 0; padding: 24px; }}
                .box {{ background: #2b2b36; max-width: 620px; margin: 40px auto; padding: 28px; border-radius: 12px; }}
                .error {{ background: #493039; color: #ffdce0; padding: 14px; border-radius: 8px; text-align: left; word-break: break-word; }}
                .info {{ color: #b8f5ff; font-size: 14px; margin-top: 16px; }}
            </style>
        </head>
        <body>
            <div class="box">
                <h1>FuryBiss Plugin</h1>
                <p>The web interface hit an internal error.</p>
                <div class="error">{error}</div>
                <p class="info">Check the plugin screen for IP/Web status and last error.<br>Log file: {log_file}</p>
            </div>
        </body>
        </html>
        """.format(error=error_text, log_file=html_escape(LOG_FILE))
        try:
            self._send_html(500, page)
        except Exception:
            pass

    def get_current_channel(self):
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
                            # استخراج التردد
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
        
    def get_emus(self):
        emus_dict = {}
        try:
            # 1. البحث في مسارات السكريبتات المعتادة
            # Real restart: stop script, kill old softcam processes, wait, then start again.
            script_paths = [
                "/usr/script",
                "/usr/camscript",
                "/etc/rc.d",
                "/etc/init.d"
            ]
            
            script_emus = [] # مصفوفة لحفظ أسماء السكريبتات عشان نفلتر بيها بعدين

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
                                emus_dict[display_name] = _build_openvix_softcam_restart_command(name, full_path)
                                script_emus.append(display_name.lower())
                                script_emus.append(name.lower())
            
            for script_dir in script_paths:
                if os.path.isdir(script_dir):
                    for name in os.listdir(script_dir):
                        lower = name.lower()
                        if "none" in lower or lower.endswith(".bak") or lower.endswith(".pid") or "volatiles" in lower or "bootup" in lower:
                            continue
                            
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
                                    emus_dict[display_name] = _build_emu_script_restart_command(full_path, bin_name)
                                    script_emus.append(display_name.lower())

            # 2. البحث المباشر في ملفات التشغيل (Binaries) كحل قاطع لصورة Pure2
            bin_dirs = ["/usr/bin", "/usr/bin/cam", "/usr/bin/cams", "/usr/bin/emu", "/var/bin", "/var/emu"]
            for b_dir in bin_dirs:
                if os.path.isdir(b_dir):
                    for name in os.listdir(b_dir):
                        lower = name.lower()
                        if lower.endswith(".sh") or lower.endswith(".bak"):
                            continue
                        if "oscam" in lower or "ncam" in lower or "gcam" in lower or "cccam" in lower or "wicardd" in lower or "gbox" in lower:
                            
                            # الفلترة الذكية: لو اسم البيناري جزء من اسم سكريبت موجود أصلاً، ما تضيفوش
                            is_duplicate = False
                            if lower not in _EMU_BASE_NAMES:
                                for s_name in script_emus:
                                    if lower in s_name or s_name in lower:
                                        is_duplicate = True
                                        break
                                    
                            if not is_duplicate:
                                full_path = os.path.join(b_dir, name)
                                if os.path.isfile(full_path) and os.access(full_path, os.X_OK):
                                    if name not in emus_dict:
                                        emus_dict[name] = _build_emu_binary_restart_command(name, full_path)

            # 3. إزالة الأسماء الوهمية (مثل cams و softcam) إذا وجدنا الإيموهات الحقيقية
            specific_found = any(x for x in emus_dict.keys() if "oscam" in x.lower() or "ncam" in x.lower() or "gcam" in x.lower() or "cccam" in x.lower() or "wicardd" in x.lower() or "gbox" in x.lower())
            if specific_found:
                for generic in ["cams", "softcam", "cam", "softcams"]:
                    if generic in emus_dict:
                        del emus_dict[generic]

        except Exception as error:
            _set_last_error("get_emus failed: {0}".format(_to_text(error)))
            
        return emus_dict

    def append_key_lines(self, path, lines):
        import os
        existing_content = []
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    existing_content = f.readlines()
            except Exception:
                pass 

        new_prefixes = []
        for line in lines:
            parts = line.strip().split()
            if len(parts) >= 3 and parts[0].upper() == 'F':
                new_prefixes.append(" ".join(parts[:3]).upper())

        final_lines = []
        for line in existing_content:
            line_strip = line.strip()
            if not line_strip:
                continue
            
            parts = line_strip.split()
            is_replacement = False
            if len(parts) >= 3 and parts[0].upper() == 'F':
                prefix = " ".join(parts[:3]).upper()
                if prefix in new_prefixes:
                    is_replacement = True
            
            if not is_replacement:
                final_lines.append(line_strip + "\n")

        for line in lines:
            if line.strip():
                final_lines.append(line.strip() + "\n")

        try:
            with open(path, 'w') as f:
                f.writelines(final_lines)
            os.system("sync") 
        except Exception:
            pass

    def verify_key_lines(self, path, lines):
        data = b'' if PY3 else ''
        handle = None
        try:
            handle = open(path, 'rb')
            data = handle.read()
        finally:
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass

        missing = []
        for line in lines:
            payload = _to_bytes(_to_text(line).rstrip("\r\n"))
            if payload not in data:
                missing.append(_to_text(line).rstrip("\r\n"))
        return missing
        
        
    def get_current_biss_key(self, info, path):
        import os
        if not os.path.exists(path):
            return "Not Found (File missing)"
            
        hash_val = info.get("hash", "")
        sid = info.get("sid", "0000")
        vpid = info.get("vpid", "1FFF")
        
        # تجهيز الصيغ المحتملة للشفرة الخاصة بهذه القناة
        prefixes = []
        if hash_val:
            prefixes.append("F {0} 00".format(hash_val))
            prefixes.append("F {0} 01".format(hash_val))
        if vpid and vpid != "1FFF" and vpid != "0000":
            prefixes.append("F {0}{1} 00".format(sid, vpid))
            prefixes.append("F {0}{1} 01".format(sid, vpid))
        prefixes.append("F {0}1FFF 00".format(sid))
        prefixes.append("F {0}1FFF 01".format(sid))
        
        try:
            with open(path, 'rb') as f:
                lines = f.readlines()
                # البحث من الأسفل للأعلى لضمان جلب أحدث شفرة مضافة
                for line in reversed(lines):
                    line_str = _to_text(line).strip()
                    if not line_str or line_str.startswith(";"):
                        continue
                    parts = line_str.split()
                    if len(parts) >= 4 and parts[0].upper() == 'F':
                        prefix = " ".join(parts[:3]).upper()
                        if prefix in prefixes:
                            return parts[3].upper() # استخراج الشفرة
        except Exception:
            pass
        return "Not Found" 
        
        
    def fetch_telegram_key(self, current_sid):
        import re
        try:
            if PY3:
                import urllib.request as urllib2
            else:
                import urllib2
                
            url = "https://t.me/s/biss2key"
            req = urllib2.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            response = urllib2.urlopen(req, timeout=10)
            html = response.read()
            if PY3: html = html.decode('utf-8', 'ignore')
            else: html = _to_text(html)
            
            messages = re.findall(r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>', html, re.IGNORECASE | re.DOTALL)
            
            for msg in reversed(messages):
                text = re.sub(r'<br\s*/?>', '\n', msg)
                text = re.sub(r'<[^>]+>', '', text)
                
                sid_match = re.search(r'SID\s*[:\-]?\s*([0-9A-Fa-f]{1,4})\b', text, re.IGNORECASE)
                if sid_match:
                    found_sid = sid_match.group(1).upper().zfill(4)
                    current_sid_clean = current_sid.upper().zfill(4)
                    
                    acceptable_sids = [current_sid_clean]
                    if current_sid_clean == "0001":
                        acceptable_sids.append("0002")
                    elif current_sid_clean == "0002":
                        acceptable_sids.append("0001")
                    
                    if found_sid in acceptable_sids:
                        key_matches = re.findall(r'(?:Key|CW|BISS)\s*[:\-]?\s*([0-9A-Fa-f \t]{16,40})', text, re.IGNORECASE)
                        if key_matches:
                            found_keys = []
                            for match in key_matches:
                                raw_key = match.replace(" ", "").strip().upper()
                                if len(raw_key) >= 16 and raw_key[:16] not in found_keys:
                                    found_keys.append(raw_key[:16])
                            if found_keys: return ",".join(found_keys)
            return None
        except Exception as e:
            return "ERROR: " + str(e)  
            
    def fetch_telegram_key(self, current_sid, current_name, current_freq):
        import re
        try:
            if PY3:
                import urllib.request as urllib2
            else:
                import urllib2
                
            url = "https://t.me/s/biss2key"
            req = urllib2.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            response = urllib2.urlopen(req, timeout=10)
            html = response.read()
            if PY3: html = html.decode('utf-8', 'ignore')
            else: html = _to_text(html)
            
            messages = re.findall(r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>', html, re.IGNORECASE | re.DOTALL)
            
            for msg in reversed(messages):
                text = re.sub(r'<br\s*/?>', '\n', msg)
                text = re.sub(r'<[^>]+>', '', text)
                
                sid_match = re.search(r'SID\s*[:\-]?\s*([0-9A-Fa-f]{1,4})\b', text, re.IGNORECASE)
                found_by_sid = False
                if sid_match:
                    found_sid = sid_match.group(1).upper().zfill(4)
                    current_sid_clean = current_sid.upper().zfill(4)
                    acceptable_sids = [current_sid_clean]
                    if current_sid_clean == "0001": acceptable_sids.append("0002")
                    elif current_sid_clean == "0002": acceptable_sids.append("0001")
                    if found_sid in acceptable_sids: found_by_sid = True

                found_by_name = False
                if current_name and current_name.lower() != "unknown" and len(current_name) > 2:
                    if current_name.lower() in text.lower(): found_by_name = True

                found_by_freq = False
                if current_freq and current_freq.isdigit():
                    freq_int = int(current_freq)
                    for f in range(freq_int - 2, freq_int + 3):
                        if str(f) in text:
                            found_by_freq = True
                            break

                if found_by_sid or found_by_name or found_by_freq:
                    key_matches = re.findall(r'(?:Key|CW|BISS)\s*[:\-]?\s*([0-9A-Fa-f \t]{16,40})', text, re.IGNORECASE)
                    if key_matches:
                        found_keys = []
                        for match in key_matches:
                            raw_key = match.replace(" ", "").strip().upper()
                            if len(raw_key) >= 16 and raw_key[:16] not in found_keys:
                                found_keys.append(raw_key[:16])
                        if found_keys: return ",".join(found_keys)
            return None
        except Exception as e:
            return "ERROR: " + str(e)
            
            
    def get_active_emu_name(self):
        try:
            # 1. First trust the process that is actually running now.
            comm, bin_path, extra_args = _get_active_emu_proc_info()
            if comm or bin_path:
                for value in (os.path.basename(bin_path or ''), comm):
                    normalized = _normalize_emu_identifier(value)
                    if normalized:
                        return normalized

            # 2. OpenBH / BlackHole current cam file.
            if os.path.exists("/etc/CurrentBhCamName"):
                with open("/etc/CurrentBhCamName", "r") as f:
                    value = f.read().strip()
                    normalized = _normalize_emu_identifier(value)
                    if normalized:
                        return normalized

            # 3. OpenViX SoftcamManager running process path and saved selection.
            for pid in os.listdir('/proc'):
                if pid.isdigit():
                    try:
                        exe_path = os.path.realpath(os.path.join('/proc', pid, 'exe'))
                        if exe_path and '/usr/softcams/' in exe_path:
                            normalized = _normalize_emu_identifier(os.path.basename(exe_path))
                            if normalized:
                                return normalized
                    except Exception:
                        pass

            candidates = _get_openvix_softcam_candidates()
            if candidates:
                return candidates[0]

            # 4. OpenATV / OpenPLi softcam symlink.
            if os.path.exists("/etc/init.d/softcam"):
                value = os.path.realpath("/etc/init.d/softcam").split('/')[-1]
                normalized = _normalize_emu_identifier(value)
                if normalized:
                    return normalized

            # 5. Last fallback: process comm scan.
            for pid in os.listdir('/proc'):
                if pid.isdigit():
                    try:
                        with open(os.path.join('/proc', pid, 'comm'), 'r') as f:
                            comm = f.read().strip()
                            normalized = _normalize_emu_identifier(comm)
                            if normalized:
                                return normalized
                    except Exception:
                        pass
        except Exception:
            pass
        return None

    def resolve_active_emu(self, emus_dict=None):
        """
        Return (emu_name, restart_command, display_label) for the active EMU.
        Direct /proc restart has priority; script commands are only fallback.
        """
        if emus_dict is None:
            emus_dict = self.get_emus()

        def best_match(candidates):
            best_emu = ""
            best_score = 0
            for candidate in candidates:
                if not candidate:
                    continue
                for emu_name in sorted(emus_dict.keys()):
                    score = _score_emu_match(candidate, emu_name)
                    if score > best_score:
                        best_score = score
                        best_emu = emu_name
            return best_emu

        try:
            comm, bin_path, extra_args = _get_active_emu_proc_info()
            if comm and bin_path:
                direct_cmd = _build_direct_proc_restart_command(bin_path, extra_args)
                display_label = os.path.basename(bin_path) or comm
                candidates = [comm, display_label, bin_path, _normalize_emu_identifier(comm), _normalize_emu_identifier(display_label)]
                matched_emu = best_match(candidates)
                return (matched_emu or display_label, direct_cmd, display_label)
        except Exception:
            pass

        candidates = []
        try:
            active_name = self.get_active_emu_name()
            if active_name:
                _add_emu_candidate(candidates, active_name)
        except Exception:
            pass

        try:
            for item in _get_openvix_softcam_candidates():
                _add_emu_candidate(candidates, item)
        except Exception:
            pass

        matched_emu = best_match(candidates)
        if matched_emu and matched_emu in emus_dict:
            return (matched_emu, emus_dict[matched_emu], matched_emu)

        return ("", "", "")


    def render_form(self, message_html=""):
        info = self.get_current_channel()
        channel_name = info.get("name", "Unknown")
        sid = info.get("sid", "0000")
        storage_path = get_storage_path()
        emus_dict = self.get_emus()
        current_key = self.get_current_biss_key(info, storage_path)
        
        # Detect active EMU once, keep it as the default choice, and still allow manual override.
        # The dropdown shows plain EMU names only. The active EMU is not repeated again
        # in the manual list when it has the same name/base as a detected item.
        resolved_emu, resolved_cmd, resolved_label = self.resolve_active_emu(emus_dict)
        active_text = resolved_label or resolved_emu or ""
        active_display = active_text or "Active EMU"
        active_base = _normalize_emu_identifier(active_display)
        active_key_base = _normalize_emu_identifier(resolved_emu)
        options_list = []
        used_option_names = []

        def add_emu_option(option_value, option_label, selected=False):
            label_text = _to_text(option_label).strip()
            if not label_text:
                return
            label_key = label_text.lower()
            label_base = _normalize_emu_identifier(label_text)
            dedupe_keys = [label_key]
            if label_base:
                dedupe_keys.append("base:" + label_base)
            for key in dedupe_keys:
                if key in used_option_names:
                    return
            for key in dedupe_keys:
                used_option_names.append(key)
            selected_attr = ' selected="selected"' if selected else ''
            options_list.append(
                '<option value="{0}"{1}>{2}</option>'.format(
                    html_escape(option_value),
                    selected_attr,
                    html_escape(label_text)
                )
            )

        if resolved_cmd:
            add_emu_option("__active__", active_display, True)

        if emus_dict:
            for emu_name in sorted(emus_dict.keys()):
                emu_base = _normalize_emu_identifier(emu_name)
                emu_lower = _to_text(emu_name).strip().lower()
                active_lower = _to_text(active_display).strip().lower()
                if resolved_cmd and (
                    (active_lower and emu_lower == active_lower) or
                    (active_base and emu_base and emu_base == active_base) or
                    (active_key_base and emu_base and emu_base == active_key_base)
                ):
                    continue
                add_emu_option(emu_name, emu_name, False)

        if options_list:
            if resolved_cmd:
                emu_control_html = (
                    '<label>EMU Restart Mode:</label>'
                    '<div class="active-emu">Active EMU Detected: {0}</div>'
                    '<select name="emu">{1}</select>'
                    '<div class="emu-hint">The active EMU is selected automatically. You can choose another EMU from the list.</div>'
                ).format(html_escape(active_text or "Active EMU"), "".join(options_list))
            else:
                emu_control_html = (
                    '<label>Select EMU to Restart:</label>'
                    '<select name="emu">{0}</select>'
                    '<div class="emu-hint">No running EMU was detected, so manual selection is available.</div>'
                ).format("".join(options_list))
        else:
            emu_control_html = (
                '<label>Active EMU:</label>'
                '<div class="active-emu">No running EMU found</div>'
                '<input type="hidden" name="emu" value="">'
            )

        return """
        <!DOCTYPE html>
        <html lang="en" dir="ltr">
        <head>
            <meta charset="UTF-8">
            <title>FuryBiss By Abou Yassin</title>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #1e1e24; color: #fff; text-align: center; margin: 0; padding: 15px; }}
                .container {{ max-width: 560px; margin: 0 auto; }}
                .box {{ background: #2b2b36; margin: 20px auto; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }}
                h1.main-title {{ color: #00d2ff; font-size: 28px; font-weight: bold; margin-bottom: 20px; text-shadow: 2px 2px 5px rgba(0,0,0,0.6); }}
                h2 {{ color: #00d2ff; margin-top: 0; font-size: 22px; border-bottom: 2px solid #3a3a47; padding-bottom: 10px; }}
                .info, .message {{ background: #3a3a47; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
                .message {{ border-left: 4px solid #00d2ff; text-align: left; }}
                .status {{ font-size: 13px; color: #b8f5ff; word-break: break-all; }}
                label {{ display: block; text-align: left; margin-top: 15px; font-weight: bold; color: #ccc; font-size: 15px; }}
                input[type="text"], input[type="number"], select {{ width: 92%; padding: 10px; margin: 8px 0; border: none; border-radius: 6px; font-size: 16px; text-align: center; background: #fff; color: #000; }}
                .row {{ display: flex; justify-content: space-between; }}
                .row .col {{ width: 48%; }}
                .row .col input, .row .col select {{ width: 85%; }}
                button {{ background: #00d2ff; color: #1e1e24; border: none; padding: 14px 20px; font-size: 17px; font-weight: bold; border-radius: 6px; cursor: pointer; width: 100%; margin-top: 15px; }}
                button:hover {{ background: #00b0d8; }}
                .path {{ font-size: 14px; color: #b8f5ff; word-break: break-all; }}
                .current-key {{ color: #00ff00; letter-spacing: 1px; font-family: monospace; font-size: 16px; }}
                .active-emu {{ width: 92%; padding: 10px; margin: 8px auto; border-radius: 6px; font-size: 16px; text-align: center; background: #142f1f; color: #00ff66; font-weight: bold; }}
                .emu-hint {{ width: 92%; margin: 0 auto 8px auto; color: #b8f5ff; font-size: 12px; text-align: center; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1 class="main-title">🌟 FuryBiss By Abou Yassin 🌟</h1>
                {message_html}

                <div class="box">
                    <div class="info" style="margin-bottom: 0;">
                        <p>Channel: <b>{channel}</b></p>
                        <p>SID (Hex): <b>{sid}</b></p>
                        <p>Current Key: <b class="current-key">{current_key}</b></p>
                    </div>
                </div>

                <div class="box" style="border: 2px solid #ffcc00; background: #2f2b20;">
                    <h2 style="color: #ffcc00; border-bottom-color: #554400;">⚡ Auto BISS ⚡</h2>
                    <p style="font-size: 14px; color: #ccc;">Fetch latest key for <b>{channel}</b> from FuryBiss </p>
                    <form method="POST">
                        <input type="hidden" name="action" value="autofetch">
                        {emu_control_html}
                        <button type="submit" style="background: #ffcc00; color: #000;">Fetch &amp; Restart EMU</button>
                    </form>
                </div>

                <div class="box">
                    <h2>Manual BISS Key</h2>
                    <form method="POST">
                        <input type="hidden" name="action" value="biss">
                        <label>BISS Key (Hex characters):</label>
                        <input type="text" name="biss_key" maxlength="32" placeholder="Example: 11 22 33 66 44 55 66 FF" autocomplete="off">
                        {emu_control_html}
                        <button type="submit">Enter Key &amp; Restart EMU</button>
                    </form>
                </div>

                <div class="box">
                    <h2>Add Server</h2>
                    <form method="POST">
                        <input type="hidden" name="action" value="server">
                        <div class="row">
                            <div class="col">
                                <label>Target File:</label>
                                <select name="server_file">
                                    <option value="oscam.server">oscam.server</option>
                                    <option value="ncam.server">ncam.server</option>
                                </select>
                            </div>
                            <div class="col">
                                <label>Protocol:</label>
                                <select name="protocol">
                                    <option value="cccam">CCcam</option>
                                    <option value="newcamd">Newcamd (Mgcamd)</option>
                                </select>
                            </div>
                        </div>
                        <label>Host / IP:</label>
                        <input type="text" name="host" placeholder="server.dyndns.org" autocomplete="off" style="text-align: left; padding-left: 15px; width: 90%;">
                        <label>Port:</label>
                        <input type="number" name="port" placeholder="12000" autocomplete="off">
                        <div class="row">
                            <div class="col">
                                <label>Username:</label>
                                <input type="text" name="user" placeholder="user" autocomplete="off" style="text-align: left; padding-left: 10px;">
                            </div>
                            <div class="col">
                                <label>Password:</label>
                                <input type="text" name="password" placeholder="pass" autocomplete="off" style="text-align: left; padding-left: 10px;">
                            </div>
                        </div>
                        {emu_control_html}
                        <button type="submit">Add Server &amp; Restart EMU</button>
                    </form>
                </div>

            </div>
        </body>
        </html>
        """.format(
            message_html=message_html,
            channel=html_escape(channel_name),
            sid=html_escape(sid),
            current_key=html_escape(current_key),
            emu_control_html=emu_control_html,
        )

    def do_GET(self):
        try:
            _note_request("GET", getattr(self, 'path', '/'))
            if self.path == '/favicon.ico':
                self._send_empty(204)
                return
            if self.path == '/status':
                snapshot = get_status_snapshot(run_self_test=False)
                lines = [
                    "enabled_setting={0}".format(snapshot.get("enabled_setting")),
                    "running={0}".format(snapshot.get("running")),
                    "primary_url={0}".format(snapshot.get("primary_url")),
                    "self_test_ok={0}".format(snapshot.get("self_test_ok")),
                    "self_test_message={0}".format(snapshot.get("self_test_message")),
                    "last_error={0}".format(snapshot.get("last_error")),
                    "last_request_at={0}".format(snapshot.get("last_request_at")),
                    "log_file={0}".format(snapshot.get("log_file")),
                ]
                self._send_text(200, "\n".join(lines) + "\n")
                return
            html = self.render_form()
            self._send_html(200, html)
        except Exception as error:
            _set_last_error("GET {0} failed: {1}".format(getattr(self, 'path', '/'), _to_text(error)))
            self._send_internal_error_page(error)

    def do_POST(self):
        try:
            _note_request("POST", getattr(self, 'path', '/'))
            content_length = 0
            try:
                content_length = int(self.headers.get('Content-Length', 0))
            except Exception:
                try:
                    content_length = int(self.headers.getheader('Content-Length') or 0)
                except Exception:
                    content_length = 0

            raw_data = self.rfile.read(content_length)
            if PY3:
                raw_data = _to_text(raw_data)
            parsed_data = urlparse.parse_qs(raw_data)

            # تحديد نوع العملية (BISS أو SERVER)
            action = _to_text(parsed_data.get('action', ['biss'])[0]).strip()
            emu = _to_text(parsed_data.get('emu', [''])[0]).strip()
            
            messages = []
            saved_ok = False

            # === نظام إضافة البيس ===
            if action == "biss":
                biss_key = _to_text(parsed_data.get('biss_key', [''])[0]).replace(" ", "").strip().upper()
                info = self.get_current_channel()
                channel_name = info.get("name", "Unknown")
                sid = info.get("sid", "0000")
                path = get_storage_path()

                if not BISS_KEY_RE.match(biss_key):
                    messages.append("BISS key must be exactly 16 hexadecimal characters.")
                else:
                    target_paths = get_storage_write_paths()
                    lines, ecm_pids = build_biss_lines(info, biss_key)
                    written_paths = []
                    failed_paths = []
                    try:
                        for target_path in target_paths:
                            self.append_key_lines(target_path, lines)
                            missing = self.verify_key_lines(target_path, lines)
                            if missing:
                                failed_paths.append("{0} (verification failed)".format(target_path))
                            else:
                                written_paths.append(target_path)

                        if written_paths:
                            saved_ok = True
                            if len(written_paths) == 1:
                                messages.append("BISS key saved and verified in: {0}".format(written_paths[0]))
                            else:
                                messages.append("BISS key saved and verified in {0} files: {1}".format(len(written_paths), ", ".join(written_paths)))
                            
                            _log("saved key for SID {0} into {1}".format(sid, ", ".join(written_paths)))

                        if failed_paths:
                            messages.append("These paths could not be verified: {0}".format(", ".join(failed_paths)))
                            _set_last_error("write verification failed for: {0}".format(", ".join(failed_paths)))
                    except Exception as error:
                        messages.append("Error writing key file: {0}".format(_to_text(error)))
                        _set_last_error("write key file failed: {0}".format(_to_text(error)))
            # === نظام الجلب التلقائي من تليجرام ===
            elif action == "autofetch":
                info = self.get_current_channel()
                sid = info.get("sid", "0000")
                name = info.get("name", "Unknown")
                freq = info.get("freq", "")
                
                messages.append("🔍 Searching for: {0} | {1} | {2}...".format(name, freq, sid))
                fetched_key = self.fetch_telegram_key(sid, name, freq)
                
                if not fetched_key:
                    messages.append("❌ Not Found: No matching key for this channel.")
                elif fetched_key.startswith("ERROR:"):
                    messages.append("❌ Fetch Error: " + fetched_key)
                else:
                    messages.append("✅ Success! Found Key: {0}".format(fetched_key))
                    biss_key = fetched_key
                    
                    target_paths = get_storage_write_paths()
                    lines, ecm_pids = build_biss_lines(info, biss_key)
                    written_paths = []
                    try:
                        for target_path in target_paths:
                            self.append_key_lines(target_path, lines)
                            written_paths.append(target_path)

                        if written_paths:
                            saved_ok = True
                            messages.append("BISS key saved successfully and kept previous keys.")
                    except Exception as error:
                        messages.append("Error writing key file: {0}".format(_to_text(error)))
                        _set_last_error("write key file failed: {0}".format(_to_text(error)))
            # === نظام إضافة السيرفرات (بالإعدادات الاحترافية) ===
            elif action == "server":
                server_file = _to_text(parsed_data.get('server_file', ['oscam.server'])[0]).strip()
                protocol = _to_text(parsed_data.get('protocol', ['cccam'])[0]).strip()
                host = _to_text(parsed_data.get('host', [''])[0]).strip()
                port = _to_text(parsed_data.get('port', [''])[0]).strip()
                user = _to_text(parsed_data.get('user', [''])[0]).strip()
                password = _to_text(parsed_data.get('password', [''])[0]).strip()

                # استخراج المسار الأساسي
                base_dir = os.path.dirname(get_storage_path())
                if not base_dir: 
                    base_dir = "/etc/tuxbox/config"
                target_path = os.path.join(base_dir, server_file)

                reader_name = "{0}_{1}".format(protocol, host.split('.')[0] if '.' in host else host)
                reader_str = ""
                
                if protocol == "cccam":
                    reader_str += "\n####################### CCcam Lines #############################\n"
                    reader_str += "[reader]\n"
                    reader_str += "label                         = {0}\n".format(reader_name)
                    reader_str += "protocol                      = cccam\n"
                    reader_str += "device                        = {0},{1}\n".format(host, port)
                    reader_str += "user                          = {0}\n".format(user)
                    reader_str += "password                      = {0}\n".format(password)
                    reader_str += "inactivitytimeout             = -1\n"
                    reader_str += "reconnecttimeout              = 10\n"
                    reader_str += "disablecrccws_only_for        = 0E00:000000;0B00:000000;09AF:000000;0602:000000;090D:000000;092B:000000;091F:000000;0B01:000000;0500:000000,050800,060200,020810,030830,030B00,032830,032840,032900,032920,032930,041200,042820,032940,041A00,041900,041950,041A30,042800,043330,043800,051B00,007400,007800,021110,023800,050F00,051900,051920,051930,051A00,051A10;09C4:000000;098C:000000;098D:000000;0100:003311,00006C,00006D;1811:003311,003315,023311,003341,00331B,000007,000107;1813:000000,000068;1818:000000,00006C,000007;186C:000000;1819:000000,00006D,000007;1863:003342,003343;1861:000000;1884:000000,000068;183D:000000;183E:000000;4AEE:000001,000003,000300;0987:000000;0BC1:000000;0642:000000;0647:000000;1870:000000;1807:000000\n"
                    reader_str += "group                         = 2,3,4\n"
                    reader_str += "emmcache                      = 2,1,2,1\n"
                    reader_str += "blockemm-unknown              = 1\n"
                    reader_str += "blockemm-u                    = 1\n"
                    reader_str += "blockemm-s                    = 1\n"
                    reader_str += "blockemm-g                    = 1\n"
                    reader_str += "lb_force_fallback             = 1\n"
                    reader_str += "cccwantemu                    = 1\n"
                    reader_str += "disablecrccws                 = 1\n"
                    reader_str += "cccversion                    = 2.3.9\n"
                    reader_str += "ccckeepalive                  = 1\n"
                    reader_str += "cccmaxhops                    = 2\n"
                    reader_str += "audisabled                    = 1\n"

                elif protocol == "newcamd":
                    reader_str += "\n####################### Newcamd ############################\n"
                    reader_str += "[reader]\n"
                    reader_str += "label                         = {0}\n".format(reader_name)
                    reader_str += "enable                        = 1\n"
                    reader_str += "protocol                      = newcamd\n"
                    reader_str += "device                        = {0},{1}\n".format(host, port)
                    reader_str += "key                           = 0102030405060708091011121314\n"
                    reader_str += "user                          = {0}\n".format(user)
                    reader_str += "password                      = {0}\n".format(password)
                    reader_str += "services                      = !powervu_fake,!tandberg_fake,!biss_fake,!afn_fake,1708:000000\n"
                    reader_str += "fallback                      = 1\n"
                    reader_str += "group                         = 1,2,3,4,5,6,7,8,9,10,64\n"
                    reader_str += "disablecrccws                 = 1\n"
                    reader_str += "audisabled                    = 1\n"
                    reader_str += "disablecrccws_only_for        = 1709:000000;1708:000000;1811:003311,003315;09C4:000000;0500:030B00,042820;0604:000000;1819:00006D;0100:00006D;1810:000000;1884:000000;0E00:000000\n"

                try:
                    # تم التعديل هنا: تغيير 'ab' إلى 'wb' لمسح المحتوى القديم
                    with open(target_path, 'wb') as f:
                        f.write(_to_bytes(reader_str))
                    saved_ok = True
                    messages.append("Server successfully replaced in: {0}".format(target_path))
                except Exception as error:
                    messages.append("Error writing server file: {0}".format(_to_text(error)))
                    _set_last_error("write server file failed: {0}".format(_to_text(error)))

            # === نظام ريستارت الإيمو المشترك ورسالة الشاشة ===
            emus_dict = self.get_emus()
            if saved_ok:
                command_str = ""
                emu_label = ""

                try:
                    if emu == "__active__" or not emu or emu not in emus_dict:
                        resolved_emu, resolved_cmd, resolved_label = self.resolve_active_emu(emus_dict)
                        if resolved_cmd:
                            command_str = resolved_cmd
                            emu_label = resolved_label or resolved_emu or "Active EMU"

                    if not command_str and emu and emu in emus_dict:
                        command_str = emus_dict[emu]
                        emu_label = emu
                    elif not command_str and emu and emu not in ("__active__", ""):
                        messages.append("Selected EMU is not available on this device.")
                except Exception as error:
                    messages.append("Error detecting active EMU: {0}".format(_to_text(error)))
                    _set_last_error("detect active EMU failed: {0}".format(_to_text(error)))

                if command_str:
                    try:
                        command_str = _to_text(command_str).strip()
                        if command_str.startswith("(") and command_str.endswith(") &"):
                            command_str = command_str[1:-3].strip()

                        if _run_emu_restart_command(command_str):
                            messages.append("EMU real restart executed: {0}".format(emu_label or "Active EMU"))
                        else:
                            messages.append("EMU restart command finished with an error: {0}".format(emu_label or "Active EMU"))
                            _set_last_error("restart EMU command returned error for: {0}".format(emu_label or "Active EMU"))

                        # --- إظهار رسالة النجاح على شاشة التلفزيون ---
                        try:
                            from Tools.Notifications import AddPopup
                            from Screens.MessageBox import MessageBox

                            if action == "biss":
                                tv_msg = "BISS Key Added Successfully"
                            else:
                                tv_msg = "Server Added Successfully"

                            AddPopup(tv_msg, type=MessageBox.TYPE_INFO, timeout=10, id="FuryBissMsg")
                        except Exception:
                            pass

                    except Exception as error:
                        messages.append("Error restarting EMU {0}: {1}".format(emu_label or "Active EMU", _to_text(error)))
                        _set_last_error("restart EMU failed: {0}".format(_to_text(error)))
                else:
                    messages.append("No running EMU detected. Data saved only.")
                    try:
                        from Tools.Notifications import AddPopup
                        from Screens.MessageBox import MessageBox
                        AddPopup("Saved successfully", type=MessageBox.TYPE_INFO, timeout=5, id="FuryBissMsg")
                    except Exception:
                        pass

            # عرض النتيجة في الصفحة
            message_html = ''
            if messages:
                message_html = '<div class="message">{0}</div>'.format(
                    "<br>".join([html_escape(message) for message in messages])
                )

            response = self.render_form(message_html)
            self._send_html(200, response)
        except Exception as error:
            _set_last_error("POST {0} failed: {1}".format(getattr(self, 'path', '/'), _to_text(error)))
            self._send_internal_error_page(error)



def _serve(httpd):
    global _httpd, _server_thread
    try:
        _log("server started on {0}:{1}".format(HOST, PORT))
        httpd.serve_forever()
    except Exception as error:
        _set_last_error("serve_forever failed on port {0}: {1}".format(PORT, _to_text(error)))
    finally:
        try:
            httpd.server_close()
        except Exception:
            pass
        _server_lock.acquire()
        try:
            if _httpd is httpd:
                _httpd = None
                _server_thread = None
        finally:
            _server_lock.release()
        _log("server stopped on port {0}".format(PORT))



def check_web_license():
    import os
    def get_device_id():
        try:
            with open('/sys/class/net/eth0/address', 'r') as f:
                mac = f.read().strip().replace(':', '').upper()
                if len(mac) >= 6: return mac[-6:]
        except: pass
        return "1A2B3C"
    device_id = get_device_id()
    try: num = int(device_id, 16)
    except: num = 123456
    expected_code = str((num * 7392) + 842105).zfill(8)[::-1][:8]
    
    try:
        if os.path.exists("/etc/tuxbox/config/furybis.license"):
            with open("/etc/tuxbox/config/furybis.license", 'r') as f:
                if f.read().strip() == expected_code:
                    return True
    except: pass
    return False

def start_server():
    global _httpd, _server_thread
    
    ensure_config()
    if not config.plugins.furybis.enabled.value:
        _set_self_test(False, "plugin disabled")
        return False

    _server_lock.acquire()
    try:
        if _httpd is not None and _thread_is_alive(_server_thread):
            return True
        try:
            httpd = ReusableHTTPServer((HOST, PORT), FuryBisHandler)
        except Exception as error:
            _set_last_error("Error starting server on port {0}: {1}".format(PORT, _to_text(error)))
            _set_self_test(False, "listen failed on port {0}".format(PORT))
            return False

        thread = threading.Thread(target=_serve, args=(httpd,))
        try:
            thread.setDaemon(True)
        except Exception:
            try:
                thread.daemon = True
            except Exception:
                pass
        _httpd = httpd
        _server_thread = thread
    finally:
        _server_lock.release()

    try:
        thread.start()
    except Exception as error:
        _server_lock.acquire()
        try:
            _httpd = None
            _server_thread = None
        finally:
            _server_lock.release()
        _set_last_error("thread start failed on port {0}: {1}".format(PORT, _to_text(error)))
        _set_self_test(False, "thread start failed")
        return False

    _clear_last_error()
    _set_self_test(None, "server started")
    return True



def stop_server():
    global _httpd, _server_thread
    httpd = None
    _server_lock.acquire()
    try:
        httpd = _httpd
        _httpd = None
        _server_thread = None
    finally:
        _server_lock.release()

    if httpd is not None:
        try:
            httpd.shutdown()
        except Exception:
            pass
        try:
            httpd.server_close()
        except Exception:
            pass
    _set_self_test(False, "server stopped")



def ensure_server_state():
    ensure_config()
    if config.plugins.furybis.enabled.value:
        return start_server()
    stop_server()
    return False