from Components.config import config, ConfigSubsection, ConfigYesNo, ConfigText, ConfigSelection
import os

# (باقي المتغيرات الخاصة بك زي PLUGIN_VERSION وغيرها...)

config.plugins.furybis = ConfigSubsection()
config.plugins.furybis.enabled = ConfigYesNo(default=True)
config.plugins.furybis.notifications = ConfigYesNo(default=True)

# إضافة خيار مصدر الفيدات الجديد
config.plugins.furybis.feed_source = ConfigSelection(default="telegram", choices=[
   # ("both", "Both"),
    ("telegram", "FuryServer "),
    ("website", "Blogger")
])
# ضيف السطر ده تحت قائمة خيارات الفيدات
config.plugins.furybis.use_proxy = ConfigYesNo(default=False)
config.plugins.furybis.storage_relative_path = ConfigText(default="usr/keys")##################################################

# Created by islam salama

##################################################
def _plugin_dir():
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return "/usr/lib/enigma2/python/Plugins/Extensions/FuryBiss"


def _read_version_file(default="4.1"):
    path = os.path.join(_plugin_dir(), "version.txt")
    try:
        with open(path, "r") as handle:
            value = handle.read().strip()
        cleaned = "".join(ch for ch in value if ch.isdigit() or ch == ".")
        return cleaned or default
    except Exception:
        return default


PLUGIN_VERSION = _read_version_file("4.1")
BASE_CONFIG_DIR = "/etc/tuxbox/config"
DEFAULT_KEY_FILE = "SoftCam.Key"
COMMON_KEY_FILE_VARIANTS = (
    "SoftCam.Key",
    "softcam.key",
    "SoftCam.key",
    "softcam.Key",
    "constant.cw",
    "Constant.cw",
)

try:
    text_type = unicode
except NameError:
    text_type = str


def _to_text(value):
    if value is None:
        return ""
    if isinstance(value, text_type):
        return value
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


def _is_within_base(path):
    path = os.path.normpath(path)
    return path == BASE_CONFIG_DIR or path.startswith(BASE_CONFIG_DIR + os.sep)


def _sanitize_relative_path(value):
    value = _to_text(value).strip().replace("\\", "/")
    if value.startswith(BASE_CONFIG_DIR):
        value = value[len(BASE_CONFIG_DIR):]
    value = value.lstrip("/")
    if not value:
        return DEFAULT_KEY_FILE

    normalized = os.path.normpath(value)
    normalized = _to_text(normalized).replace("\\", "/")
    if normalized in ("", ".", "/", ".."):
        return DEFAULT_KEY_FILE

    while normalized.startswith("../"):
        normalized = normalized[3:]

    normalized = normalized.lstrip("/")
    if not normalized:
        return DEFAULT_KEY_FILE
    return normalized


def _legacy_path_value():
    try:
        subsection = getattr(config.plugins, "furybis", None)
        if subsection and hasattr(subsection, "softcam_path"):
            return subsection.softcam_path.value
    except Exception:
        pass
    return ""


def _relative_from_absolute(path):
    try:
        rel = os.path.relpath(path, BASE_CONFIG_DIR)
    except Exception:
        rel = path
    return _sanitize_relative_path(rel)


def _variant_group_for_name(name):
    lower_name = _to_text(name or "").lower()
    if lower_name == "softcam.key":
        return [item for item in COMMON_KEY_FILE_VARIANTS if item.lower() == "softcam.key"]
    if lower_name == "constant.cw":
        return [item for item in COMMON_KEY_FILE_VARIANTS if item.lower() == "constant.cw"]
    return [_to_text(name or DEFAULT_KEY_FILE)]


def _detect_existing_variant(relative_path):
    relative_path = _sanitize_relative_path(relative_path)
    absolute_path = os.path.normpath(os.path.join(BASE_CONFIG_DIR, relative_path))
    if not _is_within_base(absolute_path):
        return DEFAULT_KEY_FILE

    if os.path.isfile(absolute_path):
        return relative_path

    directory = os.path.dirname(absolute_path) or BASE_CONFIG_DIR
    basename = os.path.basename(absolute_path) or DEFAULT_KEY_FILE
    if os.path.isdir(directory):
        for variant in _variant_group_for_name(basename):
            candidate = os.path.join(directory, variant)
            if os.path.isfile(candidate):
                return _relative_from_absolute(candidate)

    # If user is still on the old lowercase default but an uppercase SoftCam.Key exists,
    # migrate automatically to the existing file.
    if basename.lower() == "softcam.key" and os.path.isdir(directory):
        candidate = os.path.join(directory, DEFAULT_KEY_FILE)
        if os.path.isfile(candidate):
            return _relative_from_absolute(candidate)

    return relative_path


def _detect_initial_relative_path(legacy_path=""):
    if legacy_path:
        return _detect_existing_variant(legacy_path)

    for name in COMMON_KEY_FILE_VARIANTS:
        candidate = os.path.join(BASE_CONFIG_DIR, name)
        if os.path.isfile(candidate):
            return name

    return DEFAULT_KEY_FILE


def ensure_config():
    if not hasattr(config.plugins, "furybis"):
        config.plugins.furybis = ConfigSubsection()
    
    if not hasattr(config.plugins.furybis, "enabled"):
        config.plugins.furybis.enabled = ConfigYesNo(default=True)
        
    # --- السطر الخاص بتفعيل الإشعارات ---
    if not hasattr(config.plugins.furybis, "notifications"):
        config.plugins.furybis.notifications = ConfigYesNo(default=True)
    # ------------------------------------
        
    if not hasattr(config.plugins.furybis, "storage_relative_path"):
        config.plugins.furybis.storage_relative_path = ConfigText(default=DEFAULT_KEY_FILE, fixed_size=False)
    # ضيف السطرين دول تحت إعداد الإشعارات (notifications)
    if not hasattr(config.plugins.furybis, "use_proxy"):
        config.plugins.furybis.use_proxy = ConfigYesNo(default=False)

def get_relative_storage_path():
    ensure_config()
    value = _sanitize_relative_path(config.plugins.furybis.storage_relative_path.value)
    return _detect_existing_variant(value)


def get_storage_path():
    relative = get_relative_storage_path()
    path = os.path.normpath(os.path.join(BASE_CONFIG_DIR, relative))
    if not _is_within_base(path):
        path = os.path.join(BASE_CONFIG_DIR, DEFAULT_KEY_FILE)
    return path


def get_storage_write_paths():
    primary_path = get_storage_path()
    directory = os.path.dirname(primary_path) or BASE_CONFIG_DIR
    basename = os.path.basename(primary_path) or DEFAULT_KEY_FILE
    seen = []

    def add_path(candidate):
        candidate = os.path.normpath(candidate)
        if not _is_within_base(candidate):
            return
        if candidate not in seen:
            seen.append(candidate)

    add_path(primary_path)
    if os.path.isdir(directory):
        for variant in _variant_group_for_name(basename):
            candidate = os.path.join(directory, variant)
            if os.path.isfile(candidate):
                add_path(candidate)

    return seen


def set_storage_path(path):
    ensure_config()
    config.plugins.furybis.storage_relative_path.value = _detect_existing_variant(_sanitize_relative_path(path))


def normalize_stored_values():
    ensure_config()
    config.plugins.furybis.storage_relative_path.value = _detect_existing_variant(
        config.plugins.furybis.storage_relative_path.value
    )
