#!/usr/bin/env python3
"""Build the website locally from a copy of the real data, with a pretend internet that
returns today's real numbers. Usage: python3 stats/tools/preview.py [out_dir]"""
import os
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tests"))
from fakes import FakePost, FakeWorld  # noqa: E402

out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/piracy-preview")
data = out / "data"
if data.exists():
    shutil.rmtree(data)
shutil.copytree(HERE / "data", data)
os.environ.update({"STATS_DATA": str(data), "STATS_SITE": str(out / "site"), "DRY_RUN": "1",
                   "BOT_NOW": os.environ.get("BOT_NOW", "2026-11-18T02:07:00Z"), "YOUTUBE_API_KEY": "fake"})
world = FakeWorld(os.environ["BOT_NOW"], youtube=[
    FakePost("Thxs9ZZ0VD8", "Cannon to the Kraken (cutscene) #roblox #piracy", "2026-11-15T02:48:26Z", 1350, 6.4, 0.009, 24),
    FakePost("hcNvPpxCBxI", "wait this is actually ROBLOX?? (new pirate game)", "2026-11-16T22:21:03Z", 400, 180, 0.055, 19),
    FakePost("Wp2pwWQsNOk", "New Roblox Pirate Game Has a Submarine Boss and Something Worse #robloxfyp", "2026-11-16T23:14:31Z", 1310, 3.4, 0.018, 28),
], subs=None, members=12, board_csv=(HERE / "tests" / "board_sample.csv").read_text())
from piracy import net  # noqa: E402
net.transport = world.transport
net.sleep = lambda s: None
import run  # noqa: E402
run.main()
print("site:", out / "site")
