from typing import Optional
from dataclasses import dataclass

import psycopg2
from psycopg2.extras import RealDictCursor

from logger import log
from sql_queries import INSERT_SQL, DELETE_SQL, AUTO_GENERATE_PLAYLIST

@dataclass
class Track:
    artists: list[str]
    album: str
    title: str
    duration: int
    album_mbid: Optional[str] = None
    track_mbid: Optional[str] = None    


class DatabaseWriter:

    def __init__(self, conn):
        self.conn = conn

    def insert_track(self, track: Track) -> None:
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(INSERT_SQL, {
                    "artist_names": track.artists,
                    "album_title": track.album,
                    "track_title": track.title,
                    "duration_ms": track.duration,
                    "album_mbid": track.album_mbid,
                    "track_mbid": track.track_mbid
                })
            self.conn.commit()
            log.debug("Inserted track", track_title=track.title)
        except psycopg2.Error as e:
            log.error("Error inserting track", error=str(e), exc_info=True)
            self.conn.rollback()

    def bulk_insert_tracks(self, tracks: list[Track]) -> int:
        if not tracks:
            return 0

        for track in tracks:
            self.insert_track(track)

        return len(tracks)
    
    def delete_album(self, mbid: str):
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(DELETE_SQL, {
                    "album_mbid": mbid
                })
                result = cur.fetchone()
            self.conn.commit()
            log.debug("Deleted album", album_mbid=mbid)
        except psycopg2.Error as e:
            log.error("Error inserting track", error=str(e), exc_info=True)
            self.conn.rollback()

        return {
            "deleted_artists": result[2],
            "deleted_tracks": result[1]
        }
    
    def insert_navidrome_ids(self, mapping):
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    CREATE TEMP TABLE tmp_mapping (
                        mbid TEXT,
                        navidrome_id TEXT
                    )
                """)

                cur.executemany("""
                    INSERT INTO tmp_mapping (mbid, navidrome_id)
                    VALUES (%s, %s)
                """, [(mbid, sid) for mbid, sid in mapping.items()])

                cur.execute("""
                    UPDATE tracks t
                    SET navidrome_id = m.navidrome_id
                    FROM tmp_mapping m
                    WHERE t.mbid = m.mbid
                """)

            self.conn.commit()
        except psycopg2.Error as e:
            log.error("Error inserting navidrome IDs", error=str(e), exc_info=True)
            self.conn.rollback()

    def update_playlist_navidrome_id(self, playlist_id, navidrome_id):
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    UPDATE playlists
                    SET navidrome_id = %s
                    WHERE id = %s
                """, (navidrome_id, playlist_id,))
            self.conn.commit()
        except psycopg2.Error as e:
            log.error("Error inserting playlist navidrome ID", error=str(e), exc_info=True, playlist=playlist_id)
            self.conn.rollback()

    def insert_auto_playlist(self, name: str, date: str):
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(AUTO_GENERATE_PLAYLIST, {
                    "name": name,
                    "date": date,
                })
            self.conn.commit()
            log.debug("Created new playlist", name=name, date=date)
        except psycopg2.Error as e:
            log.error("Error creating playlist", error=str(e), exc_info=True, name=name, date=date)
            self.conn.rollback()

    def create_empty_playlist(self, name: str, date: str):
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO playlists (name, month, description)
                    VALUES (%(name)s, %(date)s, 'Auto-generated, but fancy!')
                    RETURNING id
                """, {
                    "name": name,
                    "date": date,
                })
            row = cur.fetchone()
            log.debug("Created new empty playlist", name=name, date=date, playlist=row[0])
            return row[0]
        except psycopg2.Error as e:
            log.error("Error creating empty playlist", error=str(e), exc_info=True, name=name, date=date)
            self.conn.rollback()
            return None
        
    def delete_playlist(self, playlist_id):
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    DELETE FROM playlists
                    WHERE id = %s
                """, 
                (playlist_id,))
            self.conn.commit()
            log.debug("Removed playlist", playlist=playlist_id)
        except psycopg2.Error as e:
            log.error("Error removing playlist", error=str(e), exc_info=True, playlist=playlist_id)
            self.conn.rollback()

    def update_playlist_name(self, playlist_id, name):
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    UPDATE playlists
                    SET name = %s
                    WHERE id = %s
                """, 
                (name, playlist_id,))
            self.conn.commit()
            log.debug("Updated playlist", playlist=playlist_id)
        except psycopg2.Error as e:
            log.error("Error updating playlist", error=str(e), exc_info=True, playlist=playlist_id)
            self.conn.rollback()

    def insert_tracks_into_playlist(self, playlist_id: int, tracks):
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO playlist_tracks (playlist_id, track_id, position)
                    SELECT
                        %(playlist_id)s,
                        UNNEST(%(tracks)s::int[]),
                        ROW_NUMBER() OVER ()
                """, {
                    "playlist_id": playlist_id,
                    "tracks": tracks,
                })
            self.conn.commit()
            log.debug("Added tracks to playlist", playlist=playlist_id, tracks=len(tracks))
        except psycopg2.Error as e:
            log.error("Error adding tracks to playlist", error=str(e), exc_info=True, playlist=playlist_id)
            self.conn.rollback()

    def delete_track_from_playlist(self, playlist_id, track_id):
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    DELETE FROM playlist_tracks
                    WHERE playlist_id = %s
                        AND track_id = %s
                """, (playlist_id, track_id,))
            self.conn.commit()
            log.debug("Removed track from playlist", playlist=playlist_id, track=track_id)
        except psycopg2.Error as e:
            log.error("Error removing track from playlist", error=str(e), exc_info=True, playlist=playlist_id, track=track_id)
            self.conn.rollback()
    
    
class DatabaseReader:

    def __init__(self, conn):
        self.conn = conn

    def load_playlists(self):
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT id, name, navidrome_id
                    FROM playlists
                    ORDER BY month
                """)
                rows = cur.fetchall()
        except psycopg2.Error as e:
            log.error("Error reading playlists from Database", error=str(e), exc_info=True)
            self.conn.rollback()

        playlists = []
        for row in rows:
            playlists.append({
                "playlist_id": row[0],
                "name": row[1],
                "navidrome_id": row[2]
            })
        return playlists
    
    def search_playlist(self, playlist_id: int):
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT id, name, navidrome_id
                    FROM playlists
                    ORDER BY month
                    WHERE id = %s
                """, (playlist_id,))
                row =  cur.fetchone()
        except psycopg2.Error as e:
            log.error("Error reading playlist by name from Database", error=str(e), exc_info=True, playlist=playlist_id)
            self.conn.rollback()

        return {
            "playlist_id": row[0],
            "name": row[1],
            "navidrome_id": row[2]
        }

    def load_playlist_tracks(self, playlist_id):
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT t.id, t.title, a.name, t.mbid, t.navidrome_id
                    FROM playlist_tracks pt
                    JOIN tracks t ON t.id = pt.track_id
                    LEFT JOIN artist_tracks art ON art.track_id = t.id
                    LEFT JOIN artists a ON a.id = art.artist_id
                    WHERE pt.playlist_id = %s
                """, (playlist_id,))
                rows = cur.fetchall()
        except psycopg2.Error as e:
            log.error("Error reading playlist tracks", error=str(e), exc_info=True, playlist=playlist_id)
            self.conn.rollback()

        tracks = {}
        for track in rows:
            tracks.append({
                "id": track[0],
                "title": track[1],
                "artist": track[2],
                "mbid": track[3],
                "navidrome_id": track[4],
            })

        return tracks


    def get_top_artist_tracks(self, date):
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    WITH top_artists AS (
                        SELECT a.id AS artist_id, COUNT(*) AS play_count
                        FROM artists a
                        LEFT JOIN artist_tracks art ON a.id = art.artist_id
                        LEFT JOIN tracks t ON t.id = art.track_id
                        LEFT JOIN track_plays tp ON t.id = tp.track_id
                        WHERE played_at >= TIMESTAMP %(date)s
                            AND played_at < TIMESTAMP %(date)s + interval '1 month'
                        GROUP BY a.id
                        ORDER BY play_count DESC
                        LIMIT 20
                    ), 

                    artist_tracks AS (
                        SELECT t.navidrome_id AS track_id, t.title, a.id, a.name,
                            ROW_NUMBER() OVER (PARTITION BY a.id ORDER BY COUNT(tp.*) DESC) AS rank
                        FROM tracks t
                        LEFT JOIN artist_tracks art ON art.track_id = t.id
                        LEFT JOIN artists a ON a.id = art.artist_id
                        JOIN track_plays tp ON tp.track_id = t.id
                        WHERE played_at >= TIMESTAMP %(date)s
                            AND played_at < TIMESTAMP %(date)s + interval '1 month'
                            AND art.artist_id IN (SELECT artist_id FROM top_artists)
                        GROUP BY t.navidrome_id, t.title, a.id, a.name
                    )
                            
                    SELECT track_id
                    FROM artist_tracks
                    WHERE rank <= 3
                """, {
                    "date": date,
                })
                return cur.fetchall()
        except psycopg2.Error as e:
            log.error("Error reading top artist tracks from Database", error=str(e), exc_info=True, date=date)
            self.conn.rollback()

    def get_top_tracks(self, date):
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    WITH top_tracks AS (
                        SELECT t.navidrome_id AS track_id, t.title, COUNT(*) AS play_count
                        FROM tracks t
                        JOIN track_plays tp ON tp.track_id = t.id
                        WHERE played_at >= TIMESTAMP %(date)s
                            AND played_at < TIMESTAMP %(date)s + interval '1 month'
                        GROUP BY t.navidrome_id, t.title
                        ORDER BY play_count DESC
                        LIMIT 30
                    )
                            
                    SELECT track_id
                    FROM top_tracks
                """, {
                    "date": date,
                })
                return cur.fetchall()
        except psycopg2.Error as e:
            log.error("Error reading top tracks from Database", error=str(e), exc_info=True, date=date)
            self.conn.rollback()

    def get_top_genre_top_tracks(self, date):
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    WITH month_plays AS (
                        SELECT tp.track_id
                        FROM track_plays tp
                        WHERE tp.played_at >= TIMESTAMP %(date)s
                        AND tp.played_at < TIMESTAMP %(date)s + interval '1 month'
                    ),

                    top_genre AS (
                        SELECT ag.genre_id, COUNT(*) AS play_count
                        FROM month_plays mp
                        JOIN artist_tracks at ON at.track_id = mp.track_id
                        JOIN artist_genres ag ON ag.artist_id = at.artist_id
                        GROUP BY ag.genre_id
                        ORDER BY play_count DESC
                        LIMIT 1
                    ),

                    genre_tracks AS (
                        SELECT t.navidrome_id, COUNT(mp.track_id) AS plays
                        FROM tracks t
                        JOIN artist_tracks at ON at.track_id = t.id
                        JOIN artist_genres ag ON ag.artist_id = at.artist_id
                        JOIN top_genre tg ON tg.genre_id = ag.genre_id
                        LEFT JOIN month_plays mp ON mp.track_id = t.id
                        GROUP BY t.navidrome_id
                    )

                    SELECT id
                    FROM genre_tracks
                    ORDER BY plays DESC
                    LIMIT 10
                """, {
                    "date": date,
                })
                return cur.fetchall()
        except psycopg2.Error as e:
            log.error("Error reading top genre tracks from Database", error=str(e), exc_info=True, date=date)
            self.conn.rollback()

    def get_top_genre_single_listens(self, date):
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    WITH month_plays AS (
                        SELECT tp.track_id, COUNT(*) AS plays
                        FROM track_plays tp
                        WHERE tp.played_at >= TIMESTAMP %(date)s
                        AND tp.played_at < TIMESTAMP %(date)s + interval '1 month'
                        GROUP BY tp.track_id
                    ),

                    top_genre AS (
                        SELECT ag.genre_id, COUNT(*) AS play_count
                        FROM track_plays tp
                        JOIN artist_tracks at ON at.track_id = tp.track_id
                        JOIN artist_genres ag ON ag.artist_id = at.artist_id
                        WHERE tp.played_at >= TIMESTAMP %(date)s
                        AND tp.played_at < TIMESTAMP %(date)s + interval '1 month'
                        GROUP BY ag.genre_id
                        ORDER BY play_count DESC
                        LIMIT 1
                    )

                    SELECT t.navidrome_id
                    FROM month_plays mp
                    JOIN tracks t ON t.id = mp.track_id
                    JOIN artist_tracks at ON at.track_id = t.id
                    JOIN artist_genres ag ON ag.artist_id = at.artist_id
                    JOIN top_genre tg ON tg.genre_id = ag.genre_id
                    WHERE mp.plays = 1
                """, {
                    "date": date,
                })
                return cur.fetchall()
        except psycopg2.Error as e:
            log.error("Error reading single listen tracks from Database", error=str(e), exc_info=True, date=date)
            self.conn.rollback()

    def get_top_genre_wildcard(self, date):
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    WITH month_tracks AS (
                        SELECT DISTINCT track_id
                        FROM track_plays
                        WHERE played_at >= TIMESTAMP %(date)s
                        AND played_at < TIMESTAMP %(date)s + interval '1 month'
                    ),

                    top_genre AS (
                        SELECT ag.genre_id
                        FROM track_plays tp
                        JOIN artist_tracks at ON at.track_id = tp.track_id
                        JOIN artist_genres ag ON ag.artist_id = at.artist_id
                        WHERE tp.played_at >= TIMESTAMP %(date)s
                        AND tp.played_at < TIMESTAMP %(date)s + interval '1 month'
                        GROUP BY ag.genre_id
                        ORDER BY COUNT(*) DESC
                        LIMIT 1
                    )

                    SELECT t.navidrome_id
                    FROM tracks t
                    JOIN artist_tracks at ON at.track_id = t.id
                    JOIN artist_genres ag ON ag.artist_id = at.artist_id
                    JOIN top_genre tg ON tg.genre_id = ag.genre_id
                    LEFT JOIN month_tracks mt ON mt.track_id = t.id
                    WHERE mt.track_id IS NULL
                    ORDER BY random()
                    LIMIT 20
                """, {
                    "date": date,
                })
                return cur.fetchall()
        except psycopg2.Error as e:
            log.error("Error reading top genre wildcard from Database", error=str(e), exc_info=True, date=date)
            self.conn.rollback()

    def get_genre_wildcard(self, date):
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    WITH month_tracks AS (
                        SELECT DISTINCT track_id
                        FROM track_plays
                        WHERE played_at >= TIMESTAMP %(date)s
                        AND played_at < TIMESTAMP %(date)s + interval '1 month'
                    ),

                    month_genres AS (
                        SELECT DISTINCT ag.genre_id
                        FROM track_plays tp
                        JOIN artist_tracks at ON at.track_id = tp.track_id
                        JOIN artist_genres ag ON ag.artist_id = at.artist_id
                        WHERE tp.played_at >= TIMESTAMP %(date)s
                        AND tp.played_at < TIMESTAMP %(date)s + interval '1 month'
                    )

                    SELECT t.navidrome_id
                    FROM tracks t
                    JOIN artist_tracks at ON at.track_id = t.id
                    JOIN artist_genres ag ON ag.artist_id = at.artist_id
                    JOIN month_genres mg ON mg.genre_id = ag.genre_id
                    LEFT JOIN month_tracks mt ON mt.track_id = t.id
                    WHERE mt.track_id IS NULL
                    ORDER BY random()
                    LIMIT 30
                """, {
                    "date": date,
                })
                return cur.fetchall()
        except psycopg2.Error as e:
            log.error("Error reading wildcard from Database", error=str(e), exc_info=True, date=date)
            self.conn.rollback()