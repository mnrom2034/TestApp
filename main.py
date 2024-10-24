from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import tempfile
import yt_dlp
import cv2
from skimage.metrics import structural_similarity as compare_ssim
from youtube_transcript_api import YouTubeTranscriptApi
from fpdf import FPDF
from PIL import Image

app = FastAPI()

class URLRequest(BaseModel):
    url: str

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
    video_id_match = re.search(r"v=([\w\-_]+)", url)
    if video_id_match:
        return video_id_match.group(1)
    return None

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
    last_frame = None
    timestamps = []
    frame_number = 0

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
                    frame_path = os.path.join(output_folder, f'frame{frame_number:04d}.png')
                    cv2.imwrite(frame_path, frame)
                    timestamps.append((frame_number, frame_number // 30))
            last_frame = gray_frame

        frame_number += 1
    cap.release()
    return timestamps

def convert_frames_to_pdf(input_folder, output_file, timestamps):
    frame_files = sorted(os.listdir(input_folder), key=lambda x: int(x.split('_')[0].split('frame')[-1]))
    pdf = FPDF("L")
    pdf.set_auto_page_break(0)

    for frame_file, (frame_number, timestamp_seconds) in zip(frame_files, timestamps):
        frame_path = os.path.join(input_folder, frame_file)
        pdf.add_page()
        pdf.image(frame_path, x=0, y=0, w=pdf.w, h=pdf.h)
    pdf.output(output_file)

def create_transcripts_pdf(output_file, timestamps, captions):
    pdf = FPDF("P")
    pdf.set_auto_page_break(0)

    caption_index = 0
    for frame_number, timestamp_seconds in timestamps:
        pdf.add_page()

        if captions and caption_index < len(captions):
            transcript = ""
            while caption_index < len(captions) and captions[caption_index][0] < timestamp_seconds * 1000:
                transcript += f"{captions[caption_index][2]}\n"
                caption_index += 1

            pdf.set_xy(10, 25)
            pdf.set_font("Arial", size=10)
            pdf.multi_cell(0, 10, transcript)
    pdf.output(output_file)

@app.post("/process_video")
def process_video(request: URLRequest):
    url = request.url
    video_id = get_video_id(url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    video_file = f"video_{video_id}.mp4"
    output_pdf_filename = f"{video_id}.pdf"
    transcript_pdf_filename = f"transcript_{video_id}.pdf"

    download_video(url, video_file)
    captions = get_captions(video_id)

    with tempfile.TemporaryDirectory() as tmp_dir:
        frames_folder = os.path.join(tmp_dir, "frames")
        os.makedirs(frames_folder)

        timestamps = extract_unique_frames(video_file, frames_folder)
        convert_frames_to_pdf(frames_folder, output_pdf_filename, timestamps)
        create_transcripts_pdf(transcript_pdf_filename, timestamps, captions)

    return {
        "slides_pdf": output_pdf_filename,
        "transcripts_pdf": transcript_pdf_filename
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
    
