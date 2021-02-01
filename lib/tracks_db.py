#
# Analyse files with Essentia
#
# Copyright (c) 2020-2021 Craig Drummond <craig.p.drummond@gmail.com>
# GPLv3 license.
#

import logging
import math
import os
import sqlite3
import time


GENRE_SEPARATOR = ';'
ESSENTIA_ATTRIBS = ['danceable', 'aggressive', 'electronic', 'acoustic', 'happy', 'party', 'relaxed', 'sad', 'dark', 'tonal', 'voice', 'bpm']
MAX_SQL_ROWS = 1500
_LOGGER = logging.getLogger(__name__)
ALBUM_REMOVALS = ['anniversary edition', 'deluxe edition', 'expanded edition', 'extended edition', 'special edition', 'deluxe', 'deluxe version', 'extended deluxe', 'super deluxe', 're-issue', 'remastered', 'mixed', 'remixed and remastered']
TITLE_REMOVALS = ['demo', 'demo version', 'radio edit', 'remastered', 'session version', 'live', 'live acoustic', 'acoustic', 'industrial remix', 'alternative version', 'alternate version', 'original mix', 'bonus track', 're-recording', 'alternate']


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
    for r in ALBUM_REMOVALS:
        s=s.replace(' (%s)' % r, '')
    return normalize_str(s)


def normalize_artist(artist):
    if not artist:
        return artist
    return normalize_str(artist.lower()).replace(' feat ', ' ').replace(' ft ', ' ').replace(' featuring ', ' ')


def normalize_title(title):
    if not title:
        return title
    s = title.lower()
    for r in TITLE_REMOVALS:
        s=s.replace(' (%s)' % r, '')
    return normalize_str(s)


class TracksDb(object):
    def __init__(self, config):
        self.conn = sqlite3.connect('file:%s?immutable=1&nolock=1&mode=ro' % config['db'], uri=True)
        self.cursor = self.conn.cursor()


    def close(self):
        self.cursor.close()
        self.conn.close()


    def get(self, path):
        try:
            query = ''
            for attr in ESSENTIA_ATTRIBS:
                query+=', %s' % attr
            self.cursor.execute('SELECT title, artist, album, albumartist, genre, duration, rowid %s FROM tracks WHERE file=?' % query, (path,))
            row = self.cursor.fetchone()
            if row:
                details = {'file':path, 'title':normalize_title(row[0]), 'artist.orig':row[1], 'artist':normalize_artist(row[1]), 'album':normalize_album(row[2]), 'albumartist':normalize_artist(row[3]), 'duration':row[5], 'rowid':row[6]}
                if row[3] and len(row[3])>0:
                    details['genres']=row[3].split(GENRE_SEPARATOR)
                for attr in range(len(ESSENTIA_ATTRIBS)):
                    details[ESSENTIA_ATTRIBS[attr]] = row[attr+7]
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


    min_bpm = None
    bpm_range = None
    max_sim = math.sqrt(len(ESSENTIA_ATTRIBS)+1)

    def get_similar_tracks(self, seed, seed_genres, all_genres, min_duration=0, max_duration=24*60*60, skip_rows=[], match_all_genres=False, allow_same_artist=False):
        query = ''
        duration = ''
        total = 0
        _LOGGER.debug('Query similar tracks to: %s' % str(seed))

        tstart = time.time_ns()

        if TracksDb.min_bpm is None:
            self.cursor.execute('SELECT min(bpm), max(bpm) from tracks')
            row = self.cursor.fetchone()
            TracksDb.min_bpm = row[0]
            TracksDb.bpm_range = row[1] - TracksDb.min_bpm

        for attr in ESSENTIA_ATTRIBS:
            if 'bpm'==attr:
                query+='( ((bpm-%d.0)/%d.0)*((bpm-%d.0)/%d.0) )' % (TracksDb.min_bpm, TracksDb.bpm_range, TracksDb.min_bpm, TracksDb.bpm_range)
            else:
                query+='((%.20f-%s)*(%.20f-%s))+' % (seed[attr], attr, seed[attr], attr)

        if max_duration>0 and min_duration>0 and max_duration>min_duration:
            duration = 'and (duration between %d AND %d)' % (min_duration, max_duration)
        elif min_duration>0:
            duration = 'and duration >= %d' % min_duration
        elif max_duration>0:
            duration = 'and duration <= %d' % max_duration

        # Get all tracks...
        if allow_same_artist:
            self.cursor.execute('SELECT file, title, artist, album, albumartist, genre, rowid, (%s) as dist FROM tracks where (ignore != 1) %s order by dist limit %d' % (query, duration, MAX_SQL_ROWS))
        else:
            self.cursor.execute('SELECT file, title, artist, album, albumartist, genre, rowid, (%s) as dist FROM tracks where (ignore != 1) %s and (artist != ?) order by dist limit %d' % (query, duration, MAX_SQL_ROWS), (seed['artist.orig'],))
        _LOGGER.debug('Query time:%d' % int((time.time_ns()-tstart)/1000000))
        tstart = time.time_ns()
        entries=[]
        num_std_cols = 6
        for row in self.cursor:
            entry = {'file':row[0], 'title':normalize_title(row[1]), 'artist':normalize_artist(row[2]), 'album':normalize_album(row[3]), 'albumartist':normalize_artist(row[4]), 'rowid':row[6]}
            if entry['rowid'] == seed['rowid'] or (skip_rows is not None and entry['rowid'] in skip_rows):
                continue

            if row[4] and len(row[4])>0:
                entry['genres'] = row[4].split(GENRE_SEPARATOR)

            sim = row[len(row)-1]

            # Adjust similarity using genres
            sim += TracksDb.genre_sim(seed, entry, seed_genres, all_genres, match_all_genres)**2

            entry['similarity'] = math.sqrt(sim)/TracksDb.max_sim
            entries.append(entry)

        # Sort entries by similarity, most similar (lowest number) first
        vals = sorted(entries, key=lambda k: k['similarity'])
        _LOGGER.debug('Processing time:%d' % int((time.time_ns()-tstart)/1000000))
        return vals;
