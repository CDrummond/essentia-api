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
DEFAULT_MAX_DURATION = 24*60*60 # 24hrs -> almost no max?
MAX_SKIP_ROWS = 200
_LOGGER = logging.getLogger(__name__)


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
    return normalize_str(album.lower().replace(' (anniversary edition)', '') \
                                      .replace(' (deluxe edition)', '') \
                                      .replace(' (expanded edition)', '') \
                                      .replace(' (extended edition)', '') \
                                      .replace(' (special edition)', '') \
                                      .replace(' (deluxe)', '') \
                                      .replace(' (deluxe version)', '') \
                                      .replace(' (extended deluxe)', '') \
                                      .replace(' (super deluxe)', '') \
                                      .replace(' (re-issue)', '') \
                                      .replace(' (remastered)', '') \
                                      .replace(' (remixed)', '') \
                                      .replace(' (remixed and remastered)', ''))


def normalize_artist(artist):
    if not artist:
        return artist
    return normalize_str(artist.lower()).replace(' feat ', ' ').replace(' ft ', ' ').replace(' featuring ', ' ')

    
class TracksDb(object):
    def __init__(self, config):
        self.conn = sqlite3.connect(config['db'])
        self.cursor = self.conn.cursor()


    def close(self):
        self.cursor.close()
        self.conn.close()

                
    def get(self, path):
        try:
            query = ''
            for attr in ESSENTIA_ATTRIBS:
                query+=', %s' % attr
            self.cursor.execute('SELECT artist, album, albumartist, genre, duration, rowid %s FROM tracks WHERE file=?' % query, (path,))
            row = self.cursor.fetchone()
            if row:
                details = {'file':path, 'artist.orig':row[0], 'artist':normalize_artist(row[0]), 'album':normalize_album(row[1]), 'albumartist':normalize_artist(row[2]), 'duration':row[4], 'rowid':row[5]}
                if row[3] and len(row[3])>0:
                    details['genres']=row[3].split(GENRE_SEPARATOR)
                for attr in range(len(ESSENTIA_ATTRIBS)):
                    details[ESSENTIA_ATTRIBS[attr]] = row[attr+6]
                return details
        except Exception as e:
            _LOGGER.error('Failed to read metadata - %s' % str(e))
            pass
        return None


    @staticmethod
    def genre_sim(seed, entry, seed_genres, all_genres, match_all_genres=False):
        if match_all_genres:
            return 1.0
        if 'genres' not in seed:
            return 0.7
        if 'genres' not in entry:
            return 0.7
        if seed['genres'][0]==entry['genres'][0]:
            return 0.1
        if (seed_genres is not None and entry['genres'][0] not in seed_genres) or \
           (seed_genres is None and all_genres is not None and entry['genres'][0] in all_genres):
            return 0.9
        return 0.3


    def get_similar_tracks(self, seed, seed_genres, all_genres, min_duration=0, max_duration=24*60*60, skip_rows=[], match_all_genres=False, allow_same_artist=False):
        query = ''
        duration = ''
        skip = ''
        total = 0
        _LOGGER.debug('Query similar tracks to: %s' % str(seed))

        tstart = time.time_ns()

        if skip_rows is not None and len(skip_rows)>0:
            if 1==len(skip_rows):
                skip='and rowid!=%d' % skip_rows[0]
            else:
                skip_rows = skip_rows[:MAX_SKIP_ROWS]
                skip='and rowid not in ('
                for row in sorted(skip_rows):
                    skip+='%d,' % row
                skip=skip[:-1]+')'

        self.cursor.execute('SELECT min(bpm), max(bpm) from tracks')
        row = self.cursor.fetchone()
        min_bpm = row[0]
        max_bpm = row[1]

        for attr in ESSENTIA_ATTRIBS:
            if 'bpm'==attr:
                query+='( ((bpm-%d.0)/%d.0)*((bpm-%d.0)/%d.0) )' % (min_bpm, max_bpm-min_bpm, min_bpm, max_bpm-min_bpm)
            else:
                query+='((%.20f-%s)*(%.20f-%s))+' % (seed[attr], attr, seed[attr], attr)

        if min_duration>0 or max_duration>0:
            if max_duration<=0:
                max_duration = DEFAULT_MAX_DURATION
            duration = 'and (duration between %d AND %d)' % (min_duration, max_duration)

        # Get all tracks...
        if allow_same_artist:
            self.cursor.execute('SELECT file, artist, album, albumartist, genre, rowid, (%s) as dist FROM tracks where (ignore != 1) and (file != ?) %s %s order by dist limit 2500' % (query, skip, duration), (seed['file'],))
        else:
            self.cursor.execute('SELECT file, artist, album, albumartist, genre, rowid, (%s) as dist FROM tracks where (ignore != 1) and (file != ?) %s %s and (artist != ?) order by dist limit 2500' % (query, skip, duration), (seed['file'], seed['artist.orig'],))
        rows = self.cursor.fetchall()
        _LOGGER.debug('Returned rows:%d' % len(rows))
        _LOGGER.debug('Query time:%d' % int((time.time_ns()-tstart)/1000000))
        entries=[]
        num_std_cols = 6
        for row in rows:
            entry = {'file':row[0], 'artist':normalize_artist(row[1]), 'album':normalize_album(row[2]), 'albumartist':normalize_artist(row[3]), 'rowid':row[5]}
            if row[4] and len(row[4])>0:
                entry['genres'] = row[4].split(GENRE_SEPARATOR)

            sim = row[len(row)-1]

            # Adjust similarity using genres
            sim += (TracksDb.genre_sim(seed, entry, seed_genres, all_genres, match_all_genres))**2

            entry['similarity'] = math.sqrt(sim)
            entries.append(entry)

        # Sort entries by similarity, most similar (lowest number) first
        vals = sorted(entries, key=lambda k: k['similarity'])
        _LOGGER.debug('Total time:%d' % int((time.time_ns()-tstart)/1000000))
        return vals;
