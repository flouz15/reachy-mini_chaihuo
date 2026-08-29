"""Local background-music discovery and deterministic command parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BGM_DIR = PROJECT_ROOT / "bgm" / "compatible"


@dataclass(frozen=True)
class BgmTrack:
    id: str
    title: str
    path: Path

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "title": self.title}


def clean_track_title(path: Path) -> str:
    title = path.stem
    title = re.sub(r"\s*\[mqms\d*\]\s*", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\.(?:mgg\d*|mflac\d*|qmc\d*)$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"^\d{10,}(?=\D)", "", title)
    title = re.sub(r"[-_ ]*ringtone$", "", title, flags=re.IGNORECASE)
    return " ".join(title.replace("_", " ").split()).strip() or path.stem


def list_bgm_tracks(directory: Path | str = DEFAULT_BGM_DIR) -> list[BgmTrack]:
    directory = Path(directory)
    if not directory.is_dir():
        return []
    tracks: list[BgmTrack] = []
    for path in sorted(directory.glob("*.wav"), key=lambda item: item.name.casefold()):
        if path.is_file():
            tracks.append(BgmTrack(id=path.name, title=clean_track_title(path), path=path))
    return tracks


def resolve_bgm_track(
    track_id: str, directory: Path | str = DEFAULT_BGM_DIR
) -> BgmTrack | None:
    wanted = Path(str(track_id)).name
    return next((track for track in list_bgm_tracks(directory) if track.id == wanted), None)


def parse_bgm_command(
    text: str, tracks: list[BgmTrack]
) -> tuple[str, BgmTrack | None] | None:
    normalized = " ".join(text.split()).strip()
    compact = normalized.replace(" ", "")
    if not compact:
        return None
    stop_words = ("停止音乐", "关闭音乐", "关掉音乐", "音乐停止", "音乐关掉", "别放音乐")
    if any(word in compact for word in stop_words):
        return "stop", None
    play_words = ("播放音乐", "放音乐", "播放歌曲", "放首歌", "来首歌", "来点音乐")
    if not any(word in compact for word in play_words):
        return None
    lowered = compact.casefold()
    selected = None
    for track in tracks:
        aliases = {track.title, Path(track.id).stem}
        aliases.update(re.split(r"\s*[-—–]\s*", track.title))
        if any(
            alias.replace(" ", "").casefold() in lowered
            for alias in aliases
            if len(alias.strip()) >= 2
        ):
            selected = track
            break
    return "play", selected
