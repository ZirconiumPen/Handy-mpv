#!/usr/bin/python3

import argparse
import json
from os.path import isfile
from pathlib import Path
from time import time_ns

import mpv
import requests

import config
from utils import fundoubler, funhalver

API_ENDPOINT = "https://www.handyfeeling.com/api/handy-rest/v3"

# Two alternatives; if one doesn't work, try the other
CACHE_URL = "https://handyfeeling.com/api/sync/upload"
# CACHE_URL = "https://tugbud.kaffesoft.com/cache"

HEADERS = {
    "X-Connection-Key": config.CONNECTION_KEY,
    "X-Api-Key": config.APPLICATION_ID,
}
HSSP_ID = 1

SEC_TO_MS = 10**3
SEC_TO_NS = 10**9
RESYNC_COOLDOWN = 3600 * SEC_TO_NS

client_server_offset = 0  # in milliseconds


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

    r = requests.get(f"{API_ENDPOINT}/servertime", headers=HEADERS)
    data = r.json()
    server_time = data["server_time"]

    receive_time = get_time_ms()

    rtd = receive_time - send_time
    estimated_server_time = int(server_time + rtd / 2)
    offset = estimated_server_time - receive_time
    return offset


def calculate_client_server_offset(n_samples=30):
    # algorithm from https://www.handyfeeling.com/api/handy-rest/v3/docs/#/UTILS/getServerTime
    print("Calculating offset...")
    aggregate_offset = 0
    for i in range(n_samples):
        aggregate_offset += measure_offset()
        print(f"Sample {i}: aggregate offset = {aggregate_offset}ms")
    average_offset = aggregate_offset / n_samples
    return average_offset


def find_video(script_path):
    base_name = script_path.with_suffix("")
    # TODO: try prefixes
    video_path = f"{base_name}.mp4"
    if isfile(video_path):
        return video_path
    return None


def mod_script(script_path, modifier):
    with open(script_path) as f:
        script = json.loads(f.read())
    script["actions"] = modifier(script["actions"])
    return (script_path, json.dumps(script))


def upload_script(script):
    r = requests.post(CACHE_URL, files={"file": script})
    data = r.json()
    url = data["url"]
    print("Uploading:", url)
    r = requests.put(f"{API_ENDPOINT}/hssp/setup", json={"url": url}, headers=HEADERS)


def check_connection():
    r = requests.get(f"{API_ENDPOINT}/mode", headers=HEADERS)
    if r.status_code != 200:
        print(f"Bad status: {r.status_code}")
        return False
    if not r.text.strip():
        print("Empty response")
        return False

    try:
        data = r.json()
    except ValueError as e:
        print(f"Invalid JSON: {r.text}")
        return False

    if data["result"]["mode"] != HSSP_ID:
        r = requests.put(
            f"{API_ENDPOINT}/mode2", json={"mode": HSSP_ID}, headers=HEADERS
        )
    return True


print("Getting Handy status...")
if not check_connection():
    print("Couldn't sync with Handy, exiting...")
    exit()
print("Handy connected!")

parser = argparse.ArgumentParser(description="Handy MPV sync Utility")
parser.add_argument("script_path", type=Path, help="The script file to play")
parser.add_argument("--double", action="store_true", help="Enable FunDoubler")
parser.add_argument("--half", action="store_true", help="Enable FunHalver")
args = parser.parse_args()

script_name = str(args.script_path)

if not isfile(args.script_path):
    print(f"Script not found: {script_name}")
    exit()

video_name = find_video(args.script_path)
if not video_name:
    print("Video not found")
    exit()
print(f"Video found: {video_name}")
if args.double:
    script_to_use = mod_script(script_name, fundoubler)
elif args.half:
    script_to_use = mod_script(script_name, funhalver)
else:
    script_to_use = open(script_name, "rb")

upload_script(script_to_use)

saved_time = get_saved_time()

if time_ns() - saved_time["last_saved"] < RESYNC_COOLDOWN:
    client_server_offset = saved_time["client_server_offset"]
else:
    client_server_offset = calculate_client_server_offset()
    print(f"Syncing complete, new offset: {client_server_offset:.02f} ms")
    save_server_time()

player = mpv.MPV(
    config=True,
    input_default_bindings=True,
    input_vo_keyboard=True,
    osc=True,
)
current_speed = 1.0
player.play(video_name)


def stop_handy():
    requests.put(f"{API_ENDPOINT}/hssp/stop", headers=HEADERS)


def play_handy():
    time_s = player._get_property("playback-time")
    if time_s is None:
        time_s = 0
    time_ms = int(time_s * SEC_TO_MS)
    payload = {
        "server_time": get_server_time(),
        "startTime": time_ms,
        "playback_rate": current_speed,
    }
    requests.put(f"{API_ENDPOINT}/hssp/play", json=payload, headers=HEADERS)


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


def on_player_speed_changed(name, new_speed):
    global current_speed
    current_speed = new_speed
    play_handy()


player.observe_property("speed", on_player_speed_changed)

try:
    player.wait_for_playback()
finally:
    stop_handy()
