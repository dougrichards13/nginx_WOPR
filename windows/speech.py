"""Distinctive local formant voice, never cloud speech or shell execution."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading


class BusyError(Exception):
    pass


def discover():
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
        roots.append(Path(getattr(sys, "_MEIPASS", roots[0])))
    else:
        roots.extend((Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent))
    for root in roots:
        candidate = root / "speech" / "espeak-ng.exe"
        if candidate.is_file():
            return str(candidate)
    if not getattr(sys, "frozen", False):
        for name in ("espeak-ng", "espeak"):
            executable = shutil.which(name)
            if executable:
                return executable
        if os.name == "nt":
            for variable in ("ProgramFiles", "ProgramFiles(x86)"):
                base = Path(os.environ.get(variable, r"C:\Program Files"))
                for folder in ("eSpeak NG", "espeak-ng"):
                    executable = base / folder / "espeak-ng.exe"
                    if executable.is_file():
                        return str(executable)
    return None


class Speech:
    def __init__(self, executable=None):
        self.executable = executable if executable is not None else discover()
        self.slot = threading.BoundedSemaphore(1)
        self.closed = threading.Event()

    def close(self):
        self.closed.set()
        # Synthesis itself has a 15-second timeout. Do not orphan its child.
        if self.slot.acquire(timeout=16):
            self.slot.release()

    def capability(self):
        return {"available": bool(self.executable),
                "engine": ("espeak-ng" if "espeak-ng" in Path(self.executable).name.lower()
                           else "espeak") if self.executable else None}

    def synthesize(self, data):
        text = data.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 500 or "\x00" in text:
            raise ValueError("text must contain 1 to 500 characters")
        values = []
        for key, default, low, high in (("speed", 145, 80, 300), ("pitch", 30, 0, 99), ("volume", 130, 0, 200)):
            value = data.get(key, default)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{key} must be an integer from {low} to {high}")
            values.append(str(value))
        if not self.executable:
            raise FileNotFoundError("Local eSpeak is unavailable")
        if not self.slot.acquire(blocking=False):
            raise BusyError("Voice is busy")
        try:
            if self.closed.is_set():
                raise FileNotFoundError("Voice has stopped")
            args = [self.executable, "--stdin", "--stdout", "-v", "en-us",
                    "-s", values[0], "-p", values[1], "-a", values[2]]
            parent = Path(self.executable).resolve().parent
            if (parent / "espeak-ng-data").is_dir():
                args.extend(("--path", str(parent)))
            with tempfile.TemporaryFile() as output:
                subprocess.run(args, input=text.encode("utf-8"), stdout=output,
                               stderr=subprocess.DEVNULL, timeout=15, check=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if output.tell() > 8 * 1024 * 1024:
                    raise ValueError("Voice response exceeded limit")
                output.seek(0)
                wav = output.read(8 * 1024 * 1024 + 1)
            if len(wav) < 44 or wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
                raise ValueError("Local synthesizer did not return a WAV")
            return wav
        finally:
            self.slot.release()
