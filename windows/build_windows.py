"""Build a portable WOPR directory/ZIP with a source-built offline speech engine.

Run on Windows x64 after installing requirements-build.txt and Visual Studio C++
build tools/CMake. This is a maintainer command, not an end-user installer.
Speech source archives and this exact build recipe accompany every package.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ESPEAK_VERSION = "1.52.0"
SONIC_REVISION = "fbf75c3d6d846bad3bb3d456cbc5d07d9fd8c104"
SOURCES = {
    "espeak-ng-1.52.0-source.tar.gz": (
        "https://codeload.github.com/espeak-ng/espeak-ng/tar.gz/refs/tags/1.52.0",
        "bb4338102ff3b49a81423da8a1a158b420124b055b60fa76cfb4b18677130a23",
    ),
    f"sonic-{SONIC_REVISION}.tar.gz": (
        f"https://codeload.github.com/waywardgeek/sonic/tar.gz/{SONIC_REVISION}",
        "715827b5a39b79e56e44397d7b845910df996d4cca74777b3b61629b1ddc98c1",
    ),
}


def run(*args: object, cwd: Path | None = None) -> None:
    subprocess.run([str(a) for a in args], cwd=cwd or ROOT, check=True)


def download_verified(name: str, cache: Path) -> Path:
    url, digest = SOURCES[name]
    destination = cache / name
    cache.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        request = urllib.request.Request(url, headers={"User-Agent": "WOPR-portable-build/1"})
        with urllib.request.urlopen(request, timeout=90) as response:
            data = response.read(40 * 1024 * 1024 + 1)
        if len(data) > 40 * 1024 * 1024:
            raise RuntimeError(f"Source archive exceeds size limit: {name}")
        if hashlib.sha256(data).hexdigest() != digest:
            raise RuntimeError(f"SHA-256 mismatch: {name}")
        destination.write_bytes(data)
    if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
        raise RuntimeError(f"Cached SHA-256 mismatch: {name}; remove it and retry")
    return destination


def extract_source(archive: Path, destination: Path) -> Path:
    """Extract regular files only; materialize safe in-tree symlinks as copies."""
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive) as source:
        members = source.getmembers()
        roots = {Path(member.name).parts[0] for member in members}
        if len(roots) != 1:
            raise RuntimeError("Expected one source archive root")
        for member in members:
            path = (root / member.name).resolve()
            if not path.is_relative_to(root):
                raise RuntimeError("Unsafe source archive path")
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                path.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as content:
                    path.write_bytes(content.read())
            elif not member.issym():
                raise RuntimeError("Unsupported source archive entry")
        for member in members:
            if member.issym():
                path = root / member.name
                target = (path.parent / member.linkname).resolve()
                if not target.is_relative_to(root) or not target.is_file():
                    raise RuntimeError("Unsafe source archive symlink")
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(target, path)
    return root / roots.pop()


def build_speech(work: Path, destination: Path, cache: Path) -> dict:
    archives = [download_verified(name, cache) for name in SOURCES]
    espeak = extract_source(archives[0], work / "sources" / "espeak")
    sonic = extract_source(archives[1], work / "sources" / "sonic")
    build = work / "speech-build"
    options = [
        "-DBUILD_SHARED_LIBS=OFF", "-DBUILD_TESTING=OFF",
        "-DUSE_ASYNC=OFF", "-DUSE_LIBPCAUDIO=OFF", "-DUSE_MBROLA=OFF",
        "-DUSE_LIBSONIC=ON",
        "-DCMAKE_POLICY_DEFAULT_CMP0091=NEW",
        "-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded",
        "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
        "-DFETCHCONTENT_FULLY_DISCONNECTED=ON",
        f"-DFETCHCONTENT_SOURCE_DIR_SONIC-GIT={sonic}",
    ]
    configure = ["cmake", "-S", str(espeak), "-B", str(build), *options]
    if os.name == "nt":
        configure += ["-A", "x64"]
    run(*configure)
    run("cmake", "--build", build, "--config", "Release", "--parallel", "2")
    executables = sorted(build.rglob("espeak-ng.exe" if os.name == "nt" else "espeak-ng"))
    executables = [p for p in executables if p.is_file()]
    if not executables:
        raise RuntimeError("Speech build did not produce espeak-ng")
    data = build / "espeak-ng-data"
    if not (data / "phontab").is_file() or not (data / "en_dict").is_file():
        raise RuntimeError("Speech phonemes/English dictionary missing")
    destination.mkdir(parents=True, exist_ok=True)
    exe = destination / executables[0].name
    shutil.copy2(executables[0], exe)
    shutil.copytree(data, destination / "espeak-ng-data", dirs_exist_ok=True)
    # --path avoids relying on any globally installed espeak voice data.
    result = subprocess.run(
        [str(exe), f"--path={destination}", "--stdout", "--stdin"],
        input=b"Greetings Professor Falken. Shall we play a game?",
        capture_output=True, timeout=30, check=True,
    )
    if result.stdout[:4] != b"RIFF" or len(result.stdout) < 1000:
        raise RuntimeError("Bundled speech self-test failed")
    source_dir = destination / "corresponding-source"
    source_dir.mkdir(exist_ok=True)
    for archive in archives:
        shutil.copy2(archive, source_dir / archive.name)
    shutil.copy2(Path(__file__), source_dir / "build_windows.py")
    (source_dir / "REBUILD.txt").write_text(
        "CORRESPONDING SPEECH SOURCE / REBUILD\n\n"
        "These archives contain unmodified eSpeak NG 1.52.0 and its pinned Sonic dependency.\n"
        "Their licenses and all upstream build scripts are included in the archives.\n"
        "BUILD-INFO.json one directory above records the original configure options and hashes.\n"
        "WOPR's build_windows.py is MIT licensed; see the package LICENSE.\n\n"
        "To reproduce manually on Windows x64 with Visual Studio C++ Build Tools and CMake:\n"
        "1. Extract both .tar.gz archives (Windows tar supports these).\n"
        "2. Set ESPEAK and SONIC to the absolute extracted source directories.\n"
        "3. Configure CMake using the options in BUILD-INFO.json, substituting local paths:\n"
        '   cmake -S "$ESPEAK" -B build -A x64 -DBUILD_SHARED_LIBS=OFF '
        "-DUSE_ASYNC=OFF -DUSE_LIBPCAUDIO=OFF -DUSE_MBROLA=OFF -DUSE_LIBSONIC=ON "
        "-DCMAKE_POLICY_DEFAULT_CMP0091=NEW -DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded "
        "-DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DFETCHCONTENT_FULLY_DISCONNECTED=ON "
        '"-DFETCHCONTENT_SOURCE_DIR_SONIC-GIT=$SONIC"\n'
        "4. cmake --build build --config Release --parallel 2\n"
        "5. Copy build/src/Release/espeak-ng.exe and build/espeak-ng-data/ into one directory.\n"
        "6. Test espeak-ng.exe --path=<that directory> --stdout --stdin, supplying text on stdin.\n"
        "No upstream source modifications, pcaudiolib checkout, audio driver or runtime installer are used.\n",
        encoding="utf-8")
    shutil.copy2(espeak / "COPYING", destination / "COPYING-espeak-ng.txt")
    for filename in ("COPYING", "LICENSE", "COPYING.LIB"):
        if (sonic / filename).is_file():
            shutil.copy2(sonic / filename, destination / f"{filename}-sonic.txt")
    # Preserve notices for embedded speechPlayer/ucd-tools and other components.
    notices = destination / "upstream-notices"
    for path in espeak.rglob("*"):
        if path.is_file() and path.name.lower().startswith(("copying", "license")):
            target = notices / path.relative_to(espeak)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    manifest = {"espeak": ESPEAK_VERSION, "sonic_revision": SONIC_REVISION,
                "sources": {k: {"url": v[0], "sha256": v[1]} for k, v in SOURCES.items()},
                "cmake_configure": configure, "static_runtime": True}
    (destination / "BUILD-INFO.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def copy_runtime_licenses(package: Path) -> None:
    licenses = package / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise RuntimeError("Python's LICENSE.txt is required for the portable build")
    shutil.copy2(python_license, licenses / "Python-LICENSE.txt")
    for name in ("psutil", "pyinstaller"):
        distribution = importlib.metadata.distribution(name)
        copied = 0
        for entry in distribution.files or []:
            if any(part.lower().startswith(("copying", "license")) for part in entry.parts):
                original = Path(distribution.locate_file(entry))
                if original.is_file():
                    target = licenses / name / Path(*entry.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(original, target)
                    copied += 1
        if not copied:
            raise RuntimeError(f"Missing license files for {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--speech-only", action="store_true", help="Validate the speech build on this host")
    args = parser.parse_args()
    if not args.speech_only and (os.name != "nt" or platform.machine().lower() not in ("amd64", "x86_64")):
        parser.error("Portable packages must be built on Windows x64")
    work = ROOT / "build" / "windows"
    cache = ROOT / "build" / "downloads"
    work.mkdir(parents=True, exist_ok=True)
    if args.speech_only:
        build_speech(work, work / "speech", cache)
        return
    package = ROOT / "dist" / "WOPR"
    if package.exists():
        parser.error("dist/WOPR already exists. Move it aside before making a fresh package.")
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--name", "WOPR", "--contents-directory", "_internal",
        "--paths", ROOT / "windows",
        "--distpath", ROOT / "dist", "--workpath", work / "pyinstaller",
        "--specpath", work, "--add-data", f"{ROOT / 'src'}{os.pathsep}src",
        ROOT / "windows" / "wopr.py")
    build_speech(work, package / "speech", cache)
    copy_runtime_licenses(package)
    for name in ("README.md", "SECURITY.md", "LICENSE", "THIRD_PARTY_NOTICES.txt", "FONT_LICENSES.txt", "Launch WOPR.cmd"):
        shutil.copy2(ROOT / name, package / name)
    (package / "START HERE.txt").write_text(
        "WOPR // WINDOWS COMMAND CENTER\n\n"
        "1. Extract the entire ZIP to a folder you can write to.\n"
        "2. Open WOPR.exe (or Launch WOPR.cmd). Do not run as administrator.\n"
        "3. Your browser opens automatically. Click TEST VOICE to hear JOSHUA.\n"
        "4. Public feeds are optional. Local telemetry never uploads.\n"
        "5. Use SHUTDOWN in the dashboard, or Ctrl+C in the console, to stop.\n\n"
        "No Azure account or CLI is needed. The terminal explains commands; it cannot execute them.\n"
        "Offline voice and games work without internet. Keep speech/ and _internal/ beside WOPR.exe.\n"
        "Unsigned build: follow your organization's software policy; never disable security controls.\n"
        "See README.md, SECURITY.md and THIRD_PARTY_NOTICES.txt for details.\n",
        encoding="utf-8")
    run(sys.executable, ROOT / "windows" / "smoke_windows.py", package)
    archive = shutil.make_archive(str(ROOT / "dist" / "WOPR-Windows-x64"), "zip",
                                 root_dir=package.parent, base_dir=package.name)
    digest = hashlib.sha256(Path(archive).read_bytes()).hexdigest()
    Path(archive + ".sha256").write_text(f"{digest}  {Path(archive).name}\n", encoding="ascii")
    print(f"Portable package: {archive}\nSHA-256: {digest}")


if __name__ == "__main__":
    main()
