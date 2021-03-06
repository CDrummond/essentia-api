#
# Essentia API Service for LMS
#
# Copyright (c) 2020-2021 Craig Drummond <craig.p.drummond@gmail.com>
# GPLv3 license.
#

import argparse
from datetime import datetime
import json
import logging
import os
import random
import sqlite3
import time
import urllib
from flask import Flask, abort, request
from . import cue, filters, tracks_db


_LOGGER = logging.getLogger(__name__)

DEFAULT_TRACKS_TO_RETURN              = 5    # Number of tracks to return, if none specified
MIN_TRACKS_TO_RETURN                  = 5    # Min value for 'count' parameter
MAX_TRACKS_TO_RETURN                  = 50   # Max value for 'count' parameter
DEFAULT_NUM_PREV_TRACKS_FILTER_ARTIST = 15   # Try to ensure artist is not in previous N tracks
DEFAULT_NUM_PREV_TRACKS_FILTER_ALBUM  = 25   # Try to ensure album is not in previous N tracks
SHUFFLE_FACTOR                        = 3    # How many (shuffle_factor*count) tracks to shuffle?
VERBOSE_DEBUG                         = True


class EssentiaApp(Flask):
    def init(self, args, app_config):
        _LOGGER.debug('Start server')
        self.app_config = app_config

        flask_logging = logging.getLogger('werkzeug')
        flask_logging.setLevel(args.log_level)
        flask_logging.disabled = 'DEBUG'!=args.log_level
        # Load tracks DB into memory
        tracks_db.TracksDb(app_config)

        random.seed()

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
    if VERBOSE_DEBUG:
        _LOGGER.debug('%s %s' % (reason, str(track)))


@essentia_app.route('/api/dump', methods=['GET', 'POST'])
def dump_api():
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

    if len(params['track'])!=1:
        abort(400)

    cfg = essentia_app.get_config()
    db = tracks_db.TracksDb(cfg)

    # Strip LMS root path from track path
    root = cfg['lms']

    track = decode(params['track'][0], root)
    entry = db.get(track, True)
    if entry is None:
        abort(404)

    fmt = get_value(params, 'format', '', isPost)
    match_artist = int(get_value(params, 'filterartist', '0', isPost))==1

    tracks = db.get_similar_tracks(entry,  match_all_genres=1==int(get_value(params, 'matchallgenres', '0', isPost)), count=-1)
    count = int(get_value(params, 'count', 1000, isPost))

    if not fmt.startswith('text'):
        return json.dumps(tracks[:count])

    resp=[]
    _LOGGER.debug('Num tracks %d' % len(tracks))
    if fmt=='text-url':
        tracks.insert(0, entry)
        for track in tracks:
            if match_artist and entry['artist']!=track['artist']:
                continue
            path = '%s%s' % (root, track['file'])
            resp.append(cue.convert_to_cue_url(path))
            if len(resp)>=count:
                break
    else:
        header = "file\tsimilarity\tgenres"

        if fmt=='textall':
            for attr in tracks_db.ESSENTIA_ATTRIBS:
                header+="\t%s" % attr
        resp.append(header)
        for track in tracks:
            if match_artist and entry['artist']!=track['artist']:
                continue
            if 'genres' in track:
                line="%s\t%f\t%s" % (track['file'], track['similarity'], track['genres'])
            else:
                line="%s\t%f\tXXXXX" % (track['file'], track['similarity'])
            if fmt=='textall':
                for attr in tracks_db.ESSENTIA_ATTRIBS:
                    line+="\t%f" % track[attr]
            resp.append(line)
            if len(resp)>=count:
                break

    return '\n'.join(resp)


