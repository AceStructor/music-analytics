from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2

from logger import log
from config import DB_CONFIG
from libmanager import MusicBrainzClient
from databasemanager import DatabaseWriter, DatabaseReader
from playlistmanager import SubsonicClient, MagicPlaylister

app = Flask(__name__)
CORS(app)


@app.route("/album", methods=["POST"])
def add_album():
    mbid = request.json.get("mbid")

    if not mbid:
        return {"error": "mbid missing"}, 400

    tracks = MusicBrainzClient().fetch_release(mbid)
    log.info("Fetched album tracks", mbid=mbid, track_count=len(tracks))
    log.debug("Track details", tracks=[t.__dict__ for t in tracks])
    inserted =  app.db_writer.bulk_insert_tracks(tracks)

    return jsonify({
        "mbid": mbid,
        "tracks_fetched": len(tracks),
        "tracks_inserted": inserted
    })

@app.route("/album/delete", methods=["POST"])
def remove_album():
    mbid = request.json.get("mbid")

    if not mbid:
        return {"error": "mbid missing"}, 400

    deleted = app.db_writer.delete_album(mbid)

    return jsonify({
        "mbid": mbid,
        "tracks_deleted": deleted["deleted_tracks"],
        "artists_deleted": deleted["deleted_artists"]
    })

@app.route("/playlist/sync", methods=["POST"])
def sync_playlists():
    mapping = SubsonicClient.build_mbid_mapping()
    app.db_writer.insert_navidrome_ids(mapping)

    playlists = app.db_reader.load_playlists()
    synced = []
    skipped = []

    for playlist in playlists:
        print(f"\nSyncing: {playlist['name']}")

        songs = app.db_reader.load_playlist_tracks(playlist["playlist_id"])

        if not songs:
            print(" -> skip (no tracks)")
            skipped.append(playlist["playlist_id"])
            continue

        song_navidrome_ids = [song["navidrome_id"] for song in songs]

        if playlist["navidrome_id"] is None:
            print(" -> creating playlist")
            new_id = SubsonicClient.create_playlist(playlist["name"], song_navidrome_ids)
            app.db_writer.update_playlist_navidrome_id(playlist["playlist_id"], new_id)
            synced.append({"playlist_id": playlist["playlist_id"], "navidrome_id": new_id, "action": "created"})
        else:
            print(" -> replacing playlist")
            new_id = SubsonicClient.replace_playlist(playlist["navidrome_id"], song_navidrome_ids)
            app.db_writer.update_playlist_navidrome_id(playlist["playlist_id"], new_id)
            synced.append({"playlist_id": playlist["playlist_id"], "navidrome_id": new_id, "action": "replaced"})

        log.debug(f" -> done ({len(song_navidrome_ids)} tracks)")

    return jsonify({
        "status": "success",
        "synced": synced,
        "skipped": skipped
    }), 200

@app.route("/playlist/add", methods=["POST"])
def add_playlist():
    name_overwrite = request.json.get("name")
    month = request.json.get("month")
    year = request.json.get("year")
    auto = request.json.get("auto")
    wildness = request.json.get("wildness")

    if not month or not year:
        return {"error": "json body incomplete, month or year missing"}, 400
    
    name = month + " " + year
    date = "01 " + name
    date_normal = datetime.strptime(date, "%d %B %y")
    date = date_normal.strftime("%Y-%m-%d")

    if name_overwrite:
        name = name_overwrite

    if auto:
        playlist_id = app.db_writer.insert_auto_playlist(name, date)
        return jsonify({"playlist_id": playlist_id, "name": name, "date": date, "auto": True, "status": "created"}), 201

    playlist_id = app.db_writer.create_empty_playlist(name, date)
    if not playlist_id:
        return {"error": "error creating empty playlist"}, 500

    top_artist_tracks = app.db_reader.get_top_artist_tracks(date)
    top_tracks = app.db_reader.get_top_tracks(date)
    top_genre_top_tracks = app.db_reader.get_top_genre_top_tracks(date)
    top_genre_single_listens = app.db_reader.get_top_genre_single_listens(date)
    top_genre_wildcard = app.db_reader.get_top_genre_wildcard(date)
    genre_wildcard = app.db_reader.get_genre_wildcard(date)

    try:
        tracklist = MagicPlaylister.make_playlist(wildness, top_artist_tracks, top_tracks, top_genre_top_tracks, top_genre_single_listens, top_genre_wildcard, genre_wildcard)
    except ValueError as e:
        return {"error": "error creating playlist: " + str(e)}, 500

    inserted_tracks = app.db_writer.insert_tracks_into_playlist(playlist_id, tracklist)

    return jsonify({
        "playlist_id": playlist_id,
        "name": name,
        "date": date,
        "tracks_inserted": inserted_tracks,
        "status": "created"
    }), 201

