#!/bin/bash
#
# Command: wget -q --no-check-certificate -O - https://raw.githubusercontent.com/islam-2412/FuryBiss/main/fury/installer.sh | /bin/sh
#
echo "------------------------------------------------------------------------"
echo "                     Installing FuryBiss                           "
echo "------------------------------------------------------------------------"

REPO_BASE_URL="https://raw.githubusercontent.com/islam-2412/FuryBiss/main/fury"
REMOTE_VERSION_URL="${REPO_BASE_URL}/version.txt"
LOCAL_VERSION_FILE="/usr/lib/enigma2/python/Plugins/Extensions/FuryBiss/version.txt"
PLUGIN_DIR="/usr/lib/enigma2/python/Plugins/Extensions/FuryBiss"

# 1. Detect Architecture (arm or mipsel)
echo "Checking system architecture..."
SYS_ARCH=$(uname -m)
case $SYS_ARCH in
    armv*|aarch64)
        ARCH="arm"
        ;;
    mips*)
        ARCH="mipsel"
        ;;
    *)
        echo "Error: Unsupported architecture ($SYS_ARCH) for this plugin."
        exit 1
        ;;
esac
echo "Detected Architecture: $ARCH"
echo ""

# 2. Detect Python version on the receiver
echo "Checking Python version..."
PY_BIN=""
PY_VER=$(python -c 'import sys; print(str(sys.version_info[0])+"."+str(sys.version_info[1]))' 2>/dev/null)
if [ -n "$PY_VER" ]; then
    PY_BIN="python"
else
    PY_VER=$(python3 -c 'import sys; print(str(sys.version_info[0])+"."+str(sys.version_info[1]))' 2>/dev/null)
    if [ -n "$PY_VER" ]; then
        PY_BIN="python3"
    fi
fi

if [ -z "$PY_VER" ] || [ -z "$PY_BIN" ]; then
    echo "Error: Python is not installed or detected on this device!"
    exit 1
fi

echo "Detected Python Version: $PY_VER"

case $PY_VER in
    3.9|3.10|3.11|3.12|3.13|3.14|3.15)
        echo "Python $PY_VER is supported. Proceeding..."
        ;;
    *)
        echo "Error: Python $PY_VER is not supported by this plugin version."
        exit 1
        ;;
esac
echo ""

# 3. Ensure curl exists
echo "Checking if curl is installed..."
if ! command -v curl >/dev/null 2>&1; then
    opkg install curl
fi
sleep 1

read_url_text() {
    curl -fsSLk "$1" 2>/dev/null || wget -q --no-check-certificate -O - "$1" 2>/dev/null
}

normalize_version() {
    echo "$1" | tr -cd '0-9.\n' | head -n 1 | sed 's/^\.*//; s/\.*$//'
}

version_newer_than() {
    "$PY_BIN" - "$1" "$2" <<'PY'
import sys, re

def parse(value):
    parts = re.findall(r'\d+', value or '')
    return tuple(int(p) for p in parts) if parts else (0,)

left = parse(sys.argv[1])
right = parse(sys.argv[2])
sys.exit(0 if left > right else 1)
PY
}

# 4. Compare local version.txt with the remote version.txt before deleting anything
LOCAL_VERSION=""
if [ -f "$LOCAL_VERSION_FILE" ]; then
    LOCAL_VERSION=$(normalize_version "$(cat "$LOCAL_VERSION_FILE" 2>/dev/null)")
fi
REMOTE_VERSION=$(normalize_version "$(read_url_text "$REMOTE_VERSION_URL")")

if [ -n "$REMOTE_VERSION" ] && [ -n "$LOCAL_VERSION" ]; then
    echo "Installed version: $LOCAL_VERSION"
    echo "Server version   : $REMOTE_VERSION"
    if ! version_newer_than "$REMOTE_VERSION" "$LOCAL_VERSION"; then
        echo "FuryBiss is already up to date. Nothing to install."
        exit 0
    fi
    echo "New version detected. Updating now..."
else
    echo "Version check info is incomplete. Continuing with installation..."
fi
echo ""

# 5. Remove the old version completely
echo "Removing old versions of FuryBiss completely..."
sleep 1

# تنظيف مجلد tmp من أي ملفات تثبيت سابقة للإضافة
rm -f /tmp/furybiss_*.ipk

# إزالة الحزم القديمة مع فرض تجاوز الاعتماديات لتجنب توقف عملية الحذف
opkg remove enigma2-plugin-extensions-furybiss --force-depends > /dev/null 2>&1
opkg remove enigma2-plugin-extensions-furybis --force-depends > /dev/null 2>&1

# التأكد من حذف المجلد بالكامل
if [ -d "$PLUGIN_DIR" ] ; then
    rm -rf "$PLUGIN_DIR"
    echo "- Old folder /FuryBiss deleted permanently."
else
    echo "- No old folder found. System is clean."
fi
echo ""

# 6. Download the package that matches the Python version AND Architecture
cd /tmp || exit 1
# دمج المعمارية وإصدار البايثون في اسم الملف
FILE_NAME="furybiss_${PY_VER}_${ARCH}.ipk"
DOWNLOAD_URL="${REPO_BASE_URL}/${FILE_NAME}"

echo "Downloading FuryBiss package for Python ${PY_VER} (${ARCH})..."

# التحميل باستخدام curl مع وجود wget كبديل
if command -v curl >/dev/null 2>&1; then
    curl -fSLk "${DOWNLOAD_URL}" -o "/tmp/${FILE_NAME}"
else
    wget -q --no-check-certificate "${DOWNLOAD_URL}" -O "/tmp/${FILE_NAME}"
fi

# التحقق من وجود الملف وحجمه
if [ ! -s "/tmp/${FILE_NAME}" ] || [ $(stat -c%s "/tmp/${FILE_NAME}") -lt 1000 ]; then
    echo "Error: Failed to download ${FILE_NAME} or file is corrupted."
    echo "Please check if the file exists on the GitHub repository."
    rm -f "/tmp/${FILE_NAME}"
    exit 1
fi
sleep 1

# 7. Install the update
echo ""
echo "Installing new version...."
opkg install --force-reinstall --force-overwrite "/tmp/${FILE_NAME}"
if [ $? -ne 0 ]; then
    echo "Error: Installation of FuryBiss failed."
    rm -f "/tmp/${FILE_NAME}"
    exit 1
fi

echo ""
sleep 1

echo "Cleaning up temporary files..."
rm -f "/tmp/${FILE_NAME}"

echo "Done"
echo "------------------------------------------------------------------------"
echo "        This work is exclusive to Islam Salama (( Skin Fury-FHD ))      "
echo "------------------------------------------------------------------------"
echo "                              Abou Yassin                               "
echo "                   FuryBiss Installed Successfully                      "
echo "------------------------------------------------------------------------"
echo ""

# 8. Restart Enigma2 GUI
echo "Please wait..."
echo "Restarting Enigma2 GUI in 3 seconds to apply changes..."
sleep 3
killall -9 enigma2

exit 0