from flask import Flask, request, jsonify, send_file
import os
import re
import tempfile
import subprocess
import yt_dlp
from fpdf import FPDF
from youtube_transcript_api import YouTubeTranscriptApi
import cv2
from skimage.metrics import structural_similarity as compare_ssim
from PIL import Image

app = Flask(__name__)

def get_video_id(url):
    # Match YouTube Shorts URLs
    video_id_match = re.search(r"shorts\/(\w+)", url)
    if video_id_match:
        return video_id_match.group(1)

    # Match youtube.be shortened URLs
    video_id_match = re.search(r"youtu\.be\/([\w\-_]+)", url)
    if video_id_match:
        return video_id_match.group(1)

    # Match regular YouTube URLs
    video_id_match = re.search(r"(?:v=|\/|embed\/|\/)([\w\-_]{11})", url)
    if video_id_match:
        return video_id_match.group(1)

    # Match YouTube live stream URLs
    video_id_match = re.search(r"live\/(\w+)", url)
    if video_id_match:
        return video_id_match.group(1)

    return None

def download_video(url, output_file):
    ydl_opts = {
        'outtmpl': output_file,
        'format': 'best',
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

def get_captions(video_id, lang='en'):
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=[lang])
        return [(t['start'], t['duration'], t['text']) for t in transcript]
    except Exception as e:
        print(f"Error fetching captions: {e}")
        return None

def extract_unique_frames(video_file, output_folder, n=3, ssim_threshold=0.8):
    cap = cv2.VideoCapture(video_file)
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    last_frame = None
    timestamps = []

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        if cap.get(cv2.CAP_PROP_POS_FRAMES) % n == 0:
            gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray_frame = cv2.resize(gray_frame, (128, 72))

            if last_frame is not None:
                similarity = compare_ssim(gray_frame, last_frame, data_range=gray_frame.max() - gray_frame.min())
                if similarity < ssim_threshold:
                    frame_path = os.path.join(output_folder, f'frame{len(timestamps):04d}.png')
                    cv2.imwrite(frame_path, frame)
                    timestamps.append(int(cap.get(cv2.CAP_PROP_POS_MSEC)))

            last_frame = gray_frame

    cap.release()
    return timestamps

def convert_frames_to_pdf(input_folder, output_file, timestamps):
    pdf = FPDF("L")
    pdf.set_auto_page_break(0)

    for i, frame_file in enumerate(sorted(os.listdir(input_folder))):
        frame_path = os.path.join(input_folder, frame_file)
        pdf.add_page()
        pdf.image(frame_path, x=0, y=0, w=pdf.w, h=pdf.h)

        timestamp = timestamps[i] / 1000  # Convert milliseconds to seconds
        time_str = f"{int(timestamp // 3600):02d}:{int((timestamp % 3600) // 60):02d}:{int(timestamp % 60):02d}"
        pdf.set_xy(10, 10)
        pdf.set_font("Arial", size=12)
        pdf.cell(0, 10, time_str)

    pdf.output(output_file)

def create_transcripts_pdf(output_file, timestamps, captions):
    pdf = FPDF("P")
    pdf.set_auto_page_break(0)

    caption_index = 0
    for timestamp in timestamps:
        pdf.add_page()
        pdf.set_font("Arial", size=14)
        pdf.cell(0, 10, f"{int(timestamp // 1000 // 3600):02d}:{int((timestamp // 1000 % 3600) // 60):02d}:{int((timestamp // 1000) % 60):02d}")

        if captions:
            transcript = ""
            while caption_index < len(captions) and captions[caption_index][0] * 1000 < timestamp:
                transcript += f"{captions[caption_index][2]}\n"
                caption_index += 1

            pdf.set_font("Arial", size=10)
            pdf.multi_cell(0, 10, transcript)

    pdf.output(output_file)

@app.route('/download', methods=['POST'])
def download():
    data = request.json
    url = data.get('url')

    video_id = get_video_id(url)
    if not video_id:
        return jsonify({"error": "Invalid URL"}), 400

    with tempfile.TemporaryDirectory() as tmp_dir:
        video_file = os.path.join(tmp_dir, f"{video_id}.mp4")
        download_video(url, video_file)
        
        captions = get_captions(video_id)
        timestamps = extract_unique_frames(video_file, tmp_dir)

        slides_pdf_filename = os.path.join(tmp_dir, f"{video_id}_slides.pdf")
        transcript_pdf_filename = os.path.join(tmp_dir, f"{video_id}_transcript.pdf")

        convert_frames_to_pdf(tmp_dir, slides_pdf_filename, timestamps)
        create_transcripts_pdf(transcript_pdf_filename, timestamps, captions)

        return jsonify({
            "slides_pdf": slides_pdf_filename,
            "transcript_pdf": transcript_pdf_filename
        })

@app.route('/download-file', methods=['GET'])
def download_file():
    filename = request.args.get('filename')
    return send_file(filename, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
