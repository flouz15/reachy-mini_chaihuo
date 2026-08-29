#!/usr/bin/env python3
"""Convert ordinary BGM audio into Reachy-friendly mono PCM WAV files."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "bgm"
OUTPUT_DIR = SOURCE_DIR / "compatible"
SUPPORTED = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus"}


def output_name(path: Path) -> str:
    name = re.sub(r"\s*\[mqms\d*\]\s*", " ", path.stem, flags=re.IGNORECASE)
    name = re.sub(r"\.(?:mgg\d*|mflac\d*|qmc\d*)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^\d{10,}(?=\D)", "", name)
    name = re.sub(r"[-_ ]*ringtone$", "", name, flags=re.IGNORECASE)
    name = " ".join(name.split()).strip() or path.stem
    return f"{name}.wav"


def convert(path: Path) -> tuple[bool, str]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / output_name(path)
    temporary = output.with_suffix(".tmp.wav")
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "24000",
        "-c:a",
        "pcm_s16le",
        str(temporary),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not temporary.is_file():
        temporary.unlink(missing_ok=True)
        detail = (result.stderr or "无法解码").strip().splitlines()[-1]
        return False, detail
    temporary.replace(output)
    return True, str(output.relative_to(ROOT))


def main() -> int:
    sources = sorted(
        path
        for path in SOURCE_DIR.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SUPPORTED
        and not (path.parent == OUTPUT_DIR and path.suffix.lower() == ".wav")
    )
    if not sources:
        print("bgm 中没有可转换的音频文件")
        return 0
    converted = 0
    for path in sources:
        ok, detail = convert(path)
        if ok:
            converted += 1
            print(f"[OK] {path.name} -> {detail}")
        else:
            print(f"[SKIP] {path.name}: {detail}")
    print(f"converted={converted} skipped={len(sources) - converted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
