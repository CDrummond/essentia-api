#
# Essentia API Service for LMS
#
# Copyright (c) 2020 Craig Drummond <craig.p.drummond@gmail.com>
# GPLv3 license.
#

import argparse
from datetime import datetime
import json
import logging
import os
import random
import sqlite3
import urllib
from flask import Flask, abort, request
from . import cue, filters, tracks_db

_LOGGER = logging.getLogger(__name__)

DEFAULT_TRACKS_TO_RETURN      = 5  # Number of tracks to return, if none specified
MIN_TRACKS_TO_RETURN          = 5  # Min value for 'count' parameter
MAX_TRACKS_TO_RETURN          = 50 # Max value for 'count' parameter
NUM_PREV_TRACKS_FILTER_ARTIST = 15 # Try to ensure artist is not in previous N tracks
NUM_PREV_TRACKS_FILTER_ALBUM  = 25 # Try to ensure album is not in previous N tracks
SHUFFLE_FACTOR                = 2  # How many tracks to shuffle?

class EssentiaApp(Flask):
    def init(self, args, app_config):
        _LOGGER.debug('Start server')
        self.app_config = app_config
        
        flask_logging = logging.getLogger('werkzeug')
        flask_logging.setLevel(args.log_level)
        flask_logging.disabled = 'DEBUG'!=args.log_level

    def get_config(self):
        return self.app_config
    
essentia_app = EssentiaApp(__name__)


def get_value(params, key, defVal, isPost):
    if isPost:
        return params[key] if key in params else defVal
    return params[key][0] if key in params else defVal


def decode(url, root):
    u = urllib.parse.unquote(url)
    if u.startswith('file://'):
        u=u[7:]
    elif u.startswith('tmp://'):
        u=u[6:]
    if u.startswith(root):
        u=u[len(root):]
    return cue.convert_from_cue_path(u)


def log_track(reason, track):
    _LOGGER.debug('%s Path:%s Similarity:%f Artist:%s Album:%s Genres:%s' % (reason, track['file'], track['similarity'], track['artist'], track['album'], str(track['genres'])))


