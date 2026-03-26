import time
import random
import requests
from typing import Optional, List
from json import JSONDecodeError

from logger import log
from config import LOCAL_MUSICSTREAM_URL, NAVIDROME_USER, NAVIDROME_PASSWORD


class SubsonicClient:

    def _auth_params(self):
        return {
            'u': NAVIDROME_USER,
            'p': NAVIDROME_PASSWORD,
            'v': '1.8.0',
            'c': 'music-analytics',
            'f': 'json',
        }
    
    def _call_api(self, endpoint, params=None):
        try:
            if params is None:
                params = {}
            r = requests.get(
                f"{LOCAL_MUSICSTREAM_URL}/rest/{endpoint}",
                params={**self._auth_params(), **params}, 
                timeout=5
            )
            r.raise_for_status()
            return r.json()["subsonic-response"]
        except requests.RequestException as e:
            log.error("Error while calling subsonic API", error=e)
            return None
        except JSONDecodeError as e:
            log.error("Invalid JSON from Navidrome", error=str(e), data=r.text)
            return None
        except:
            log.error("Unexpected error while calling subsonic API", exc_info=True)
        

    def build_mbid_mapping(self):
        """
        Lädt alle Songs aus Navidrome und mapped:
        musicbrainz_id -> navidrome_song_id

        Speichert Ergebnis direkt in DB (tracks.navidrome_id)
        """

        log.debug("Building MBID → Navidrome ID mapping...")

        mapping = {}
        unmapped = []
        duplicates = 0

        artists = self._get_artists()

        albums = []
        for group in artists:
            for artist in group.get("artist", []):
                artist_id = artist["id"]

                artist_albums = self._get_artist_albums(artist_id)
                albums += artist_albums

        tracks = []
        for album in albums:
            album_id = album["id"]

            album_tracks = self._get_album_tracks(album_id)
            tracks += album_tracks

        log.debug("Collected tracks from Navidrome", tracks=len(tracks))

        for track in tracks:
            mbid = track.get("musicBrainzId")
            sid = track.get("id")

            if mapping[mbid]:
                duplicates+=1
            if mbid and sid:
                mapping[mbid] = sid
            if not mbid:
                title = track.get("title")
                album = track.get("album")
                artist = track.get("artist")
                unmapped.append({
                    "title": title,
                    "album": album,
                    "artist": artist
                })

        log.debug(f"Mapped {len(mapping)} songs")
        log.debug(f"Navidrome contains {duplicates} duplicate songs")
        log.debug(f"{len(unmapped)} songs could not be mapped", unmapped=unmapped)
        return mapping

    def _get_artists(self) -> Optional[List[any]]:
        data = self._call_api("getArtists")      

        if data is None:
            log.warning("No Artists data was found")
            return None
        
        try:
            artists = data["artists"]["index"]
        except (KeyError, TypeError) as e:
            log.error("Missing expected fields in getArtists data", error=str(e), data=data)
            return None
        
        return artists
    
    def _get_artist_albums(self, artist_id) -> Optional[List[any]]:
        params = {
            'id': artist_id,
        }
        
        data = self._call_api("getArtist", params)

        if data is None:
            log.warning("No Album data was found")
            return None

        try:
            albums = data["artist"].get("album", [])
        except (KeyError, TypeError) as e:
            log.error("Missing expected fields in getArtist data", error=str(e), data=data)
            return None
        
        return albums
    
    def _get_album_tracks(self, album_id) -> Optional[List[any]]:
        params = {
            'id': album_id,
        }

        data = self._call_api("getAlbum", params)
        
        if data is None:
            log.warning("No Song data was found")
            return None
        
        try:
            tracks = data["album"].get("song", [])
        except (KeyError, TypeError) as e:
            log.error("Missing expected fields in getAlbum data", error=str(e), data=data)
            return None
        
        return tracks
    
    def create_playlist(self, name, song_ids):
        resp = self._call_api("createPlaylist", {
            "name": name,
            "songId": song_ids 
        })
        return resp["playlist"]["id"]

    def replace_playlist(self, name, navidrome_id, song_ids):
        self.delete_playlist(navidrome_id)

        new_id = self.create_playlist(name, song_ids)

        return new_id
    
    def delete_playlist(self, navidrome_id):
        self._call_api("deletePlaylist", {"id": navidrome_id})
        
    
class MagicPlaylister:

    def _take(self, lst, n):
        return random.sample(lst, min(len(lst), n))

    def make_playlist(
        self,
        wildness,
        length,
        top_artist_tracks,
        top_tracks,
        top_genre_top_tracks,
        top_genre_single_listens,
        top_genre_wildcard,
        genre_wildcard
    ):
        # 🎚️ Gewichtungen pro Wildness-Level
        if wildness == 0:
            weights = {
                "artist": 0.5,
                "tracks": 0.5,
            }

        elif wildness == 1:
            weights = {
                "artist": 0.4,
                "tracks": 0.3,
                "genre_top": 0.2,
                "single": 0.1,
            }

        elif wildness == 2:
            weights = {
                "artist": 0.3,
                "tracks": 0.2,
                "genre_top": 0.2,
                "single": 0.15,
                "genre_wild": 0.15,
            }

        elif wildness == 3:
            weights = {
                "artist": 0.2,
                "tracks": 0.1,
                "genre_top": 0.2,
                "single": 0.15,
                "genre_wild": 0.2,
                "wildcard": 0.15,
            }

        else:
            raise ValueError("wildness must be 0-3")

        counts = {k: int(v * length) for k, v in weights.items()}

        missing = length - sum(counts.values())
        if missing > 0:
            keys = list(counts.keys())
            for _ in range(missing):
                counts[random.choice(keys)] += 1

        # 🎧 Tracks ziehen
        selected = []

        selected += self._take(top_artist_tracks, counts.get("artist", 0))
        selected += self._take(top_tracks, counts.get("tracks", 0))
        selected += self._take(top_genre_top_tracks, counts.get("genre_top", 0))
        selected += self._take(top_genre_single_listens, counts.get("single", 0))
        selected += self._take(top_genre_wildcard, counts.get("genre_wild", 0))
        selected += self._take(genre_wildcard, counts.get("wildcard", 0))

        seen = set()
        deduped = []
        for t in selected:
            if t not in seen:
                seen.add(t)
                deduped.append(t)

        if len(deduped) < length:
            pool = list(set(
                top_artist_tracks +
                top_tracks +
                top_genre_top_tracks +
                top_genre_single_listens +
                top_genre_wildcard +
                genre_wildcard
            ) - set(deduped))

            deduped += self._take(pool, length - len(deduped))

        random.shuffle(deduped)

        return deduped