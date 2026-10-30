"""Compile the supplied app icons with Xcode, preserving their artwork."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from builder import ROOT


def compile_icons(catalog, streams=("multiplayer", "multiplayer-legacy", "pokermon")):
    files = {}
    for stream in streams:
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            assets = work / "Images.xcassets"
            shutil.copytree(catalog, assets)
            icon = assets / "iOS AppIcon.appiconset"
            shutil.rmtree(icon)
            icon.mkdir()
            shutil.copy2(
                ROOT / "assets/icons" / (stream + "-1024.png"), icon / "icon.png"
            )
            (icon / "Contents.json").write_text(
                json.dumps(
                    {
                        "images": [
                            {
                                "filename": "icon.png",
                                "idiom": "universal",
                                "platform": "ios",
                                "size": "1024x1024",
                            }
                        ],
                        "info": {"author": "xcode", "version": 1},
                    }
                )
            )
            output = work / "compiled"
            output.mkdir()
            subprocess.run(
                [
                    "xcrun",
                    "actool",
                    str(assets),
                    "--compile",
                    str(output),
                    "--platform",
                    "iphoneos",
                    "--minimum-deployment-target",
                    "15.0",
                    "--target-device",
                    "iphone",
                    "--target-device",
                    "ipad",
                    "--app-icon",
                    "iOS AppIcon",
                    "--output-partial-info-plist",
                    str(output / "icon-info.plist"),
                ],
                check=True,
            )
            for path in output.rglob("*"):
                if path.is_file():
                    files[
                        "builder-icons/"
                        + stream
                        + "/"
                        + path.relative_to(output).as_posix()
                    ] = path.read_bytes()
    return files
