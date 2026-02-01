#!/usr/bin/python3

import argparse
import json
import logging
from os.path import isfile
from pathlib import Path
from time import time_ns

from mpv import MPV
from requests import RequestException, Session, Timeout
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config
from utils import fundoubler, funhalver

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger()


API_ENDPOINT = "https://www.handyfeeling.com/api/handy/v2"

# Goes down the list until succeeding
CACHE_URLS = [
    "https://tugbud.kaffesoft.com/cache",
    "https://handyfeeling.com/api/sync/upload",
]

CONNECT_TIMEOUT = 3
READ_TIMEOUT = 10
DEFAULT_TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)

HEADERS = {"X-Connection-Key": config.CONNECTION_KEY}

HSSP_ID = 1

SEC_TO_MS = 10**3
SEC_TO_NS = 10**9
RESYNC_COOLDOWN = 3600 * SEC_TO_NS

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm"}

client_server_offset = 0  # in milliseconds


class SessionWithTimeout:
    def __init__(self, headers=None, timeout=DEFAULT_TIMEOUT):
        self._session = Session()
        self._timeout = timeout

        if headers:
            self._session.headers.update(HEADERS)

        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "PUT"],
        )

        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("https://", adapter)

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", self._timeout)
        return self._session.request(method, url, **kwargs)

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self.request("PUT", url, **kwargs)


api_session = SessionWithTimeout(HEADERS)
public_session = SessionWithTimeout()


def check_connection():
    try:
        r = api_session.get(f"{API_ENDPOINT}/status")
        r.raise_for_status()
        if not r.text.strip():
            logger.error("Empty response from /status endpoint")
            return False
        try:
            data = r.json()
        except ValueError:
            logger.error("Invalid JSON from /status endpoint: %r", r.text)
            return False
        mode = data.get("mode")
        if not isinstance(mode, int):
            logger.error("Missing or invalid 'mode' field in response: %r", data)
            return False
        logger.debug("Current mode reported: %d", mode)
        if mode == HSSP_ID:
            return True
        logger.info("Switching mode from %d to %d", mode, HSSP_ID)
        put_resp = api_session.put(f"{API_ENDPOINT}/mode", json={"mode": HSSP_ID})
        put_resp.raise_for_status()
        logger.info("Mode successfully updated")
        return True
    except Timeout:
        logger.warning("Timeout while contacting API endpoint")
    except RequestException:
        logger.exception("Request error while checking connection")
    except Exception:
        logger.exception("Unexpected error in check_connection")
    return False


def get_time_ms():
    return int(time_ns() / 10**6)


def get_server_time():
    return int(get_time_ms() + client_server_offset)


def save_server_time():
    if not isfile(config.TIME_SYNC_FILE):
        fp = open(config.TIME_SYNC_FILE, "x")
        fp.close()
    with open(config.TIME_SYNC_FILE, "w") as f:
        json.dump(
            {
                "last_saved": time_ns(),
                "client_server_offset": client_server_offset,
            },
            f,
        )


def get_saved_time():
    if not isfile(config.TIME_SYNC_FILE):
        fp = open(config.TIME_SYNC_FILE, "w")
        fp.write('{"last_saved": 0}')
        fp.close()
    with open(config.TIME_SYNC_FILE, "r") as f:
        time = json.load(f)
        return time


def measure_offset():
    send_time = get_time_ms()

    r = public_session.get(f"{API_ENDPOINT}/servertime")
    data = r.json()
    server_time = data["serverTime"]

    receive_time = get_time_ms()

    rtd = receive_time - send_time
    estimated_server_time = int(server_time + rtd / 2)
    offset = estimated_server_time - receive_time
    return offset


