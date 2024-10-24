from flask import Flask, request, jsonify, send_file
import os
import tempfile
from fpdf import FPDF
from PIL import Image
import yt_dlp
import cv2
from skimage.metrics import structural_similarity as compare_ssim
from youtube_transcript_api import YouTubeTranscriptApi

app = Flask(__name__)

# Reusing your existing functions
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
        return [(t['start'] * 1000, t['duration'] * 1000, t['text']) for t in transcript]
    except Exception as e:
        print(f"Error fetching captions: {e}")
        return None

def extract_unique_frames(video_file, output_folder, n=3, ssim_threshold=0.8):
    cap = cv2.VideoCapture(video_file)
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    last_frame, saved_frame = None, None
    frame_number, last_saved_frame_number = 0, -1
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

                if similarity < ssim_threshold and frame_number - last_saved_frame_number > fps:
                    frame_path = os.path.join(output_folder, f'frame{frame_number:04d}.png')
                    cv2.imwrite(frame_path, saved_frame)
                    timestamps.append((frame_number, frame_number // fps))

                    saved_frame = frame
                    last_saved_frame_number = frame_number
            else:
                frame_path = os.path.join(output_folder, f'frame{frame_number:04d}.png')
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

    for i, frame_file in enumerate(frame_files):
        frame_path = os.path.join(input_folder, frame_file)
        pdf.add_page()
        pdf.image(frame_path, x=0, y=0, w=pdf.w, h=pdf.h)

    pdf.output(output_file)

def create_transcripts_pdf(output_file, timestamps, captions):
    pdf = FPDF("P")
    pdf.set_auto_page_break(0)
    caption_index = 0
    page_height = pdf.h

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

# Flask route to handle YouTube video processing
@app.route('/process', methods=['POST'])
def process_video():
    data = request.json
    video_url = data.get('url')
    if not video_url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        video_id = get_video_id(video_url)
        if not video_id:
            return jsonify({"error": "Invalid URL"}), 400

        with tempfile.TemporaryDirectory() as tmp_dir:
            video_file = os.path.join(tmp_dir, f"video_{video_id}.mp4")
            download_video(video_url, video_file)

            captions = get_captions(video_id)

            output_pdf_filename = os.path.join(tmp_dir, f"slides_{video_id}.pdf")
            transcript_pdf_filename = os.path.join(tmp_dir, f"transcript_{video_id}.pdf")

            frames_folder = os.path.join(tmp_dir, "frames")
            os.makedirs(frames_folder)

            timestamps = extract_unique_frames(video_file, frames_folder)
            convert_frames_to_pdf(frames_folder, output_pdf_filename, timestamps)
            create_transcripts_pdf(transcript_pdf_filename, timestamps, captions)

            return jsonify({
                "slides_pdf": output_pdf_filename,
                "transcript_pdf": transcript_pdf_filename
            })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Route to download files
@app.route('/download', methods=['GET'])
def download_file():
    filename = request.args.get('filename')
    if filename and os.path.exists(filename):
        return send_file(filename, as_attachment=True)
    return jsonify({"error": "File not found"}), 404

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
    
