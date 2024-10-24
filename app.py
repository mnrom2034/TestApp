from flask import Flask, request, jsonify, send_file, render_template
import os
import tempfile
import re
from fpdf import FPDF
from youtube_transcript_api import YouTubeTranscriptApi
import yt_dlp
import cv2
from skimage.metrics import structural_similarity as compare_ssim
from PIL import Image

app = Flask(__name__)

# Helper functions for video download and processing
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
    video_id_match = re.search(r"shorts\/(\w+)", url) or \
                     re.search(r"youtu\.be\/([\w\-_]+)(\?.*)?", url) or \
                     re.search(r"v=([\w\-_]+)", url) or \
                     re.search(r"live\/(\w+)", url)
    return video_id_match.group(1) if video_id_match else None

def get_captions(video_id, lang='en'):
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=[lang])
        captions = [(t['start'] * 1000, t['duration'] * 1000, t['text']) for t in transcript]
        return captions
    except Exception as e:
        print(f"Error fetching captions: {e}")
        return None

def extract_unique_frames(video_file, output_folder, n=3, ssim_threshold=0.8):
    cap = cv2.VideoCapture(video_file)
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    last_frame = None
    saved_frame = None
    frame_number = 0
    last_saved_frame_number = -1
    timestamps = []

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        if frame_number % n == 0:
            gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray_frame = cv2.resize(gray_frame, (128, 72))

            if last_frame is not None:
                similarity = compare_ssim(gray_frame, last_frame, data_range=gray_frame.max() - gray_frame.min())

                if similarity < ssim_threshold:
                    if saved_frame is not None and frame_number - last_saved_frame_number > fps:
                        frame_path = os.path.join(output_folder, f'frame{frame_number:04d}_{frame_number // fps}.png')
                        cv2.imwrite(frame_path, saved_frame)
                        timestamps.append((frame_number, frame_number // fps))

                    saved_frame = frame
                    last_saved_frame_number = frame_number
                else:
                    saved_frame = frame

            else:
                frame_path = os.path.join(output_folder, f'frame{frame_number:04d}_{frame_number // fps}.png')
                cv2.imwrite(frame_path, frame)
                timestamps.append((frame_number, frame_number // fps))
                last_saved_frame_number = frame_number

            last_frame = gray_frame

        frame_number += 1

    cap.release()
    return timestamps

def convert_frames_to_pdf(input_folder, output_file, timestamps):
    frame_files = sorted(os.listdir(input_folder), key=lambda x: int(x.split('_')[0].split('frame')[-1]))
    pdf = FPDF("L")
    pdf.set_auto_page_break(0)

    for i, (frame_file, (frame_number, timestamp_seconds)) in enumerate(zip(frame_files, timestamps)):
        frame_path = os.path.join(input_folder, frame_file)
        image = Image.open(frame_path)
        pdf.add_page()
        pdf.image(frame_path, x=0, y=0, w=pdf.w, h=pdf.h)

        timestamp = f"{timestamp_seconds // 3600:02d}:{(timestamp_seconds % 3600) // 60:02d}:{timestamp_seconds % 60:02d}"

        x, y, width, height = 5, 5, 60, 15
        region = image.crop((x, y, x + width, y + height)).convert("L")
        mean_pixel_value = region.resize((1, 1)).getpixel((0, 0))
        if mean_pixel_value < 64:
            pdf.set_text_color(255, 255, 255)
        else:
            pdf.set_text_color(0, 0, 0)

        pdf.set_xy(x, y)
        pdf.set_font("Arial", size=12)
        pdf.cell(0, 0, timestamp)

    pdf.output(output_file)

def create_transcripts_pdf(output_file, timestamps, captions):
    pdf = FPDF("P")
    pdf.set_auto_page_break(0)
    page_height = pdf.h

    caption_index = 0
    for i, (frame_number, timestamp_seconds) in enumerate(timestamps):
        pdf.add_page()

        timestamp = f"{timestamp_seconds // 3600:02d}:{(timestamp_seconds % 3600) // 60:02d}:{timestamp_seconds % 60:02d}"
        pdf.set_text_color(0, 0, 0)
        pdf.set_xy(10, 10)
        pdf.set_font("Arial", size=14)
        pdf.cell(0, 0, timestamp)

        if captions and caption_index < len(captions):
            transcript = ""
            start_time = 0 if i == 0 else timestamps[i - 1][1]
            end_time = timestamp_seconds

            while caption_index < len(captions) and start_time * 1000 <= captions[caption_index][0] < end_time * 1000:
                transcript += f"{captions[caption_index][2]}\n"
                caption_index += 1

            pdf.set_text_color(0, 0, 0)
            pdf.set_xy(10, 25)
            pdf.set_font("Arial", size=10)
            lines = transcript.split("\n")
            for line in lines:
                if pdf.get_y() + 10 > page_height:
                    pdf.add_page()
                    pdf.set_xy(10, 10)
                pdf.cell(0, 10, line)
                pdf.ln()

    pdf.output(output_file)

# API Route for processing video and returning PDF files
@app.route('/process', methods=['POST'])
def process_video():
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400

    try:
        video_id = get_video_id(url)
        video_title = "video"  # Simplified for this example
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

            return jsonify({
                'slide_pdf': f'/download/{output_pdf_filename}',
                'transcript_pdf': f'/download/{transcript_pdf_filename}'
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Route to serve the static HTML page
@app.route('/')
def index():
    return render_template('index.html')

# Route to handle file downloads
@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    return send_file(filename, as_attachment=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
