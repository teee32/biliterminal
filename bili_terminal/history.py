from __future__ import annotations

import json
import os
from typing import Any

from .models import (
    VideoItem,
    item_from_payload,
    item_to_history_payload,
    video_key_from_item,
    video_key_from_payload,
)
from .paths import default_history_path
from .textutil import normalize_keyword

MAX_HISTORY_ITEMS = 40
MAX_FAVORITE_ITEMS = 200


class HistoryStore:
    def __init__(
        self,
        path: str | None = None,
        max_items: int = MAX_HISTORY_ITEMS,
        max_favorites: int = MAX_FAVORITE_ITEMS,
    ) -> None:
        self.path = path or default_history_path()
        self.max_items = max_items
        self.max_favorites = max_favorites
        self._data: dict[str, list[Any]] = {
            "recent_keywords": [],
            "recent_videos": [],
            "favorite_videos": [],
        }
        self._favorite_keys: set[str] = set()
        self._recent_videos_cache: list[VideoItem] | None = None
        self._favorite_videos_cache: list[VideoItem] | None = None
        self.load()

    def _rebuild_favorite_keys(self) -> None:
        self._favorite_keys = {
            key
            for key in (video_key_from_payload(video) for video in self._data["favorite_videos"])
            if key is not None
        }

    def _invalidate_caches(self) -> None:
        self._recent_videos_cache = None
        self._favorite_videos_cache = None

    def load(self) -> None:
        changed = False
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            return
        except (json.JSONDecodeError, OSError):
            return
        if isinstance(payload, dict):
            keywords = payload.get("recent_keywords")
            videos = payload.get("recent_videos")
            favorites = payload.get("favorite_videos")
            if isinstance(keywords, list):
                normalized_keywords: list[str] = []
                for item in keywords:
                    normalized = normalize_keyword(str(item))
                    if not normalized:
                        changed = True
                        continue
                    if normalized != str(item).strip():
                        changed = True
                    if normalized not in normalized_keywords:
                        normalized_keywords.append(normalized)
                self._data["recent_keywords"] = normalized_keywords[: self.max_items]
            if isinstance(videos, list):
                self._data["recent_videos"] = [item for item in videos if isinstance(item, dict)][: self.max_items]
            if isinstance(favorites, list):
                normalized_favorites: list[dict[str, Any]] = []
                seen_keys: set[str] = set()
                for item in favorites:
                    if not isinstance(item, dict):
                        changed = True
                        continue
                    key = video_key_from_payload(item)
                    if key is None or key in seen_keys:
                        changed = True
                        continue
                    seen_keys.add(key)
                    normalized_favorites.append(item)
                self._data["favorite_videos"] = normalized_favorites[: self.max_favorites]
        self._rebuild_favorite_keys()
        self._invalidate_caches()
        if changed:
            self.save()

    def save(self) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temp_path = f"{self.path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(self._data, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, self.path)

    def add_keyword(self, keyword: str) -> None:
        cleaned = normalize_keyword(keyword)
        if not cleaned:
            return
        keywords = [item for item in self._data["recent_keywords"] if item != cleaned]
        keywords.insert(0, cleaned)
        self._data["recent_keywords"] = keywords[: self.max_items]
        self.save()

    def add_video(self, item: VideoItem) -> None:
        payload = item_to_history_payload(item)
        key = video_key_from_payload(payload)
        videos = [video for video in self._data["recent_videos"] if video_key_from_payload(video) != key]
        videos.insert(0, payload)
        self._data["recent_videos"] = videos[: self.max_items]
        self._recent_videos_cache = None
        self.save()

    def add_favorite(self, item: VideoItem) -> bool:
        payload = item_to_history_payload(item)
        key = video_key_from_payload(payload)
        if key is None:
            return False
        favorites = [video for video in self._data["favorite_videos"] if video_key_from_payload(video) != key]
        already_exists = len(favorites) != len(self._data["favorite_videos"])
        favorites.insert(0, payload)
        self._data["favorite_videos"] = favorites[: self.max_favorites]
        self._rebuild_favorite_keys()
        self._favorite_videos_cache = None
        self.save()
        return not already_exists

    def remove_favorite(self, target: VideoItem | str) -> bool:
        key = target if isinstance(target, str) else video_key_from_item(target)
        if key is None:
            return False
        favorites = [video for video in self._data["favorite_videos"] if video_key_from_payload(video) != key]
        changed = len(favorites) != len(self._data["favorite_videos"])
        if changed:
            self._data["favorite_videos"] = favorites
            self._favorite_keys.discard(key)
            self._favorite_videos_cache = None
            self.save()
        return changed

    def toggle_favorite(self, item: VideoItem) -> bool:
        if self.is_favorite(item):
            self.remove_favorite(item)
            return False
        self.add_favorite(item)
        return True

    def is_favorite(self, item: VideoItem | None) -> bool:
        key = video_key_from_item(item)
        return key is not None and key in self._favorite_keys

    def get_recent_keywords(self, limit: int = 10) -> list[str]:
        return list(self._data["recent_keywords"][:limit])

    def get_recent_videos(self, limit: int = 20) -> list[VideoItem]:
        if self._recent_videos_cache is None:
            self._recent_videos_cache = [item_from_payload(payload) for payload in self._data["recent_videos"]]
        return self._recent_videos_cache[:limit]

    def get_favorite_videos(self, limit: int | None = None) -> list[VideoItem]:
        if self._favorite_videos_cache is None:
            self._favorite_videos_cache = [item_from_payload(payload) for payload in self._data["favorite_videos"]]
        if limit is None:
            return list(self._favorite_videos_cache)
        return self._favorite_videos_cache[:limit]
