"""Build a static satellite-image catalog; KMA_API_KEY is read only from the environment."""
import csv
import io
import json
import os
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image

key = os.environ.get("KMA_API_KEY")
if not key:
    raise SystemExit("KMA_API_KEY is not configured")
root = Path("public/satellite")
root.mkdir(parents=True, exist_ok=True)
manifest = {}
jobs = []
for year in range(2020, 2026):
    data = json.loads(Path(f"public/data/{year}.json").read_text(encoding="utf-8"))
    for number, raw in data["tracks"].items():
        if os.environ.get("KMA_TEST_STORM") and os.environ["KMA_TEST_STORM"] != f"{year}-{int(number)}":
            continue
        stamps = []
        for row in csv.reader(io.StringIO(raw)):
            if len(row) < 7 or row[0].strip() != "0":
                continue
            tm = row[6].strip()
            if len(tm) == 12 and tm.isdigit() and tm not in stamps:
                stamps.append(tm)
        stamps.sort()
        identity = f"{year}-{int(number)}"
        manifest[identity] = []
        if stamps:
            indexes = sorted({round(i * (len(stamps) - 1) / 2) for i in range(3)})
            for index in indexes:
                jobs.append((identity, stamps[index]))

def download(job):
    identity, tm = job
    params = urllib.parse.urlencode({"typ":"img", "lvl":"l1b", "are":"ea", "chn":"ir105", "tm":tm, "authKey":key})
    request = urllib.request.Request("https://apihub.kma.go.kr/api/typ01/url/sat_file_down2.php?" + params, headers={"User-Agent":"TyphoonEducation/1.0"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                data = response.read(15_000_001)
            if len(data) > 15_000_000 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
                return identity, None
            image = Image.open(io.BytesIO(data)).convert("RGB")
            image.thumbnail((900, 900))
            directory = root / identity
            directory.mkdir(parents=True, exist_ok=True)
            image.save(directory / f"{tm}.jpg", "JPEG", quality=72, optimize=True)
            return identity, {"timeUTC":tm, "path":f"./satellite/{identity}/{tm}.jpg"}
        except Exception:
            if not attempt:
                time.sleep(1)
    return identity, None

with ThreadPoolExecutor(max_workers=4) as executor:
    futures = [executor.submit(download, job) for job in jobs]
    for i, future in enumerate(as_completed(futures), 1):
        identity, frame = future.result()
        if frame:
            manifest[identity].append(frame)
        if i % 25 == 0 or i == len(futures):
            print(f"Satellite requests completed: {i}/{len(futures)}", flush=True)
for frames in manifest.values():
    frames.sort(key=lambda frame: frame["timeUTC"])
(root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
count = sum(bool(frames) for frames in manifest.values())
if not count:
    raise SystemExit("No satellite images were available; check KMA permissions.")
print(f"Satellite catalog ready: {count}/{len(manifest)} storms")

