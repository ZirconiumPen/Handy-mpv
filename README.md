# handy-mpv (Firmware 3)

Simple script to play funscripts using `mpv` and the power of Python.

## Requirements

- Python
- [`uv`](https://docs.astral.sh/uv/) package manager
- A video and funscript with the same filename

## Installation

1. Clone this repo.
1. Copy the config file: `$ cp config.py.example config.py`
1. Fill in CONNECTION_KEY in the newly created config file.

```python
CONNECTION_KEY="YOUR KEY HERE"
TIME_SYNC_FILE="/tmp/handy_mpv_server_time.json"
```

## Usage

```bash
$ python main.py path/to/script.funscript {args}
```

## Shortcuts

- **Q**: Quit application
- **Up arrow**: Pause script playback but keep video playing.
- **Down arrow**: Re-sync script / restart script playback. Use this if
for some reason your script becomes out of sync.

All other mpv shortcuts should work as intended.

## Notes

- On startup, the script will do a time sync with the Handy server to
ensure accurate strokes. The server delay is stored in a file and the sync will
not re-happen for an hour after that.
- Scrubbing the player automatically scrubs the script to the appropriate
timestamp.
- If you have a looping video, the script will also loop.
- If you change MPV's playback rate (`[` and `]` by default),
the script will NOT change with it. Use the firmware 4 branch
if you need this functionality.

## TODO

- [ ] Use Funhalver and Fundoubler algorithms as options
