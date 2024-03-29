#
# Essentia API Service for LMS
#
# Copyright (c) 2020-2021 Craig Drummond <craig.p.drummond@gmail.com>
# GPLv3 license.
#

import logging
import math
import numpy
from scipy.spatial import cKDTree
import os
import sqlite3
import time


GENRE_SEPARATOR = ';'
ESSENTIA_ATTRIBS = ['danceable', 'aggressive', 'electronic', 'acoustic', 'happy', 'party', 'relaxed', 'sad', 'dark', 'tonal', 'voice', 'bpm']
NUM_NEIGHBOURS = 1000
NO_GENRE = "<NoGenre>"
_LOGGER = logging.getLogger(__name__)

album_rem = ['anniversary edition', 'deluxe edition', 'expanded edition', 'extended edition', 'special edition', 'deluxe', 'deluxe version', 'extended deluxe', 'super deluxe', 're-issue', 'remastered', 'mixed', 'remixed and remastered']
artist_rem = ['feat', 'ft', 'featuring']
title_rem = ['demo', 'demo version', 'radio edit', 'remastered', 'session version', 'live', 'live acoustic', 'acoustic', 'industrial remix', 'alternative version', 'alternate version', 'original mix', 'bonus track', 're-recording', 'alternate']


def normalize_str(s):
    if not s:
        return s
    s=s.replace('.', '').replace('(', '').replace(')', '').replace('[', '').replace(']', '').replace(' & ', ' and ')
    while '  ' in s:
        s=s.replace('  ', ' ')
    return s


def normalize_album(album):
    if not album:
        return album
    s = album.lower()
    global album_rem
    for r in album_rem:
        s=s.replace(' (%s)' % r, '').replace(' [%s]' % r, '')
    return normalize_str(s)


def normalize_artist(artist):
    if not artist:
        return artist
    ar = normalize_str(artist.lower())
    global artist_rem
    for r in artist_rem:
        pos = ar.find(' %s ' % r)
        if pos>2:
            return ar[:pos]
    return ar


def normalize_title(title):
    if not title:
        return title
    s = title.lower()
    global title_rem
    for r in title_rem:
        s=s.replace(' (%s)' % r, '').replace(' [%s]' % r, '')
    return normalize_str(s)


def set_normalize_options(opts):
    if 'album' in opts and isinstance(opts['album'], list):
        global album_rem
        album_rem = [e.lower() for e in opts['album']]
    if 'artist' in opts and isinstance(opts['artist'], list):
        global artist_rem
        artist_rem = [e.lower() for e in opts['album']]
    if 'title' in opts and isinstance(opts['title'], list):
        global title_rem
        title_rem = [e.lower() for e in opts['title']]


