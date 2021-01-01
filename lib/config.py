#
# Essentia API Service for LMS
#
# Copyright (c) 2020-2021 Craig Drummond <craig.p.drummond@gmail.com>
# GPLv3 license.
#

import json
import logging
import os

_LOGGER = logging.getLogger(__name__)

def read_config(path):
    config={}

    if not os.path.exists(path):
        _LOGGER.error('%s does not exist' % path)
        exit(-1)
    try:
        with open(path, 'r') as configFile:
            config = json.load(configFile)
    except ValueError:
        _LOGGER.error('Failed to parse config file')
        exit(-1)
    except IOError:
        _LOGGER.error('Failed to read config file')
        exit(-1)

    for key in ['lms', 'db']:
        if not key in config:
            _LOGGER.error("'%s' not in config file" % key)
            exit(-1)
        if (key=='db' and not os.path.exists(config[key])):
            _LOGGER.error("'%s' does not exist" % config['db'])
            exit(-1)

    if not 'port' in config:
        config['port']=11002

    if not 'host' in config:
        config['host']='0.0.0.0'

    if 'genres' in config:
        config['all_genres']=[]
        for genres in config['genres']:
            for g in genres:
                if not g in config['all_genres']:
                    config['all_genres'].append(g)

    return config
