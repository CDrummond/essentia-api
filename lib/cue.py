#
# Analyse files with Musly, and provide an API to retrieve similar tracks
#
# Copyright (c) 2020-2021 Craig Drummond <craig.p.drummond@gmail.com>
# GPLv3 license.
#

import logging
from urllib.parse import quote

CUE_TRACK = '.CUE_TRACK.'
_LOGGER = logging.getLogger(__name__)


def convert_from_cue_path(path):
    hsh = path.find('#')
    if hsh>0:
        return path.replace('#', CUE_TRACK)+'.mp3'
    return path


def convert_to_cue_url(path):
    cue = path.find(CUE_TRACK)
    if cue>0:
        parts = path.replace(CUE_TRACK, '#').split('#')
        path='file://'+quote(parts[0])+'#'+parts[1]
        return path[:-4]
    return path
