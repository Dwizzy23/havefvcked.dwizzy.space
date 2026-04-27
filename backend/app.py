import os
import uuid
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import librosa
import numpy as np

app = Flask(__name__)
CORS(app)

WORK_DIR = Path("/tmp/havefvcked")
WORK_DIR.mkdir(exist_ok=True)

# Auto-cleanup jobs older than 1 hour
jobs = {}

# ── Key detection ────────────────────────────────────────────────────────────

KEYS = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                           2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                           2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

def detect_key(y, sr):
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, bins_per_octave=36)
    chroma_mean = chroma.mean(axis=1)

    best_score = -np.inf
    best_key = "C"
    best_mode = "major"

    for i in range(12):
        rotated = np.roll(chroma_mean, -i)
        major_score = np.corrcoef(rotated, MAJOR_PROFILE)[0, 1]
        minor_score = np.corrcoef(rotated, MINOR_PROFILE)[0, 1]

        if major_score > best_score:
            best_score = major_score
            best_key = KEYS[i]
            best_mode = "major"
        if minor_score > best_score:
            best_score = minor_score
            best_key = KEYS[i]
            best_mode = "minor"

    return f"{best_key} {best_mode}"

# ── Download helper ──────────────────────────────────────────────────────────

def download_audio(url: str, out_path: Path) -> Path:
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(out_path / "audio.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "wav",
            "preferredquality": "192",
        }],
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get("title", "Unknown")
        duration = info.get("duration", 0)

    wav_file = out_path / "audio.wav"
    if not wav_file.exists():
        # fallback: find any audio file and rename
        for f in out_path.iterdir():
            if f.suffix in (".wav", ".mp3", ".m4a", ".webm", ".opus"):
                if f.suffix != ".wav":
                    subprocess.run(
                        ["ffmpeg", "-i", str(f), str(wav_file), "-y"],
                        capture_output=True
                    )
                    f.unlink()
                break

    return wav_file, title, duration

# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/api/info", methods=["POST"])
def get_info():
    """Return title + duration without full download (fast)."""
    data = request.get_json()
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "Brak URL"}), 400

    try:
        ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return jsonify({
            "title": info.get("title", "Nieznany utwór"),
            "duration": info.get("duration", 0),
            "thumbnail": info.get("thumbnail", ""),
            "uploader": info.get("uploader", ""),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/analyze", methods=["POST"])
def analyze():
    """Download + detect BPM & Key."""
    data = request.get_json()
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "Brak URL"}), 400

    job_id = str(uuid.uuid4())
    job_dir = WORK_DIR / job_id
    job_dir.mkdir()
    jobs[job_id] = {"status": "downloading", "progress": 0}

    def run():
        try:
            jobs[job_id]["status"] = "downloading"
            wav, title, duration = download_audio(url, job_dir)

            jobs[job_id]["status"] = "analyzing"
            jobs[job_id]["progress"] = 50

            y, sr = librosa.load(str(wav), sr=None, mono=True)

            # BPM
            tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
            bpm = round(float(np.atleast_1d(tempo)[0]), 1)

            # Key
            key = detect_key(y, sr)

            jobs[job_id].update({
                "status": "done",
                "progress": 100,
                "bpm": bpm,
                "key": key,
                "title": title,
                "duration": duration,
            })

        except Exception as e:
            jobs[job_id] = {"status": "error", "error": str(e)}
        finally:
            # cleanup wav after analysis (not needed for analyze-only)
            if wav.exists():
                wav.unlink()

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/split", methods=["POST"])
def split():
    """Download + split into 4 stems using demucs."""
    data = request.get_json()
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "Brak URL"}), 400

    job_id = str(uuid.uuid4())
    job_dir = WORK_DIR / job_id
    job_dir.mkdir()
    jobs[job_id] = {"status": "downloading", "progress": 0}

    def run():
        try:
            jobs[job_id]["status"] = "downloading"
            wav, title, duration = download_audio(url, job_dir)

            jobs[job_id]["status"] = "splitting"
            jobs[job_id]["progress"] = 30

            # Run demucs (htdemucs model = 4 stems)
            result = subprocess.run(
                [
                    "python", "-m", "demucs",
                    "--two-stems", "no",
                    "-n", "htdemucs",
                    "--out", str(job_dir / "stems"),
                    str(wav),
                ],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                raise Exception(f"Demucs error: {result.stderr[-500:]}")

            jobs[job_id]["progress"] = 90

            # Find output stems
            stems_base = job_dir / "stems" / "htdemucs" / "audio"
            stem_map = {
                "vocals": "Vocal",
                "bass": "Bass",
                "drums": "Drums",
                "other": "Melody",
            }
            stems = {}
            for src_name, display_name in stem_map.items():
                src = stems_base / f"{src_name}.wav"
                if src.exists():
                    dst = job_dir / f"{display_name}.wav"
                    shutil.move(str(src), str(dst))
                    stems[display_name] = str(dst)

            jobs[job_id].update({
                "status": "done",
                "progress": 100,
                "stems": list(stems.keys()),
                "title": title,
                "job_id": job_id,
            })

        except Exception as e:
            jobs[job_id] = {"status": "error", "error": str(e)}

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/job/<job_id>", methods=["GET"])
def job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/api/download/<job_id>/<stem>", methods=["GET"])
def download_stem(job_id, stem):
    allowed = {"Vocal", "Bass", "Drums", "Melody"}
    if stem not in allowed:
        return jsonify({"error": "Nieprawidłowy stem"}), 400

    file_path = WORK_DIR / job_id / f"{stem}.wav"
    if not file_path.exists():
        return jsonify({"error": "Plik nie istnieje"}), 404

    return send_file(
        str(file_path),
        as_attachment=True,
        download_name=f"{stem}.wav",
        mimetype="audio/wav",
    )


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# ── Cleanup thread ────────────────────────────────────────────────────────────

def cleanup_old_jobs():
    while True:
        time.sleep(300)
        now = time.time()
        for job_id in list(jobs.keys()):
            job_dir = WORK_DIR / job_id
            if job_dir.exists():
                age = now - job_dir.stat().st_mtime
                if age > 3600:
                    shutil.rmtree(job_dir, ignore_errors=True)
                    jobs.pop(job_id, None)

threading.Thread(target=cleanup_old_jobs, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
