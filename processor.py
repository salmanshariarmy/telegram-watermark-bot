import cv2
import numpy as np
import subprocess
import tempfile
import os


def make_mask(frame, x, y, width, height):
    """
    Create a rectangular mask.

    OpenCV coordinates:
        x = horizontal
        y = vertical
    """

    h, w = frame.shape[:2]

    x1 = max(0, min(x, w))
    y1 = max(0, min(y, h))

    x2 = max(0, min(x + width, w))
    y2 = max(0, min(y + height, h))

    if x2 <= x1 or y2 <= y1:
        raise ValueError("Invalid watermark selection")

    mask = np.zeros((h, w), dtype=np.uint8)

    mask[y1:y2, x1:x2] = 255

    return mask


def remove_watermark(frame, x, y, width, height):
    mask = make_mask(frame, x, y, width, height)

    # Telea inpainting.
    #
    # Increase radius for larger watermarks.
    result = cv2.inpaint(
        frame,
        mask,
        5,
        cv2.INPAINT_TELEA,
    )

    return result


def process_image(
    input_path,
    output_path,
    x,
    y,
    width,
    height,
):
    image = cv2.imread(input_path)

    if image is None:
        raise RuntimeError("Could not read image")

    result = remove_watermark(
        image,
        x,
        y,
        width,
        height,
    )

    success = cv2.imwrite(
        output_path,
        result,
        [
            cv2.IMWRITE_JPEG_QUALITY,
            95,
        ],
    )

    if not success:
        raise RuntimeError("Could not save output image")


def process_video(
    input_path,
    output_path,
    x,
    y,
    width,
    height,
):
    """
    Process video frame-by-frame.

    Audio is copied from the original video when possible.
    """

    cap = cv2.VideoCapture(input_path)

    if not cap.isOpened():
        raise RuntimeError("Could not open video")

    fps = cap.get(cv2.CAP_PROP_FPS)

    if not fps or fps <= 0:
        fps = 30

    frame_width = int(
        cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    )

    frame_height = int(
        cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    )

    frame_count = int(
        cap.get(cv2.CAP_PROP_FRAME_COUNT)
    )

    # Temporary video without audio.
    temp_video = output_path + ".silent.mp4"

    fourcc = cv2.VideoWriter_fourcc(
        *"mp4v"
    )

    writer = cv2.VideoWriter(
        temp_video,
        fourcc,
        fps,
        (frame_width, frame_height),
    )

    if not writer.isOpened():
        cap.release()
        raise RuntimeError("Could not create video")

    processed = 0

    while True:
        ret, frame = cap.read()

        if not ret:
            break

        cleaned = remove_watermark(
            frame,
            x,
            y,
            width,
            height,
        )

        writer.write(cleaned)

        processed += 1

    cap.release()
    writer.release()

    if processed == 0:
        raise RuntimeError("Video contains no frames")

    # Re-encode using FFmpeg and copy original audio.
    command = [
        "ffmpeg",
        "-y",
        "-i",
        temp_video,
        "-i",
        input_path,
        "-map",
        "0:v:0",
        "-map",
        "1:a?",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        output_path,
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        os.remove(temp_video)
    except OSError:
        pass

    if result.returncode != 0:
        raise RuntimeError(
            "FFmpeg failed:\n" + result.stderr[-2000:]
        )