def calculate_client_server_offset(n_samples=30):
    # algorithm from https://www.handyfeeling.com/api/handy-rest/v3/docs/#/UTILS/getServerTime
    logger.info("Calculating offset...")
    aggregate_offset = 0
    for i in range(n_samples):
        aggregate_offset += measure_offset()
        logger.info("Sample %d: aggregate offset = %dms", i, aggregate_offset)
    average_offset = aggregate_offset / n_samples
    return average_offset


def find_video(script_path: Path):
    directory = script_path.parent
    prefix = script_path.stem.split(" (", 1)[0]
    for p in directory.iterdir():
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS and p.stem.startswith(prefix):
            return p
    logger.error("Could not find video for script: %s" % script_path)
    return None


def mod_script(script_path, modifier):
    with open(script_path) as f:
        script = json.loads(f.read())
    script["actions"] = modifier(script["actions"])
    return (script_path, json.dumps(script))


def upload_script(script):
    for cache_url in CACHE_URLS:
        logger.info(f"Trying cache URL: %s", cache_url)
        try:
            r = public_session.post(cache_url, files={"file": script})
            r.raise_for_status()
            data = r.json()
            url = data.get("url")
            if not url:
                logger.warning("No 'url' in response from %s", cache_url)
                continue
            logger.info("Received upload URL: %s", url)
            r = api_session.put(f"{API_ENDPOINT}/hssp/setup", json={"url": url})
            r.raise_for_status()
            logger.info("Successfully uploaded script")
            return True
        except Timeout:
            logger.warning("Timeout contacting %s", cache_url)
        except RequestException:
            logger.warning("Request error with %s", cache_url)
    logger.error("All cache URLs failed")
    return False


logger.info("Getting Handy status...")
if not check_connection():
    exit()
logger.info("Handy connected!")

parser = argparse.ArgumentParser(description="Handy MPV sync utility")
parser.add_argument("script_path", type=Path, help="Script file to play")
parser.add_argument("--double", action="store_true", help="Enable FunDoubler")
parser.add_argument("--half", action="store_true", help="Enable FunHalver")
args = parser.parse_args()

script_name = str(args.script_path)

if not args.script_path.is_file():
    logger.error("Script not found: %s", args.script_path)
    exit()

video_path = find_video(args.script_path)
if not video_path:
    exit()
video_name = str(video_path)
logger.info(f"Video found: {video_name}")
if args.double:
    script_to_use = mod_script(script_name, fundoubler)
elif args.half:
    script_to_use = mod_script(script_name, funhalver)
else:
    script_to_use = open(script_name, "rb")

if not upload_script(script_to_use):
    logger.error("Failed to upload script")
    exit()

saved_time = get_saved_time()

if time_ns() - saved_time["last_saved"] < RESYNC_COOLDOWN:
    client_server_offset = saved_time["client_server_offset"]
else:
    client_server_offset = calculate_client_server_offset()
    logger.info(f"Syncing complete, new offset: %.02f ms", client_server_offset)
    save_server_time()

player = MPV(config=True, input_default_bindings=True, input_vo_keyboard=True, osc=True)
player.play(video_name)


def stop_handy():
    api_session.put(f"{API_ENDPOINT}/hssp/stop")


def play_handy():
    time_s = player._get_property("playback-time")
    if time_s is None:
        time_s = 0
    time_ms = int(time_s * SEC_TO_MS)
    payload = {
        "estimatedServerTime": get_server_time(),
        "startTime": time_ms,
    }
    api_session.put(f"{API_ENDPOINT}/hssp/play", json=payload)


@player.on_key_press("up")
def my_up_binding(*args):
    stop_handy()


@player.on_key_press("down")
def my_down_binding(*args):
    play_handy()


@player.on_key_press("q")
def my_q_binding(*args):
    player.command("quit")


@player.event_callback("playback-restart")
def file_restart(event):
    play_handy()


def on_player_pause_changed(name, is_paused):
    if is_paused:
        stop_handy()
    else:
        play_handy()


player.observe_property("pause", on_player_pause_changed)


try:
    player.wait_for_playback()
finally:
    stop_handy()
