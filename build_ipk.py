import os
import subprocess
import shutil
import concurrent.futures

# ==========================================
# إعدادات البلوجن
# ==========================================
PKG_NAME = "enigma2-plugin-extensions-furybiss"
PKG_VERSION = "4.1"
MAINTAINER = "Islam Salama"
DESCRIPTION = "FuryBiss - BISS keys and satellite feeds for Enigma2"

py_files = ['__init__.py', 'plugin.py', 'web_server.py']
extra_files = ['plugin.png'] 
icon_files = ['clock.png','dish.png','film.png','key.png','info_hint.png', 'menu.png','satellite.png']
version_file = 'version.txt'
versions = ['3.9', '3.10', '3.11', '3.12', '3.13', '3.14']

architectures = {
    'arm': 'arm-linux-gnueabihf',
    'mipsel': 'mipsel-linux-gnu'
}

print("🔧 جاري عمل Patch لملفات بايثون لتتوافق مع معمارية 32-bit...")
for v in versions:
    src_pyconfig = f"/usr/include/x86_64-linux-gnu/python{v}/pyconfig.h"
    if os.path.exists(src_pyconfig):
        with open(src_pyconfig, 'r') as f:
            content = f.read()
        
        content = content.replace("#define SIZEOF_LONG 8", "#define SIZEOF_LONG 4")
        content = content.replace("#define SIZEOF_VOID_P 8", "#define SIZEOF_VOID_P 4")
        content = content.replace("#define SIZEOF_SIZE_T 8", "#define SIZEOF_SIZE_T 4")
        content = content.replace("#define SIZEOF_PTHREAD_T 8", "#define SIZEOF_PTHREAD_T 4")

        for arch_dir in architectures.values():
            dest_dir = f"/usr/include/{arch_dir}/python{v}"
            os.makedirs(dest_dir, exist_ok=True)
            with open(f"{dest_dir}/pyconfig.h", 'w') as f:
                f.write(content)

print("📝 جاري تحويل ملفات Python إلى C مرة واحدة...")
for f in py_files:
    if os.path.exists(f):
        subprocess.run(["cython", "-3", f])

os.makedirs('IPK_Output', exist_ok=True)
print("🚀 جاري البناء المتوازي (التشفير وبناء الـ IPK في نفس الوقت)...\n")

def build_package(arch_name, arch_triple, v):
    compiler = f"{arch_triple}-gcc"
    build_dir = f'build_{arch_name}_py{v}'
    plugin_path = f'{build_dir}/usr/lib/enigma2/python/Plugins/Extensions/FuryBiss'
    control_path = f'{build_dir}/CONTROL'
    
    os.makedirs(plugin_path, exist_ok=True)
    os.makedirs(control_path, exist_ok=True)
    
    # التشفير إلى .so
    for f in py_files:
        c_file = f.replace('.py', '.c')
        dest_so = f"{plugin_path}/{f.replace('.py', '.so')}"
        if os.path.exists(c_file):
            include_base = f"-I/usr/include/python{v}"
            include_arch = f"-I/usr/include/{arch_triple}/python{v}"
            cmd = f"{compiler} -shared -pthread -fPIC -fwrapv -O2 -Wall -fno-strict-aliasing {include_base} {include_arch} {c_file} -o {dest_so}"
            subprocess.run(cmd, shell=True, capture_output=True)

    # نسخ الملفات
    for ext_file in extra_files:
        if os.path.exists(ext_file): shutil.copy(ext_file, f"{plugin_path}/{ext_file}")

    icon_dest_dir = f"{plugin_path}/icon"
    os.makedirs(icon_dest_dir, exist_ok=True)
    for icon in icon_files:
        if os.path.exists(icon): shutil.copy(icon, f"{icon_dest_dir}/{icon}")

    if os.path.exists(version_file):
        shutil.copy(version_file, f"{plugin_path}/{version_file}")
    else:
        with open(f"{plugin_path}/{version_file}", "w") as f_v: f_v.write(PKG_VERSION)

    # ملف Control
    control_content = f"Package: {PKG_NAME}\nVersion: {PKG_VERSION}\nDescription: {DESCRIPTION}\nSection: extra\nPriority: optional\nMaintainer: {MAINTAINER}\nArchitecture: {arch_name}\nOE: {PKG_NAME}\nHomepage: https://t.me/yassin117\nDepends: \n"
    with open(f"{control_path}/control", "w") as f_ctrl: f_ctrl.write(control_content)

    # تجميع الـ IPK
    subprocess.run(["tar", "-czvf", f"{build_dir}/data.tar.gz", "-C", build_dir, "usr"], capture_output=True)
    subprocess.run(["tar", "-czvf", f"{build_dir}/control.tar.gz", "-C", control_path, "control"], capture_output=True)
    with open(f"{build_dir}/debian-binary", "w") as f_db: f_db.write("2.0\n")
    
    ipk_filename = f"furybiss_{v}_{arch_name}.ipk"
    cwd = os.getcwd()
    subprocess.run(["ar", "-r", f"{cwd}/IPK_Output/{ipk_filename}", "debian-binary", "control.tar.gz", "data.tar.gz"], cwd=build_dir, capture_output=True)
    
    shutil.rmtree(build_dir)
    return f"✅ تم بناء: {ipk_filename}"

# تشغيل البناء المتوازي
with concurrent.futures.ThreadPoolExecutor() as executor:
    futures = []
    for arch_name, arch_triple in architectures.items():
        for v in versions:
            futures.append(executor.submit(build_package, arch_name, arch_triple, v))
    for future in concurrent.futures.as_completed(futures):
        print(future.result())

# تنظيف ملفات الـ C 
for f in py_files:
    c_file = f.replace('.py', '.c')
    if os.path.exists(c_file): os.remove(c_file)

subprocess.run(["zip", "-r", "FuryBiss_IPKs.zip", "IPK_Output"], capture_output=True)
print("\n🎉 تم الانتهاء! الملفات جاهزة ومضغوطة في FuryBiss_IPKs.zip.")
