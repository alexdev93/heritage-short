"""Two-pass loudnorm lands on the -14 LUFS target (single pass came out ~1 LU low). Needs ffmpeg."""
import re
import subprocess

from pipeline import assemble


def _lufs(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True)
    return float(re.findall(r"I:\s+(-?\d+\.\d) LUFS", r.stderr)[-1])


def test_two_pass_loudnorm_hits_minus_14(tmp_path):
    src, out = tmp_path / "quiet.wav", tmp_path / "out.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
                    "-af", "volume=-30dB", "-ar", "48000", "-ac", "2", str(src)], check=True)
    assemble.loudnorm_two_pass(src, out, 5.0)
    assert abs(_lufs(out) - (-14.0)) <= 0.5
