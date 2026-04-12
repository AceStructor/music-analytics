INSERT_SQL = """
WITH inserted_artists AS (
    INSERT INTO artists (name)
    SELECT UNNEST(%(artist_names)s)
    ON CONFLICT (name) DO UPDATE
        SET name = EXCLUDED.name
    RETURNING id, name
),

album AS (
    INSERT INTO albums (title, mbid)
    VALUES (%(album_title)s, %(album_mbid)s)
    ON CONFLICT (mbid) DO UPDATE
        SET title = EXCLUDED.title,
            mbid = EXCLUDED.mbid
    RETURNING id
),

track AS (
    INSERT INTO tracks (
        title,
        duration_ms,
        download_status,
        mbid
    )
    VALUES (
        %(track_title)s,
        %(duration_ms)s,
        'pending',
        %(track_mbid)s
    )
    ON CONFLICT (mbid)
    DO UPDATE SET
        title = EXCLUDED.title,
        duration_ms = EXCLUDED.duration_ms,
        mbid = EXCLUDED.mbid
    RETURNING id
),

artist_track_links AS (
    INSERT INTO artist_tracks (artist_id, track_id)
    SELECT inserted_artists.id, track.id
    FROM inserted_artists, track
    ON CONFLICT DO NOTHING
),

artist_album_links AS (
    INSERT INTO artist_albums (artist_id, album_id)
    SELECT inserted_artists.id, album.id
    FROM inserted_artists, album
    ON CONFLICT DO NOTHING
),

album_track_link AS (
    INSERT INTO album_tracks (album_id, track_id)
    SELECT album.id, track.id
    FROM album, track
    ON CONFLICT DO NOTHING
)
SELECT 1;
"""

DELETE_SQL = """
WITH deleted_tracks AS (
    DELETE FROM tracks t
    WHERE NOT EXISTS (
        SELECT 1
        FROM album_tracks at
        WHERE at.track_id = t.id
    )
    RETURNING id
),

deleted_artists AS (
    DELETE FROM artists a
    WHERE NOT EXISTS (
        SELECT 1
        FROM artist_albums aa
        WHERE aa.artist_id = a.id
    )
    RETURNING id
)

SELECT
    (SELECT COUNT(*) FROM deleted_tracks) AS tracks_removed,
    (SELECT COUNT(*) FROM deleted_artists) AS artists_removed;
"""

AUTO_GENERATE_PLAYLIST = """
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
	SELECT t.id AS track_id, t.title, a.id, a.name,
		ROW_NUMBER() OVER (PARTITION BY a.id ORDER BY COUNT(tp.*) DESC) AS rank
	FROM tracks t
	LEFT JOIN artist_tracks art ON art.track_id = t.id
	LEFT JOIN artists a ON a.id = art.artist_id
	JOIN track_plays tp ON tp.track_id = t.id
	WHERE played_at >= TIMESTAMP %(date)s
		AND played_at < TIMESTAMP %(date)s + interval '1 month'
		AND art.artist_id IN (SELECT artist_id FROM top_artists)
	GROUP BY t.id, t.title, a.id, a.name
), 

top_tracks AS (
	SELECT t.id AS track_id, t.title, COUNT(*) AS play_count
	FROM tracks t
	JOIN track_plays tp ON tp.track_id = t.id
	WHERE played_at >= TIMESTAMP %(date)s
		AND played_at < TIMESTAMP %(date)s + interval '1 month'
	GROUP BY t.id, t.title
	ORDER BY play_count DESC
	LIMIT 30
), 

selected_tracks AS (
	SELECT DISTINCT track_id
	FROM (
		SELECT track_id FROM artist_tracks WHERE rank <= 3
		UNION
		SELECT track_id FROM top_tracks
	) combined
	LIMIT 90
), 

upsert_playlist AS (
    INSERT INTO playlists (name, month, description)
    VALUES (%(name)s, %(date)s, 'Auto-generated')
    ON CONFLICT (month)
    DO UPDATE SET name = EXCLUDED.name
    RETURNING id
), 

playlist_ref AS (
    SELECT id FROM upsert_playlist
    UNION
    SELECT id FROM playlists WHERE month = %(date)s
)

INSERT INTO playlist_tracks (playlist_id, track_id)
SELECT 
    pr.id,
    t.track_id
FROM playlist_ref pr
JOIN (
    SELECT track_id
    FROM selected_tracks
) t ON TRUE
ON CONFLICT (playlist_id, track_id) DO NOTHING;
"""