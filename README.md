# handy-mpv

Simple script to play funscripts using `mpv` and the power of Python.

## Requirements

- Python
- [`uv`](https://docs.astral.sh/uv/) package manager
- A video and funscript with the same filename
- A Handy Application ID
  - You need [an account](https://user.handyfeeling.com/)
  (sign up with email) to make one

## Installation

1. Clone this repo.
1. Copy the config file: `$ cp config.py.example config.py`
1. Fill in CONNECTION_KEY and APPLICATION_ID in the newly created config file.

```python
CONNECTION_KEY="YOUR KEY HERE"
APPLICATION_ID="dQw4w9WgXcQ"
TIME_SYNC_FILE="/tmp/handy_mpv_server_time.json"
```

## Usage

```bash
$ python main.py path/to/script.funscript {args}
```

### Arguments

```text
--double: doubles every stroke in the provided script
(does not modify the actual file)

This option is mostly created for Fap Heroes, making every beat a full stroke.
For example, if you have 4 beats,

O---O---O---O

the resulting motion will be:

up-down-up-down-up-down-up

instead of:

up---down---up---down

This was created to more closely match the way
I would play Fap Heroes without the Handy.

Results may vary for normal scripts but sometimes creates very interesting results.
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
- If your video never starts when running the script for the first time,
try running it a second time.
- Pausing the video will pause the script. However, if you press the
resync button, the script will start playing with the video still paused.
- Scrubbing the player automatically scrubs the script to the appropriate
timestamp.
- If you have a looping video, the script will also loop.

## TODO

- [ ] Use Funhalver and Fundoubler algorithms as options
- [ ] Add support for Handy playback speed in response to MPV playback speed
