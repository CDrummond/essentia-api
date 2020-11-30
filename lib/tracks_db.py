#
# Analyse files with Essentia
#
# Copyright (c) 2020 Craig Drummond <craig.p.drummond@gmail.com>
# GPLv3 license.
#

import logging
import os
import sqlite3


GENRE_SEPARATOR = ';'
ESSENTIA_ATTRIBS         = ['danceable', 'aggressive', 'electronic', 'acoustic', 'happy', 'party', 'relaxed', 'sad', 'dark', 'tonal', 'voice', 'bpm']
ESSENTIA_ATTRIBS_WEIGHTS = [1.0,         0.9,          0.25,         0.25,       0.65,     0.8,     0.65,      0.4,   0.4,    0.1,     0.2,     1.0]
MIN_SIMILAR = 100
_LOGGER = logging.getLogger(__name__)

    
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
            self.cursor.execute('SELECT artist, album, albumartist, genre, duration %s FROM tracks WHERE file=?' % query, (path,))
            row = self.cursor.fetchone()
            if row:
                details = {'file':path, 'artist':row[0], 'album':row[1], 'albumartist':row[2], 'duration':row[4]}
                if row[3] and len(row[3])>0:
                    details['genres']=row[3].split(GENRE_SEPARATOR)
                if row[5] is not None and row[5]==1:
                    details['ignore']=True
                for attr in range(len(ESSENTIA_ATTRIBS)):
                    details[ESSENTIA_ATTRIBS[attr]] = row[attr+5]
                return details
        except Exception as e:
            _LOGGER.error('Failed to read metadata - %s' % str(e))
            pass
        return None


    def get_similar_tracks(self, seed, seed_genres, min_duration=0, max_duration=24*60*60):
        query = ''
        where = ''
        duration = ''
        total = 0
        _LOGGER.debug('Query similar tracks to: %s' % str(seed))
        for attr in ESSENTIA_ATTRIBS:
            query+=', %s' % attr
            if 'bpm'==attr:
                where+='and (%s between %d AND %d)' % (attr, seed[attr]-50, seed[attr]+50)
            else:
                where+='and (%s between %f AND %f)' % (attr, seed[attr]-0.3, seed[attr]+0.3)

        if min_duration>0 or max_duration>0:
            if max_duration<=0:
                max_duration = 24*60*60
            duration = 'and (duration between %d AND %d)' % (min_duration, max_duration)
        # Ty to get similar tracks using 'where'
        self.cursor.execute('SELECT file, artist, album, albumartist, genre %s FROM tracks where (ignore != 1) %s and (artist!="%s") %s' % (query, duration, seed['artist'], where))
        rows = self.cursor.fetchall()
        _LOGGER.debug('Close rows: %d' % len(rows))
        if len(rows)<MIN_SIMILAR:
            # Too few (as we might filter), so just get all tracks...
            self.cursor.execute('SELECT file, artist, album, albumartist, genre %s FROM tracks where (ignore != 1) %s and (artist != "%s")' % (query, duration, seed['artist']))
            rows = self.cursor.fetchall()
            _LOGGER.debug('All rows: %d' % len(rows))

        entries=[]
        for row in rows:
            if row[0]==seed['file']:
                continue
            entry = {'file':row[0], 'artist':row[1], 'album':row[2], 'albumartist':row[3]}
            if row[4] and len(row[4])>0:
                entry['genres'] = row[4].split(GENRE_SEPARATOR)

            # Calculate similarity
            sim = 0.0
            for attr in range(len(ESSENTIA_ATTRIBS)):
                factor=1.0
                if 'bpm'==ESSENTIA_ATTRIBS[attr]:
                    factor = 1.0
                elif seed[ESSENTIA_ATTRIBS[attr]]>=0.9 or seed[ESSENTIA_ATTRIBS[attr]]<=0.1:
                    factor = 0.7
                elif seed[ESSENTIA_ATTRIBS[attr]]>=0.8 or seed[ESSENTIA_ATTRIBS[attr]]<=0.2:
                    factor = 0.5
                elif seed[ESSENTIA_ATTRIBS[attr]]>=0.7 or seed[ESSENTIA_ATTRIBS[attr]]<=0.3:
                    factor = 0.3
                elif seed[ESSENTIA_ATTRIBS[attr]]>=0.6 or seed[ESSENTIA_ATTRIBS[attr]]<=0.4:
                    factor = 0.2

                sim += (abs(seed[ESSENTIA_ATTRIBS[attr]]-row[attr+5])/(seed[ESSENTIA_ATTRIBS[attr]]+0.00000001))*factor*ESSENTIA_ATTRIBS_WEIGHTS[attr]

            if seed_genres  is not None and 'genres' in entry and not entry['genres'][0] in seed_genres:
                sim += 20
            entry['similarity']=sim
            entries.append(entry)
        # Sort entries by similarity, highest first
        return sorted(entries, key=lambda k: k['similarity'])
