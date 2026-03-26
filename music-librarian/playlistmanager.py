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

        for track in tracks:
            mbid = track.get("musicBrainzId")
            sid = track.get("id")

            if mbid and sid:
                mapping[mbid] = sid

        print(f"Mapped {len(mapping)} songs")

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
        top_artist_tracks,
        top_tracks,
        top_genre_top_tracks,
        top_genre_single_listens,
        top_genre_wildcard,
        genre_wildcard
    ):
        if wildness == 0:
            base = self._take(top_artist_tracks, 25) + self._take(top_tracks, 25)

        elif wildness == 1:
            base = (
                self._take(top_artist_tracks, 20) +
                self._take(top_tracks, 15) +
                self._take(top_genre_top_tracks, 10) +
                self._take(top_genre_single_listens, 5)
            )

        elif wildness == 2:
            base = (
                self._take(top_artist_tracks, 15) +
                self._take(top_tracks, 10) +
                self._take(top_genre_top_tracks, 10) +
                self._take(top_genre_single_listens, 10) +
                self._take(top_genre_wildcard, 10)
            )

        elif wildness == 3:
            base = (
                self._take(top_artist_tracks, 10) +
                self._take(top_tracks, 5) +
                self._take(top_genre_top_tracks, 10) +
                self._take(top_genre_single_listens, 10) +
                self._take(top_genre_wildcard, 15) +
                self._take(genre_wildcard, 20)
            )

        else:
            raise ValueError("wildness must be 0-3")

        # 🔥 Duplikate entfernen (Reihenfolge behalten)
        seen = set()
        deduped = []
        for t in base:
            if t not in seen:
                seen.add(t)
                deduped.append(t)

        # 🔀 Durchmischen (wichtig!)
        random.shuffle(deduped)

        return deduped