@essentia_app.route('/api/similar', methods=['GET', 'POST'])
def similar_api():
    tstart = time.time_ns()
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

    match_genre = int(get_value(params, 'filtergenre', '0', isPost))==1
    shuffle = int(get_value(params, 'shuffle', '1', isPost))==1
    min_duration = int(get_value(params, 'min', 0, isPost))
    max_duration = int(get_value(params, 'max', 0, isPost))
    no_repeat_artist = int(get_value(params, 'norepart', 0, isPost))
    no_repeat_album = int(get_value(params, 'norepalb', 0, isPost))
    exclude_christmas = int(get_value(params, 'filterxmas', '0', isPost))==1 and datetime.now().month!=12

    if no_repeat_artist<0 or no_repeat_artist>200:
        no_repeat_artist = DEFAULT_NUM_PREV_TRACKS_FILTER_ARTIST
    if no_repeat_album<0 or no_repeat_album>200:
        no_repeat_album = DEFAULT_NUM_PREV_TRACKS_FILTER_ALBUM

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
    current_titles=[]

    # Set of rows from seeds/previous, and already checked items
    skip_rows=set()

    if min_duration>0 or max_duration>0:
        _LOGGER.debug('Duration:%d .. %d' % (min_duration, max_duration))

    seed_track_db_entries=[]
    seed_genres=set()
    for trk in params['track']:
        track = decode(trk, root)
        _LOGGER.debug('S TRACK %s -> %s' % (trk, track))

        # Check that we know about this track
        entry = db.get(track, True)
        if entry is not None:
            seed_track_db_entries.append(entry)
            skip_rows.add(entry['rowid'])
            if 'igenres' in entry and 'genres' in cfg:
                for genre in entry['igenres']:
                    for group in cfg['genres']:
                        if genre in group:
                            for cg in group:
                                if not cg in seed_genres:
                                    seed_genres.add(cg)
            if 'title' in entry:
                current_titles.append(entry['title'])
        else:
            _LOGGER.debug('Could not locate %s in DB' % track)

    previous_track_db_entries = []
    if 'previous' in params:
        for trk in params['previous']:
            track = decode(trk, root)
            _LOGGER.debug('P TRACK %s -> %s' % (trk, track))

            entry = db.get(track, False)
            if entry is not None:
                previous_track_db_entries.append(entry)
                if entry['rowid'] not in skip_rows:
                    skip_rows.add(entry['rowid'])
                if 'title' in entry:
                    current_titles.append(entry['title'])
        _LOGGER.debug('Have %d previous tracks to ignore' % len(previous_track_db_entries))

    if match_genre:
        _LOGGER.debug('Seed genres: %s' % seed_genres)

    similarity_count = int(count * SHUFFLE_FACTOR) if shuffle else count

    _LOGGER.debug('Setup time:%d' % int((time.time_ns()-tstart)/1000000))

    matched_artists={}
    for seed in seed_track_db_entries:
        accepted_tracks = 0
        match_all_genres = ('ignoregenre' in cfg) and ('*'==cfg['ignoregenre'][0] or (seed['artist'] in cfg['ignoregenre']))

        # Query DB for similar tracks
        resp = db.get_similar_tracks(seed, match_all_genres, len(skip_rows))

        for track in resp:

            if track['rowid'] in skip_rows or (min_duration>0 and track['duration']<min_duration) or (max_duration>0 and track['duration']>max_duration):
                continue

            if match_genre and not match_all_genres and not filters.genre_matches(cfg, seed_genres, track):
                log_track('DISCARD(genre)', track)
            elif exclude_christmas and filters.is_christmas(track):
                log_track('DISCARD(xmas)', track)
            else:
                if filters.same_artist_or_album(seed_track_db_entries, track):
                    log_track('FILTERED(seeds)', track)
                    filtered_by_seeds_tracks.append(track)
                elif filters.same_artist_or_album(similar_tracks, track):
                    log_track('FILTERED(current)', track)
                    filtered_by_current_tracks.append(track)
                    if track['artist'] in matched_artists and track['similarity'] - matched_artists[track['artist']]['similarity'] <= 0.25:
                        matched_artists[track['artist']]['tracks'].append(track)
                elif no_repeat_artist>0 and filters.same_artist_or_album(previous_track_db_entries, track, False, no_repeat_artist):
                    log_track('FILTERED(previous(artist))', track)
                    filtered_by_previous_tracks.append(track)
                elif no_repeat_album>0 and filters.same_artist_or_album(previous_track_db_entries, track, True, no_repeat_album):
                    log_track('FILTERED(previous(album))', track)
                    filtered_by_previous_tracks.append(track)
                elif filters.match_title(current_titles, track):
                    log_track('FILTERED(title)', track)
                    filtered_by_previous_tracks.append(track)
                else:
                    log_track('USABLE', track)
                    similar_tracks.append(track)
                    # Keep list of all tracks of an artist, so that we can randomly select one => we don't always use the same one
                    matched_artists[track['artist']]={'similarity':track['similarity'], 'tracks':[track], 'pos':len(similar_tracks)-1}
                    if 'title' in track:
                        current_titles.append(track['title'])
                    skip_rows.add(track['rowid'])
                    accepted_tracks += 1
                    if accepted_tracks >= similarity_count:
                        break


    # For each matched_artists randonly select a track...
    for matched in matched_artists:
        if len(matched_artists[matched]['tracks'])>1:
            if VERBOSE_DEBUG:
                _LOGGER.debug('Choosing random track for %s (%d tracks)' % (matched, len(matched_artists[matched]['tracks'])))
            sim = similar_tracks[matched_artists[matched]['pos']]['similarity']
            similar_tracks[matched_artists[matched]['pos']] = random.choice(matched_artists[matched]['tracks'])
            similar_tracks[matched_artists[matched]['pos']]['similarity'] = sim

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
        if VERBOSE_DEBUG:
            _LOGGER.debug('Path:%s %f' % (path, track['similarity']))

    db.close()
    _LOGGER.debug('Total time:%d' % int((time.time_ns()-tstart)/1000000))
    if get_value(params, 'format', '', isPost)=='text':
        return '\n'.join(track_list)
    else:
        return json.dumps(track_list)


def start_app(args, config):
    essentia_app.init(args, config)
    _LOGGER.debug('Ready to process requests')
    essentia_app.run(host=config['host'], port=config['port'])
