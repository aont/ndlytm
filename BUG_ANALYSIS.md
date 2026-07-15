## Cause

The exception occurs in the following code in `server.py`:

```python
album = track["album"]
match_album = catalogname_pat.match(album["cataloguename"])
album_title = match_album.group(1)
album_artist = match_album.group(2)
```

If `catalogname_pat.match(...)` does not find a match, it returns `None`. Calling `match_album.group(1)` on that value results in the following exception:

```text
AttributeError: 'NoneType' object has no attribute 'group'
```

The regular expression being used is:

```python
catalogname_pat = re.compile(r"(.*)（(.*)）")
```

This assumes that `cataloguename` is always formatted using **full-width parentheses**, like this:

```text
Album Title（Album Artist）
```

The input example in the README uses the same format.

The actual data in this case was likely one of the following:

```text
Album Title
Album Title (Artist)
Album Title【Artist】
Album Title（Artist
```

In other words, `cataloguename` was a string, but most likely did not contain full-width `（...）` parentheses. If the value itself had been `None`, the regular expression call would have raised a `TypeError` instead, so that is not consistent with the observed exception.

## Execution Flow

Based on the logs, the failure occurred during MP4 metadata tagging rather than networking or cache handling.

1. Album artwork retrieval succeeded.
2. Reading the cached M4A file succeeded.
3. The file was opened with `mutagen.mp4.MP4`.
4. Tags such as title and artist were written.
5. Parsing `cataloguename` failed.
6. The entire job failed.

The cache is designed to store unmodified audio files, so it is not the cause of this failure.

If an exception occurs during metadata tagging, the partially created output file is deleted and the exception is re-raised. As a result, a corrupted output file is unlikely to remain, but all 39 tracks are aborted when the first track fails.

The following log entry at the end is not abnormal:

```text
GET /progress-stream/... HTTP/1.1" 200
```

It simply indicates that the browser successfully established the Server-Sent Events (SSE) connection used for progress updates. Although the job itself failed, the progress API continued responding normally.

## Why It Happens with the Input Data

The bookmarklet forwards `PlayListsTracks` from the source page to the backend without modification.

Therefore, if the N data uses a different `cataloguename` format for some albums, it becomes incompatible with the backend's fixed regular expression.

The current implementation does not include:

* Validation that the regular expression matched
* Support for ASCII parentheses
* A fallback when no parentheses are present
* Logging of the problematic `cataloguename`

## Minimal Fix

At a minimum, the match result should be checked before calling `group()`.

```python
catalogue_name = str(album.get("cataloguename") or "").strip()
match_album = catalogname_pat.fullmatch(catalogue_name)

if match_album:
    album_title = match_album.group(1).strip()
    album_artist = match_album.group(2).strip()
else:
    state.log(f"Unexpected cataloguename format: {catalogue_name!r}")
    album_title = catalogue_name or "Unknown Album"
    album_artist = track.get("artist", "")
```

With this change, the entire job will no longer fail when an album uses a different format.

## Recommended Fix

A more robust approach is to support both full-width and ASCII parentheses and move the parsing logic into a dedicated function.

```python
catalogname_patterns = (
    re.compile(r"^(?P<title>.+?)（(?P<artist>.+?)）$"),
    re.compile(r"^(?P<title>.+?)\((?P<artist>.+?)\)$"),
)


def parse_catalogue_name(value, fallback_artist=""):
    catalogue_name = str(value or "").strip()

    for pattern in catalogname_patterns:
        match = pattern.fullmatch(catalogue_name)
        if match:
            return (
                match.group("title").strip(),
                match.group("artist").strip(),
            )

    return catalogue_name or "Unknown Album", fallback_artist
```

The calling code then becomes:

```python
album = track.get("album") or {}

album_title, album_artist = parse_catalogue_name(
    album.get("cataloguename"),
    fallback_artist=track.get("artist", ""),
)

audio["\xa9alb"] = [album_title]

if album_artist:
    audio["aART"] = [album_artist]
```

### Advantages of This Fix

* Prevents crashes when the regular expression does not match
* Supports both full-width and ASCII parentheses
* Handles empty `cataloguename` values gracefully
* Avoids writing an empty album artist tag
* Allows the parser to be unit tested independently

## Additional Logging

To determine the actual format of the production data, it is useful to log the value with `repr()` whenever parsing fails.

```python
state.log(
    f"Unrecognized cataloguename for track {track_num}: "
    f"{album.get('cataloguename')!r}"
)
```

This makes it possible to identify whitespace, newlines, ASCII parentheses, special characters, and other formatting differences.

## Conclusion

The immediate cause is that `album["cataloguename"]` did not match the expected full-width parenthesis format, yet `group()` was called without checking whether the regular expression matched.

Fundamentally, this is not so much malformed input as it is **insufficient backend input validation that fails to account for variations in the formatting of external data**. Rather than only changing the regular expression, the appropriate fix is to add a fallback path and diagnostic logging for unmatched input.

No repository writes, commits, branch creation, or pushes were performed.
