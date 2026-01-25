#!/usr/bin/python3

import argparse
import json
import sys
from os.path import exists
from time import time_ns

import mpv
import requests

import config

API_SECRET = config.API_SECRET
API_ENDPOINT = "https://www.handyfeeling.com/api/handy/v2/"
CACHE_URL = "https://tugbud.kaffesoft.com/cache"
# CACHE_URL = "https://handyfeeling.com/api/sync/upload"

SEC_TO_MS = 10**3
SEC_TO_NS = 10**9
RESYNC_COOLDOWN = 3600 * SEC_TO_NS
# TIMEOUT = 10 * SEC_TO_MS

time_sync_initial_offset = 0
time_sync_aggregate_offset = 0
time_sync_average_offset = 0
time_syncs = 0


def get_time_ms():
    return int(time_ns() / 10**6)


HEADERS = {"X-Connection-Key": API_SECRET}

parser = argparse.ArgumentParser(description="Handy MPV sync Utility")
parser.add_argument("file", metavar="file", type=str, help="The file to play")
parser.add_argument("--double", action="store_true", help="enable 2x speed conversion")

# this code is actually really dumb, should refactor, an intern probably
# did this. I'm just copying the JS code from the site.


def save_server_time():
    if not exists(config.TIME_SYNC_FILE):
        fp = open(config.TIME_SYNC_FILE, "x")
        fp.close()
    with open(config.TIME_SYNC_FILE, "w") as f:
        json.dump(
            {
                "last_saved": time_ns(),
                "time_sync_average_offset": time_sync_average_offset,
                "time_sync_initial_offset": time_sync_initial_offset,
            },
            f,
        )


def get_saved_time():
    if not exists(config.TIME_SYNC_FILE):
        fp = open(config.TIME_SYNC_FILE, "w")
        fp.write('{"last_saved": 0}')
        fp.close()
    with open(config.TIME_SYNC_FILE, "r") as f:
        time = json.load(f)
        return time


def get_server_time():
    time_now = get_time_ms()
    return int(time_now + time_sync_average_offset + time_sync_initial_offset)


def update_server_time():
    global time_sync_initial_offset, time_sync_aggregate_offset, time_sync_average_offset, time_syncs

    send_time = get_time_ms()
    r = requests.get(f"{API_ENDPOINT}servertime", headers=HEADERS)
    data = json.loads(r.text)
    server_time = data["serverTime"]
    time_now = get_time_ms()
    print("Server time:", server_time)
    print("Time now:", time_now)
    rtd = time_now - send_time
    estimated_server_time_now = int(server_time + rtd / 2)

    # this part here, real dumb.
    if time_syncs == 0:
        time_sync_initial_offset = estimated_server_time_now - time_now
        print(f"initial offset {time_sync_initial_offset} ms")
    else:
        offset = estimated_server_time_now - time_now - time_sync_initial_offset
        time_sync_aggregate_offset += offset
        time_sync_average_offset = time_sync_aggregate_offset / time_syncs

    time_syncs += 1
    if time_syncs < 30:
        update_server_time()
    else:
        print(f"we in sync, Average offset is: {time_sync_average_offset:d} ms")
        return


def find_script(video_path):
    video_name = video_path.replace("." + str.split(video_path, ".")[-1:][0], "")
    script_path = f"{video_name}.funscript"
    if exists(script_path):
        print(f"script found for video: {video_name}")
    return script_path


def script_2x(script_file):
    with open(script_file) as f:
        script = json.loads(f.read())

    edited = []
    for action in script["actions"]:
        action["pos"] = 0
        edited.append(action)

    final = []
    for idx, action in enumerate(edited):
        if action["pos"] == 95:
            action["pos"] = 100
        final.append(action)

        if idx == len(edited) - 1:
            break

        new_pos = {"at": int((action["at"] + edited[idx + 1]["at"]) / 2), "pos": 100}
        final.append(new_pos)

    script["actions"] = final
    return (script_file, json.dumps(script))


def upload_script(script, double=False):
    if double:
        doubled_script = script_2x(script)
        file_to_use = ("script.funscript", doubled_script[1])
    else:
        file_to_use = open(script, "rb")
    r = requests.post(CACHE_URL, files={"file": file_to_use})
    data = json.loads(r.text)
    print("uploading:", data)
    r = requests.put(
        f"{API_ENDPOINT}hssp/setup", json={"url": data["url"]}, headers=HEADERS
    )
    data = json.loads(r.text)


print("Getting Handy Status...")
r = requests.get(f"{API_ENDPOINT}status", headers=HEADERS)
data = json.loads(r.text)

if not data["mode"]:
    print("Couldn't Sync with Handy, Exiting.")
    exit()

if data["mode"] != 1:
    r = requests.put(f"{API_ENDPOINT}/mode", json={"mode": 1}, headers=HEADERS)
    print(r.text)

print("Handy connected, uploading script!")

args = parser.parse_args()
script = find_script(args.file)
upload_script(script, args.double)


saved_time = get_saved_time()

if time_ns() - saved_time["last_saved"] < RESYNC_COOLDOWN:
    time_sync_average_offset = saved_time["time_sync_average_offset"]
    time_sync_initial_offset = saved_time["time_sync_initial_offset"]
else:
    update_server_time()
    save_server_time()

player = mpv.MPV(input_default_bindings=True, input_vo_keyboard=True, osc=True)
player.play(args.file)


def sync_play(time_s=0.0, play=True):
    if not play:
        r = requests.put(f"{API_ENDPOINT}hssp/stop", headers=HEADERS)
        return
    time_ms = int(time_s * SEC_TO_MS)

    payload = {"estimatedServerTime": get_server_time(), "startTime": time_ms}
    r = requests.put(f"{API_ENDPOINT}hssp/play", json=payload, headers=HEADERS)


def toggle_motion(is_enabled=True):
    time_s = player._get_property("playback-time")
    sync_play(time_s, is_enabled)


@player.on_key_press("up")
def my_up_binding(*args):
    toggle_motion(False)


@player.on_key_press("down")
def my_up_binding(*args):
    toggle_motion(True)


@player.on_key_press("q")
def my_q_binding(*args):
    global player
    player.command("quit")


@player.event_callback("playback-restart")
def file_restart(event):
    time_s = player._get_property("playback-time")
    sync_play(time_s)
    print(f"Now playing at {time_s:.02f}s")


def video_pause_unpause(name, is_paused):
    if is_paused:
        sync_play(0, False)
        return
    time_s = player._get_property("playback-time")
    if time_s is None:
        return
    sync_play(time_s)


player.observe_property("pause", video_pause_unpause)


try:
    player.wait_for_playback()
finally:
    sync_play(0, False)