@essentia_app.route('/api/similar', methods=['GET', 'POST'])
def similar_api():
    isPost = False
    if request.method=='GET':
        params = request.args.to_dict(flat=False)
    else:
        isPost = True
        params = request.get_json()
        _LOGGER.debug('Request: %s' % json.dumps(params))

    if not params:
        abort(400)

    if not 'track' in params:
        abort(400)

    count = int(get_value(params, 'count', DEFAULT_TRACKS_TO_RETURN, isPost))
    if count < MIN_TRACKS_TO_RETURN:
        count = MIN_TRACKS_TO_RETURN
    elif count > MAX_TRACKS_TO_RETURN:
        count = MAX_TRACKS_TO_RETURN

    match_genre = get_value(params, 'filtergenre', '0', isPost)=='1'
    shuffle = get_value(params, 'shuffle', '1', isPost)=='1'
    max_similarity = int(get_value(params, 'maxsim', 75, isPost))/100.0
    min_duration = int(get_value(params, 'min', 0, isPost))
    max_duration = int(get_value(params, 'max', 0, isPost))
    exclude_christmas = get_value(params, 'filterxmas', '0', isPost)=='1' and datetime.now().month!=12

    cfg = essentia_app.get_config()
    db = tracks_db.TracksDb(cfg)

    # Strip LMS root path from track path
    root = cfg['lms']
    
    # Similar tracks
    similar_tracks=[]
    # Similar tracks ignored because of artist/album
    filtered_by_seeds_tracks=[]
    filtered_by_current_tracks=[]
    filtered_by_previous_tracks=[]

    if min_duration>0 or max_duration>0:
        _LOGGER.debug('Duration:%d .. %d' % (min_duration, max_duration))

    seed_track_db_entries=[]
    seed_files=[]
    seed_genres=[]
    all_genres = cfg['all_genres'] if 'all_genres' in cfg else None
    for trk in params['track']:
        track = decode(trk, root)
        _LOGGER.debug('S TRACK %s -> %s' % (trk, track))

        # Check that we know about this track
        entry = db.get(track)
        if entry is not None:
            seed_track_db_entries.append(entry)
            seed_files.append(track)
            if 'genres' in entry and 'genres' in cfg:
                for genre in entry['genres']:
                    for group in cfg['genres']:
                        if genre in group:
                            for cg in group:
                                if not cg in seed_genres:
                                    seed_genres.append(cg)
        else:
            _LOGGER.debug('Could not locate %s in DB' % track)

    previous_files = []
    previous_track_db_entries = []
    if 'previous' in params:
        for trk in params['previous']:
            track = decode(trk, root)
            _LOGGER.debug('P TRACK %s -> %s' % (trk, track))

            entry = db.get(track)
            if entry is not None:
                previous_files.append(track)
                previous_track_db_entries.append(entry)
        _LOGGER.debug('Have %d previous tracks to ignore' % len(previous_files))

    exclude_artists = []
    do_exclude_artists = False
    exclude_key = 'excludeartist' if 'excludeartist' in params else 'exclude'
    if exclude_key in params:
        for artist in params[exclude_key]:
            exclude_artists.append(artist.strip())
        do_exclude_artists = len(exclude_artists)>0
        _LOGGER.debug('Have %d artists to exclude %s' % (len(exclude_artists), exclude_artists))

    exclude_albums = []
    do_exclude_albums = False
    if 'excludealbum' in params:
        for album in params['excludealbum']:
            exclude_albums.append(album.strip())
        do_exclude_albums = len(exclude_albums)>0
        _LOGGER.debug('Have %d albums to exclude %s' % (len(exclude_albums), exclude_albums))

    if match_genre:
        _LOGGER.debug('Seed genres: %s' % seed_genres)

    checked_files=[]
    similarity_count = int(count * SHUFFLE_FACTOR) if shuffle else count
    for seed in seed_track_db_entries:
        # Query DB for similar tracks
        resp = db.get_similar_tracks(seed, seed_genres, all_genres, min_duration, max_duration)
        accepted_tracks = 0
        for track in resp:
            if (not track['file'] in seed_files) and (not track['file'] in previous_files) and (not track['file'] in checked_files):
                checked_files.append(track['file'])

                if match_genre and not filters.genre_matches(cfg, seed_genres, track):
                    log_track('DISCARD(genre)', track)
                elif exclude_christmas and filters.is_christmas(track):
                    log_track('DISCARD(xmas)', track)
                elif do_exclude_artists and filters.match_artist(exclude_artists, track):
                    log_track('DISCARD(artist)', track)
                elif do_exclude_albums and filters.match_album(exclude_albums, track):
                    log_track('DISCARD(album)', track)
                else:
                    if filters.same_artist_or_album(seed_track_db_entries, track):
                        log_track('FILTERED(seeds)', track)
                        filtered_by_seeds_tracks.append(track)
                    elif filters.same_artist_or_album(similar_tracks, track):
                        log_track('FILTERED(current)', track)
                        filtered_by_current_tracks.append(track)
                    elif filters.same_artist_or_album(previous_track_db_entries, track, False, NUM_PREV_TRACKS_FILTER_ARTIST):
                        log_track('FILTERED(previous(artist))', track)
                        filtered_by_previous_tracks.append(track)
                    elif filters.same_artist_or_album(previous_track_db_entries, track, True, NUM_PREV_TRACKS_FILTER_ALBUM):
                        log_track('FILTERED(previous(album))', track)
                        filtered_by_previous_tracks.append(track)
                    else:
                        log_track('USABLE', track)
                        similar_tracks.append(track)
                        accepted_tracks += 1
                        if accepted_tracks>=similarity_count:
                            break

    # Too few tracks? Add some from the filtered lists
    min_count = 2
    if len(similar_tracks)<min_count and len(filtered_by_previous_tracks)>0:
        _LOGGER.debug('Add some tracks from filtered_by_previous_tracks, %d/%d' % (len(similar_tracks), len(filtered_by_previous_tracks)))
        filtered_by_previous_tracks = sorted(filtered_by_previous_tracks, key=lambda k: k['similarity'])
        similar_tracks = similar_tracks + filtered_by_previous_tracks[:min_count-len(similar_tracks)]
    if len(similar_tracks)<min_count and len(filtered_by_current_tracks)>0:
        _LOGGER.debug('Add some tracks from filtered_by_current_tracks, %d/%d' % (len(similar_tracks), len(filtered_by_current_tracks)))
        filtered_by_current_tracks = sorted(filtered_by_current_tracks, key=lambda k: k['similarity'])
        similar_tracks = similar_tracks + filtered_by_current_tracks[:min_count-len(similar_tracks)]
    if len(similar_tracks)<min_count and len(filtered_by_seeds_tracks)>0:
        _LOGGER.debug('Add some tracks from filtered_by_seeds_tracks, %d/%d' % (len(similar_tracks), len(filtered_by_seeds_tracks)))
        filtered_by_seeds_tracks = sorted(filtered_by_seeds_tracks, key=lambda k: k['similarity'])
        similar_tracks = similar_tracks + filtered_by_seeds_tracks[:min_count-len(similar_tracks)]

    # Sort by similarity
    similar_tracks = sorted(similar_tracks, key=lambda k: k['similarity'])
    
    # Take top 'similarity_count' tracks
    similar_tracks = similar_tracks[:similarity_count]

    if shuffle:
        random.shuffle(similar_tracks)
        similar_tracks = similar_tracks[:count]

    track_list = []
    for track in similar_tracks:
        path = '%s%s' % (root, track['file'])
        track_list.append(cue.convert_to_cue_url(path))
        _LOGGER.debug('Path:%s %f' % (path, track['similarity']))

    db.close()
    if get_value(params, 'format', '', isPost)=='text':
        return '\n'.join(track_list)
    else:
        return json.dumps(track_list)


def start_app(args, config):
    essentia_app.init(args, config)
    _LOGGER.debug('Ready to process requests')
    essentia_app.run(host=config['host'], port=config['port'])
