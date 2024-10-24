# app.py
from flask import Flask, request, jsonify, send_from_directory, send_file
import os
import tempfile
import re
from fpdf import FPDF
from PIL import Image
import yt_dlp
import cv2
from skimage.metrics import structural_similarity as compare_ssim
from youtube_transcript_api import YouTubeTranscriptApi

app = Flask(__name__, static_url_path='', static_folder='static')

# Define your helper functions here (like download_video, get_video_id, etc.)
# Example helper function (complete with your actual functions):
def download_video(url, output_file):
    if os.path.exists(output_file):
        os.remove(output_file)
    ydl_opts = {
        'outtmpl': output_file,
        'format': 'best',
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

def get_video_id(url):
    # (Your existing code here)
    pass  # Replace with your implementation

# Add all your other helper functions as defined in your original code...

@app.route('/')
def index():
    return send_file('static/index.html')

@app.route('/process_video', methods=['POST'])
def process_video():
    data = request.json
    urls = data.get('urls')
    output_files = []

    for url in urls:
        video_id = get_video_id(url)
        if not video_id:
            return jsonify({"error": f"Invalid URL: {url}"}), 400

        video_title = get_video_title(url)
        video_file = f"video_{video_id}.mp4"
        download_video(url, video_file)

        captions = get_captions(video_id)

        output_pdf_filename = f"{video_title}.pdf"
        transcript_pdf_filename = f"txt_{video_title}.pdf"

        with tempfile.TemporaryDirectory() as tmp_dir:
            frames_folder = os.path.join(tmp_dir, "frames")
            os.makedirs(frames_folder)

            timestamps = extract_unique_frames(video_file, frames_folder)
            convert_frames_to_pdf(frames_folder, output_pdf_filename, timestamps)
            create_transcripts_pdf(transcript_pdf_filename, timestamps, captions)

        output_files.append((output_pdf_filename, transcript_pdf_filename))

    return jsonify({"files": output_files}), 200

@app.route('/download/<path:filename>', methods=['GET'])
def download_file(filename):
    return send_from_directory('.', filename, as_attachment=True)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
  
