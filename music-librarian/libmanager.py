import time
import requests
from typing import Optional, List

from logger import log
from databasemanager import Track

MB_BASE = "https://musicbrainz.org/ws/2"
USER_AGENT = "MusikmanagementApp/1.0 (your@email.com)"


class MusicBrainzClient:

    _session: Optional[requests.Session] = None
    _last_request_time: float = 0.0

    def __init__(self):
        self.base_url = MB_BASE

    def _get_session(self) -> requests.Session:
        if not self._session:
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": USER_AGENT
            })
        return self._session

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)

    def _get(self, endpoint: str, params: dict) -> dict:
        self._rate_limit()
        session = self._get_session()

        url = f"{self.base_url}/{endpoint}"
        # copy params so we don't mutate caller dict
        params = (params or {}).copy()
        params["fmt"] = "json"

        max_retries = 3
        backoff = 1.0

        for attempt in range(1, max_retries + 1):
            try:
                response = session.get(url, params=params, timeout=10)

                # handle explicit rate-limit from server
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        wait = float(retry_after) if retry_after else backoff
                    except Exception:
                        wait = backoff
                    log.warning("MusicBrainz rate limited, sleeping before retry", wait=wait, attempt=attempt)
                    time.sleep(wait)
                    self._last_request_time = time.time()
                    backoff *= 2
                    continue

                response.raise_for_status()

                try:
                    data = response.json()
                except ValueError as e:
                    log.error("Failed to parse JSON from MusicBrainz", error=str(e), url=url, attempt=attempt)
                    if attempt == max_retries:
                        raise
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                self._last_request_time = time.time()
                return data

            except requests.exceptions.RequestException as e:
                log.warning("MusicBrainz request error, will retry if attempts remain", error=str(e), url=url, attempt=attempt)
                if attempt == max_retries:
                    raise
                time.sleep(backoff)
                backoff *= 2

    def fetch_release(self, mbid: str) -> List[Track]:
        data = self._get(f"release/{mbid}", {
            "inc": "recordings+artists"
        })

        tracks = []

        for medium in data["media"]:
            for t in medium["tracks"]:
                recording = t["recording"]
                artists = []
                for ac in recording["artist-credit"]:
                    if "name" in ac:
                        artists.append(ac["name"])


                tracks.append(
                    Track(
                        artists=artists,
                        album=data["title"],
                        title=recording["title"],
                        duration=recording.get("length"),
                        album_mbid=mbid,
                        track_mbid=recording.get("id")
                    )
                )

        return tracks