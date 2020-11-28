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
ESSENTIA_ATTRIBS = ['danceable', 'aggressive', 'electronic', 'acoustic', 'happy', 'party', 'relaxed', 'sad', 'dark', 'tonal', 'voice', 'bpm']
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


    def get_similar_tracks(self, seed, min_duration=0, max_duration=24*60*60):
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
                if seed[attr]>0.5:
                    where+='and (%s between 0.5 AND 1.0)' % attr
                else:
                    where+='and (%s between 0 AND 0.5)' % attr
        if min_duration>0 or max_duration>0:
            duration = 'and (duration between %d AND %d)' % (min_duration, max_duration)
        # Ty to get similar tracks using 'where'
        self.cursor.execute('SELECT file, artist, album, albumartist, genre %s FROM tracks where (ignore != 1) and (artist!="%s") %s %s' % (query, seed['artist'], where, duration))
        rows = self.cursor.fetchall()
        _LOGGER.debug('Num rows: %d' % len(rows))
        if len(rows)<MIN_SIMILAR:
            # Too few (as we might filter), so just get all tracks...
            self.cursor.execute('SELECT file, artist, album, albumartist, genre %s FROM tracks where (ignore != 1) %s' % (query, duration))
            rows = self.cursor.fetchall()
            _LOGGER.debug('ALL rows: %d' % len(rows))

        entries=[]
        for row in rows:
            if row[0]==seed['file']:
                continue
            entry = {'file':row[0], 'artist':row[1], 'album':row[2], 'albumartist':row[3]}
            if row[4] and len(row[4])>0:
                entry['genres'] = row[4].split(GENRE_SEPARATOR)

            # Calculate similarity
            sim = 0.0
            #for attr in range(len(ESSENTIA_ATTRIBS)-1):
            #    if seed[ESSENTIA_ATTRIBS[attr]]>0.5:
            #        sim += abs((seed[ESSENTIA_ATTRIBS[attr]]-500)-(row[attr+5]-500))/(seed[ESSENTIA_ATTRIBS[attr]]-500)
            #    else:
            #        sim += abs((500-seed[ESSENTIA_ATTRIBS[attr]])-(500-row[attr+5]))/(500-seed[ESSENTIA_ATTRIBS[attr]])
            #sim+=abs(seed['bpm']-row[len(ESSENTIA_ATTRIBS)+4])/seed['bpm']
            for attr in range(len(ESSENTIA_ATTRIBS)):
                sim += abs(seed[ESSENTIA_ATTRIBS[attr]]-row[attr+5])/(seed[ESSENTIA_ATTRIBS[attr]]+0.00000001) # Add a little to ensure not div by 0!

            entry['similarity'] = sim/len(ESSENTIA_ATTRIBS) # TODO: bpm
            entries.append(entry)
        # Sort entries by similarity, highest first
        return sorted(entries, key=lambda k: k['similarity'])