@app.route("/playlist/add/empty", methods=["POST"])
def add_empty_playlist():
    name_overwrite = request.json.get("name")
    month = request.json.get("month")
    year = request.json.get("year")

    if not month or not year:
        return {"error": "json body inclomplete, month or year missing"}, 400
    
    name = month + " " + year
    date = "01 " + name
    date_normal = datetime.strptime(date, "%d %B %y")
    date = date_normal.strftime("%Y-%m-%d")

    if name_overwrite:
        name = name_overwrite

    playlist_id = app.db_writer.create_empty_playlist(name, date)

    return jsonify({
        "playlist_id": playlist_id
    })

@app.route("/playlist/all", methods=["GET"])
def get_playlists():
    playlists = app.db_reader.load_playlists()

    return jsonify({
        "playlists": playlists
    })

@app.route("/playlist/<playlist_id>", methods=["GET"])
def get_playlist(playlist_id):
    playlist = app.db_reader.search_playlist(playlist_id)

    return jsonify({
        "playlist": playlist
    })

@app.route("/playlist/<playlist_id>", methods=["DELETE"])
def delete_playlist(playlist_id):
    playlist = app.db_reader.search_playlist(playlist_id)

    if playlist["navidrome_id"]:
        SubsonicClient.delete_playlist(playlist["navidrome_id"])

    deleted = app.db_writer.delete_playlist(playlist_id)
    return jsonify({"playlist_id": playlist_id, "deleted": bool(deleted), "status": "deleted"}), 200

@app.route("/playlist/<playlist_id>", methods=["UPDATE"])
def update_playlist(playlist_id):
    name = request.json.get("name")

    app.db_writer.update_playlist_name(playlist_id, name)

    playlist = app.db_reader.search_playlist(playlist_id)

    return jsonify({
        "playlist": playlist
    })

@app.route("/playlist/tracks/<playlist_id>", methods=["GET"])
def get_playlist_tracks(playlist_id):
    tracks = app.db_reader.load_playlist_tracks(playlist_id)

    return jsonify({
        "playlist": playlist_id,
        "tracks": tracks
    })

@app.route("/playlist/tracks/<playlist_id>/<track_id>", methods=["DELETE"])
def delete_track_from_playlist(playlist_id, track_id):
    deleted = app.db_writer.delete_track_from_playlist(playlist_id, track_id)
    return jsonify({"playlist_id": playlist_id, "track_id": track_id, "deleted": bool(deleted), "status": "deleted"}), 200

@app.route("/playlist/tracks/<playlist_id>/add", methods=["POST"])
def add_tracks_to_playlist(playlist_id):
    tracks = request.json.get("tracks")

    if not tracks:
        return {"error": "track list is empty"}, 400 
    
    app.db_writer.insert_tracks_into_playlist(playlist_id, tracks)

    new_tracks = app.db_reader.load_playlist_tracks(playlist_id)

    return jsonify({
        "playlist": playlist_id,
        "tracks": new_tracks
    })

#@app.route("/artists/all", methods=["GET"])
#@app.route("/albums/<artist_id>/all", methods=["GET"])
#@app.route("/tracks/<album_id>/all", methods=["GET"])

def create_app():
    try:
        conn = psycopg2.connect(**DB_CONFIG) 
    except psycopg2.OperationalError as e:
        log.warning("Database connection error, will retry", error=str(e), exc_info=True)

    app.db_writer = DatabaseWriter(conn)
    app.db_reader = DatabaseReader(conn)

    return app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
