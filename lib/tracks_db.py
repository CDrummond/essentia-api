#
# Analyse files with Essentia
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
    tree = None


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

            attrib_list=[]
            for row in self.cursor:
                if row[7]==1:
                    # Track marked as ignore, so dont add to lists
                    continue
                track={'file':row[0], 'title':normalize_title(row[1]), 'artist':normalize_artist(row[2]), 'album':normalize_album(row[3]), 'albumartist':normalize_artist(row[4]), 'duration':row[6], 'rowid':row[8]}
                genre = row[5]
                if row[5] and len(row[5])>0:
                    track['genres']=row[5].split(GENRE_SEPARATOR)

                attribs=[]
                for attr in range(len(ESSENTIA_ATTRIBS)):
                    if 'bpm'==ESSENTIA_ATTRIBS[attr]:
                        attribs.append((row[9+attr]-TracksDb.min_bpm)/TracksDb.bpm_range)
                    else:
                        attribs.append(row[9+attr])

                TracksDb.track_list.append(track)
                attrib_list.append(attribs)
            TracksDb.tree = cKDTree(numpy.array(attrib_list))
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
                if is_seed:
                    attribs=[]
                    for attr in range(len(ESSENTIA_ATTRIBS)):
                        if 'bpm'==ESSENTIA_ATTRIBS[attr]:
                            attribs.append((row[7+attr]-TracksDb.min_bpm)/TracksDb.bpm_range)
                        else:
                            attribs.append(row[7+attr])
                    details['attribs']=attribs
                return details
        except Exception as e:
            _LOGGER.error('Failed to read metadata - %s' % str(e))
            pass
        return None


    @staticmethod
    def genre_sim(seed, entry, seed_genres, all_genres, match_all_genres=False):
        if match_all_genres:
            return 0.1
        if 'genres' not in seed:
            return 0.5
        if 'genres' not in entry:
            return 0.5
        if seed['genres'][0]==entry['genres'][0]:
            return 0.1
        if (seed_genres is not None and entry['genres'][0] not in seed_genres) or \
           (seed_genres is None and all_genres is not None and entry['genres'][0] in all_genres):
            return 0.7
        return 0.2


    def get_similar_tracks(self, seed, seed_genres, all_genres, min_duration=0, max_duration=24*60*60, skip_rows=[], match_all_genres=False):
        query = ''
        duration = ''
        total = 0
        _LOGGER.debug('Query similar tracks to: %s' % str(seed))

        tstart = time.time_ns()
        num_skip = len(skip_rows) if None!=skip_rows and len(skip_rows)>0 else 1
        distances, indexes = TracksDb.tree.query(numpy.array([seed['attribs']]), k=NUM_NEIGHBOURS+num_skip)
        _LOGGER.debug('Tree time:%d' % int((time.time_ns()-tstart)/1000000))

        tstart = time.time_ns()
        entries = []
        num_tracks = len(TracksDb.track_list)
        for i in range(1, len(indexes[0])): # Seed track is always returned first, so skip
            if i>=num_tracks:
                continue
            entry = TracksDb.track_list[indexes[0][i]]
            if entry['rowid'] == seed['rowid'] or (skip_rows is not None and entry['rowid'] in skip_rows):
                continue
            if (min_duration>0 and entry['duration']<min_duration) or (max_duration>0 and entry['duration']>max_duration):
                continue

            # KDTree returns the euclidean distance between entries. This is:
            #
            #   distance = sqrt( sqr( seed[danceable]-track[danceable] ) + ... + sqr( seed[bpm]-track[bpm] ) )
            #
            # ...but also want (if match_all_genres=False) to add genre to this metric. To do this we need to square
            # the euclidean distance, add to this the square of genre diff, and then take the square root. e.g.
            #
            #   distance = sqrt( sqr( seed[danceable]-track[danceable] ) + ... + sqr( seed[bpm]-track[bpm] ) + sqr ( genre_difference ) )
            #
            #
            # ...also, want the similarity to be in the range 0..1, so use the percentage diff of the maximum possible


            # Undo the square-root part of euclidean distance
            sim = distances[0][i]**2

            # Add in the square of the 'genre difference'
            sim += TracksDb.genre_sim(seed, entry, seed_genres, all_genres, match_all_genres)**2

            # Now convert back to euclidean (by taking the square root), and then work out the % this is of
            # maximum similarity score
            entry['similarity'] = math.sqrt(sim)/TracksDb.max_sim

            entries.append(entry)

        # Sort entries by similarity, most similar (lowest number) first
        entries = sorted(entries, key=lambda k: k['similarity'])
        _LOGGER.debug('Processing time:%d' % int((time.time_ns()-tstart)/1000000))
        return entries;
