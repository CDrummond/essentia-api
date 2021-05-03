# Essentia API Server

Simple python3 API server to provide a HTTP API to retrieve similar tracks to
any provided seed tracks.


## Analysing Tracks

Before this script can function you first need to anayze your tracks using
[Essentia Analyzer](https://github.com/CDrummond/essentia-analyzer)


## Similarity API 

The API server can be installed as a Systemd service, or started manually:

```
./essentia-api.py -c config.json -l DEBUG
```

Only 1 API is currently supported:

```
http://HOST:11000/api/similar?track=/path/of/track&track=/path/of/another/track&count=10&filtergenre=1&min=30&max=600&norepart=15&norepalb=25&previous=/path/to/previous&filterxmas=1&shuffle=1
```
...this will get 10 similar tracks to those supplied.

If `filtergenre=1` is supplied then only tracks whose genre matches a
pre-configured set of genres (mapped from seed tracks) will be used. e.g. if
`["Heavy Metal", "Metal", "Power Metal"]` is defined in the config, and a seed
tack's genre has `Metal` then only tracks with one of these 3 genres will be
considered.

If `filterxmas=1` is supplied, then tracks with 'Christmas' or 'Xmas' in their
genres will be excluded - unless it is December.

`min` and `max` can be used to set the minimum, and maximum, duration (in
seconds) of tracks to be considered.

`norepart` specifies the number of tracks where an artist should not be
repeated. This is not a hard-limit, as if there are too few candidates then
repeats can happen.

`norepalb` specifies the number of tracks where an album should not be
repeated. This does not aply to 'Various Artist' albums. This is not also not a
hard-limit, as if there are too few candidates then repeats can happen.

`previous` may be used to list tracks to ignore (e.g. tracks that are already in
the queue). This parameter, like `track`, may be repeated multiple times.

`shuffle` indicates that the chosen tracks should be shuffled.

For each seed track, the API will attempt to locate the desired `count` similar
tracks.  If `shuffle=1` is supplied then double `count` number of tracks will
be found, these wll be shuffled, and then then top `count` tracks returned.

Metadata for tracks is stored in an SQLite database, this has an `ignore` column
which if set to `1` will cause the API to not use this track if it is returned
as a similar track by essentia. In this way you can exclude specific tracks from
being added to mixes - but if they are already in the queue, then they can sill
be used as seed tracks.

This API is intended to be used by [LMS Music Similarity Plugin](https://github.com/CDrummond/lms-musicsimilarity)

Genres are configured via the `genres` section of `config.json`, using the
following syntax:

```
{
 "genres:[
  [ "Rock", "Hard Rock", "Metal" ],
  [ "Pop", "Dance", "R&B"]
 ]
}
```

If a seed track has `Hard Rock` as its genre, then only tracks with `Rock`,
`Hard Rock`, or `Metal` will be allowed. If a seed track has a genre that is not
listed here then any track returned by Musly, that does not cotaiain any genre
lsited here, will be considered acceptable. Therefore, if seed is `Pop` then
a `Hard Rock` track would not be considered.

### HTTP Post

Alternatively, the API may be accessed via a HTTP POST call. To do this, the
params of the call are passed as a JSON object. eg.

```
{
 "track":["/path/trackA.mp3", "/path/trackB.mp3"],
 "filtergenre":1,
 "count":10
}
```

## Configuration

The sever reads its configuration from a JSON file (default name is `config.json`).
This has the following format:

```
{
 "lms":"/home/storage/Music/",
 "db":"/home/craig/Development/Essentia/lms-essentia/essentia.db",
 "genres":[
  ["Alternative Rock", "Classic Rock", "Folk/Rock", "Hard Rock", "Indie Rock", "Punk Rock", "Rock"],
  ["Dance", "Disco", "Hip-Hop", "Pop", "Pop/Folk", "Pop/Rock", "R&B", "Reggae", "Soul", "Trance"],
  ["Gothic Metal", "Heavy Metal", "Power Metal", "Progressive Metal", "Progressive Rock", "Symphonic Metal", "Symphonic Power Metal"]
 ],
 "ignoregenre":["Artist"],
 "normalize":{
  "artist":["feet", "ft", "featuring"],
  "album":["deluxe edition", "remastered"],
  "title"["demo", "radio edit"]
 },
 "port":11000,
 "host":"0.0.0.0"
}
```

* `lms` should be the path where LMS access your music files. The API
server will remove this path from API calls, so that it can look up tracks in
its database by their relative path.
* `db` should contain the path to the Essentia DB containing the analysis results.
* `genres` This is as described above.
* `ignoregenre` List of artists where genre filtering (excluding christmas)
should be ignored. To apply to all artists, use '*' - e.g. `"ignoregenre":"*"`
* `normalize.artist` List of strings to split artist names, e.g. "A ft. B"
becomes "A" (periods are automatically removed)
* `normalize.album` List of strings to remove from album names.
* `normalize.title` List of strings to remove from titles.
* `port` This is the port number the API is accessible on.
* `host` IP addres on which the API will listen on. Use `0.0.0.0` to listen on
all interfaces on your network.

