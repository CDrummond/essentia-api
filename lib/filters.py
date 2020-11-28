#
# Analyse files with Musly, and provide an API to retrieve similar tracks
#
# Copyright (c) 2020 Craig Drummond <craig.p.drummond@gmail.com>
# GPLv3 license.
#

VARIOUS_ARTISTS = ['Various', 'Various Artists']
CHRISTMAS_GENRES = ['Christmas', 'Xmas']

def same_artist_or_album(seeds, track, check_album_only=False, max_check=0):
    check = 0
    for seed in seeds:
        if seed['artist']==track['artist'] and not check_album_only:
            return True
        if seed['album']==track['album'] and 'albumartist' in seed and 'albumartist' in track and seed['albumartist']==track['albumartist'] and track['albumartist'] not in VARIOUS_ARTISTS:
            return True
        check+=1
        if max_check>0 and check>=max_check:
            return False
    return False


def genre_matches(config, seed_genres, track):
    if 'genres' not in track or len(track['genres'])<1:
        return True # Track has no genre? Then can't filter out...

    if len(seed_genres)<1:
        # No filtering for seed track genres
        if 'all_genres' in config:
            for tg in track['genres']:
                if tg in config['all_genres']:
                    # Track's genre is in config list, but not in seeds, so filter out track
                    return False
        # No seed genres, and track's genre not in filters, so accept track
        return True

    for sg in seed_genres:
        if sg in track['genres']:
            return True

    return False


def is_christmas(track):
    if 'genres' in track and len(track['genres'])>=0:
        for genre in track['genres']:
            if genre in CHRISTMAS_GENRES:
                return True

    return False


def match_artist(artists, track):
    for artist in artists:
        if artist==track['artist'] or ('albumartist' in track and artist==track['albumartist']):
            return True
    return False


def match_album(albums, track):
    if (not 'album' in track) or ( ('albumartist' not in track) and ('artist' not in track)):
        return False

    album = '%s - %s' % (track['albumartist'] if 'albumartist' in track else track['artist'], track['album'])
    return album in albums


def check_duration(min_duration, max_duration, meta):
    if 'duration' not in meta or meta['duration'] is None or meta['duration']<=0:
        return True # No duration to check!

    if min_duration>0 and meta['duration']<min_duration:
        return False

    if max_duration>0 and meta['duration']>max_duration:
        return False

    return True