class TracksDb(object):
    min_bpm = None
    bpm_range = None
    max_sim = math.sqrt(len(ESSENTIA_ATTRIBS)+1) # +1 for genre
    track_list = []
    attrib_list = None
    last_call = None
    genre_map = {}
    genre_differences = {}


    def __init__(self, config):
        tstart = time.time_ns()
        self.conn = sqlite3.connect(config['db'], uri=True)
        self.cursor = self.conn.cursor()

        if TracksDb.min_bpm is None:
            _LOGGER.debug('Loading tracks DB')
            self.cursor.execute('SELECT min(bpm), max(bpm) from tracks')
            row = self.cursor.fetchone()
            TracksDb.min_bpm = row[0]
            TracksDb.bpm_range = row[1] - TracksDb.min_bpm

            cols = 'file, title, artist, album, albumartist, genre, duration, ignore, rowid'
            for ess in ESSENTIA_ATTRIBS:
                cols+=', %s' % ess
            self.cursor.execute('SELECT %s FROM tracks' % cols)

            attrib_list = []
            TracksDb.genre_map[NO_GENRE] = 0
            for row in self.cursor:
                if row[7]==1:
                    # Track marked as ignore, so dont add to lists
                    continue
                track={'file':row[0], 'title':normalize_title(row[1]), 'artist':normalize_artist(row[2]), 'album':normalize_album(row[3]), 'albumartist':normalize_artist(row[4]), 'duration':row[6], 'rowid':row[8]}
                genre = row[5]
                if row[5] and len(row[5])>0:
                    track['genres']=row[5].split(GENRE_SEPARATOR)
                    igenres = []
                    for genre in track['genres']:
                        if genre not in TracksDb.genre_map:
                            igenre = len(TracksDb.genre_map)
                            TracksDb.genre_map[genre] = igenre
                            _LOGGER.debug("%s -> %d" % (genre, igenre))
                        else:
                            igenre = TracksDb.genre_map[genre]
                        igenres.append(igenre)
                    track['igenres'] = igenres
                else:
                    _LOGGER.warning("NO GENRE FOR: %s" % track['file'])
                    track['igenres'] = [0]
                    track['genres'] = [NO_GENRE]

                attribs=[]
                for attr in range(len(ESSENTIA_ATTRIBS)):
                    if 'bpm'==ESSENTIA_ATTRIBS[attr]:
                        attribs.append((row[9+attr]-TracksDb.min_bpm)/TracksDb.bpm_range)
                    else:
                        attribs.append(row[9+attr])
                attribs.append(5) # Place holder for genre difference attribute

                TracksDb.track_list.append(track)
                attrib_list.append(attribs)
            TracksDb.attrib_list = numpy.array(attrib_list)

            # Update config item genres from strings to ints
            if 'genres' in config:
                config_genres = []
                all_genres = []
                for genres in config['genres']:
                    group_genres = []
                    for g in genres:
                        if g in TracksDb.genre_map:
                            val = TracksDb.genre_map[g]
                            group_genres.append(val)
                            if not val in config_genres:
                                all_genres.append(val)
                    if len(group_genres)>0:
                        config_genres.append(group_genres)
                if len(config_genres)>0:
                    config['genres'] = config_genres
                    config['all_genres'] = set(all_genres)
                else:
                    config['genres'] = []
                    config['all_genres'] = set()

            # Create map of genre -> list of differences to other genres
            for genre in range(len(TracksDb.genre_map)):
                in_all = genre in config['all_genres']
                diff_map={}
                genre_group=set()
                if 'genres' in config:
                    for group in config['genres']:
                        if genre in group:
                            genre_group = set(group)

                for ogenre in range(len(TracksDb.genre_map)):
                    if ogenre==genre:
                        diff_map[ogenre]=0.1
                    elif ogenre in genre_group:
                        # ogenre is in same group as genre
                        diff_map[ogenre]=0.2
                    elif not in_all and ogenre not in config['all_genres']:
                        # again, ogenre is in same group as genre - i.e. they are both in the 'ungrouped' genre
                        diff_map[ogenre]=0.2
                    else:
                        diff_map[ogenre]=0.4

                TracksDb.genre_differences[genre]=diff_map

            _LOGGER.debug('Loaded %d tracks in:%dms' % (len(TracksDb.track_list), int((time.time_ns()-tstart)/1000000)))


    def close(self):
        self.cursor.close()
        self.conn.close()


    def get(self, path, is_seed):
        try:
            query = ''
            if is_seed:
                for attr in ESSENTIA_ATTRIBS:
                    query+=', %s' % attr
            self.cursor.execute('SELECT title, artist, album, albumartist, genre, duration, rowid %s FROM tracks WHERE file=?' % query, (path,))
            row = self.cursor.fetchone()
            if row:
                details = {'file':path, 'title':normalize_title(row[0]), 'artist':normalize_artist(row[1]), 'album':normalize_album(row[2]), 'albumartist':normalize_artist(row[3]), 'duration':row[5], 'rowid':row[6]}
                if row[4] and len(row[4])>0:
                    details['genres']=row[4].split(GENRE_SEPARATOR)
                    igenres = []
                    for genre in details['genres']:
                        igenres.append(TracksDb.genre_map[genre])
                    details['igenres'] = igenres
                else:
                    details['igenres'] = [0]
                    details['genres'] = [NO_GENRE]

                if is_seed:
                    # This track will be used to find similar tracks, so we need its essentia attributes
                    attribs=[]
                    for attr in range(len(ESSENTIA_ATTRIBS)):
                        if 'bpm'==ESSENTIA_ATTRIBS[attr]:
                            attribs.append((row[7+attr]-TracksDb.min_bpm)/TracksDb.bpm_range)
                        else:
                            attribs.append(row[7+attr])
                    attribs.append(0) # Place holder for genre difference attribute
                    details['attribs']=attribs
                return details
        except Exception as e:
            _LOGGER.error('Failed to read metadata - %s' % str(e))
            pass
        return None


    def get_similar_tracks(self, seed, match_all_genres=False, num_skip=0, count=NUM_NEIGHBOURS):
        query = ''
        duration = ''
        total = 0
        _LOGGER.debug('Query similar tracks to: %s' % str(seed))
        if count<=0:
            count = len(TracksDb.track_list)

        # Rebuild tree, if required
        if TracksDb.last_call is None or \
            (match_all_genres and not TracksDb.last_call['match_all_genres']) or \
            ( (not match_all_genres) and (TracksDb.last_call['igenre'] != seed['igenres'][0]) ) :

            tstart = time.time_ns()
            genre_attrib = len(ESSENTIA_ATTRIBS)
            genre_diff_map = TracksDb.genre_differences[seed['igenres'][0]]
            for i in range(len(TracksDb.track_list)):
                TracksDb.attrib_list[i][genre_attrib] = 0 if match_all_genres else genre_diff_map[TracksDb.track_list[i]['igenres'][0]]

            _LOGGER.debug('Calc genre diff time:%d' % int((time.time_ns()-tstart)/1000000))

            tstart = time.time_ns()
            TracksDb.last_call={'igenre':seed['igenres'][0], 'match_all_genres':match_all_genres, 'tree':cKDTree(TracksDb.attrib_list)}
            _LOGGER.debug('Build tree time:%d' % int((time.time_ns()-tstart)/1000000))

        tstart = time.time_ns()
        distances, indexes = TracksDb.last_call['tree'].query(numpy.array([seed['attribs']]), k=count+num_skip)
        _LOGGER.debug('Tree time:%d' % int((time.time_ns()-tstart)/1000000))

        tstart = time.time_ns()
        entries = []
        num_tracks = len(TracksDb.track_list)
        for i in range(1, min(len(indexes[0]), num_tracks)): # Seed track is always returned first, so skip
            entry = TracksDb.track_list[indexes[0][i]]
            entry['similarity'] = distances[0][i]/TracksDb.max_sim
            entries.append(entry)

        _LOGGER.debug('Processing time:%d' % int((time.time_ns()-tstart)/1000000))
        return entries;
