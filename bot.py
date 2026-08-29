import asyncio
import json
import os
import uuid
from pathlib import Path

from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    Message,
    WebAppData,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import BOT_TOKEN, WEBAPP_URL, MAX_FILE_SIZE
from processor import process_image, process_video


BASE_DIR = Path(__file__).resolve().parent

DOWNLOADS = BASE_DIR / "downloads"
OUTPUTS = BASE_DIR / "outputs"
WEB_DIR = BASE_DIR / "web"

DOWNLOADS.mkdir(exist_ok=True)
OUTPUTS.mkdir(exist_ok=True)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

pending = {}


def cleanup_user(user_id):
    data = pending.pop(user_id, None)

    if not data:
        return

    path = data.get("path")

    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass


def make_selector_url(file_key):
    return f"{WEBAPP_URL}/?file_id={file_key}"


def selection_keyboard(file_key):
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="🖱️ Select watermark",
            web_app=WebAppInfo(
                url=make_selector_url(file_key)
            ),
        )
    )

    return builder.as_markup()


@dp.message(CommandStart())
async def start(message: Message):

    await message.answer(
        "👋 Watermark Remover\n\n"
        "Send an image or video containing your own watermark.\n\n"
        "Then select the watermark area."
    )


@dp.message(F.photo)
async def receive_photo(message: Message):

    user_id = message.from_user.id

    photo = message.photo[-1]

    if (
        photo.file_size
        and photo.file_size > MAX_FILE_SIZE
    ):
        await message.answer(
            "❌ File exceeds the configured size limit."
        )
        return

    cleanup_user(user_id)

    file = await bot.get_file(
        photo.file_id
    )

    file_key = uuid.uuid4().hex

    path = DOWNLOADS / f"{file_key}.jpg"

    await bot.download_file(
        file.file_path,
        destination=path
    )

    pending[user_id] = {
        "path": str(path),
        "type": "image",
        "file_key": file_key,
    }

    await message.answer(
        "✅ Image received.\n\n"
        "Tap the button and draw a rectangle "
        "around your watermark.",
        reply_markup=selection_keyboard(
            file_key
        ),
    )


@dp.message(F.video)
async def receive_video(message: Message):

    user_id = message.from_user.id

    if (
        message.video.file_size
        and message.video.file_size > MAX_FILE_SIZE
    ):
        await message.answer(
            "❌ File exceeds the configured size limit."
        )
        return

    cleanup_user(user_id)

    file = await bot.get_file(
        message.video.file_id
    )

    file_key = uuid.uuid4().hex

    path = DOWNLOADS / f"{file_key}.mp4"

    await bot.download_file(
        file.file_path,
        destination=path
    )

    pending[user_id] = {
        "path": str(path),
        "type": "video",
        "file_key": file_key,
    }

    await message.answer(
        "✅ Video received.\n\n"
        "Tap the button and draw a rectangle "
        "around your watermark.\n\n"
        "That same area will be processed "
        "on every frame.",
        reply_markup=selection_keyboard(
            file_key
        ),
    )


@dp.message(F.web_app_data)
async def receive_selection(message: Message):

    user_id = message.from_user.id

    try:
        data = json.loads(
            message.web_app_data.data
        )

        file_key = data["file_id"]

        x = int(data["x"])
        y = int(data["y"])
        width = int(data["width"])
        height = int(data["height"])

    except Exception as exc:

        print("Invalid web app data:", exc)

        await message.answer(
            "❌ Invalid selection."
        )
        return

    user_data = pending.get(user_id)

    if not user_data:

        await message.answer(
            "❌ Upload expired. "
            "Please upload the file again."
        )
        return

    if user_data["file_key"] != file_key:

        await message.answer(
            "❌ Invalid file selection."
        )
        return

    path = user_data["path"]
    media_type = user_data["type"]

    await message.answer(
        "⏳ Processing your file...\n\n"
        "This may take a while for videos."
    )

    output_id = uuid.uuid4().hex

    try:

        if media_type == "image":

            output_path = (
                OUTPUTS /
                f"{output_id}.jpg"
            )

            await asyncio.to_thread(
                process_image,
                path,
                str(output_path),
                x,
                y,
                width,
                height,
            )

            with output_path.open("rb") as f:

                await message.answer_document(
                    f,
                    caption=(
                        "✅ Done!\n\n"
                        "Your cleaned image is "
                        "ready to download."
                    ),
                )

            output_path.unlink(
                missing_ok=True
            )

        else:

            output_path = (
                OUTPUTS /
                f"{output_id}.mp4"
            )

            await asyncio.to_thread(
                process_video,
                path,
                str(output_path),
                x,
                y,
                width,
                height,
            )

            with output_path.open("rb") as f:

                await message.answer_document(
                    f,
                    caption=(
                        "✅ Done!\n\n"
                        "Your cleaned video is "
                        "ready to download."
                    ),
                )

            output_path.unlink(
                missing_ok=True
            )

    except Exception as exc:

        print(
            "Processing error:",
            repr(exc)
        )

        await message.answer(
            "❌ Processing failed.\n\n"
            "Try selecting a slightly larger "
            "area around the watermark."
        )

    finally:

        cleanup_user(user_id)


async def index(request):

    return web.FileResponse(
        WEB_DIR / "index.html"
    )


async def preview(request):

    file_key = request.match_info["file_key"]

    path_jpg = (
        DOWNLOADS /
        f"{file_key}.jpg"
    )

    path_mp4 = (
        DOWNLOADS /
        f"{file_key}.mp4"
    )

    if path_jpg.exists():

        return web.FileResponse(
            path_jpg
        )

    if path_mp4.exists():

        # For video, browser needs a frame.
        # We generate a temporary JPEG preview.

        import cv2

        cap = cv2.VideoCapture(
            str(path_mp4)
        )

        success, frame = cap.read()

        cap.release()

        if not success:

            return web.Response(
                status=404,
                text="Preview unavailable"
            )

        preview_path = (
            DOWNLOADS /
            f"{file_key}_preview.jpg"
        )

        cv2.imwrite(
            str(preview_path),
            frame
        )

        return web.FileResponse(
            preview_path
        )

    return web.Response(
        status=404,
        text="File not found"
    )


async def start_web_server():

    app = web.Application()

    app.router.add_get(
        "/",
        index
    )

    app.router.add_get(
        "/preview/{file_key}",
        preview
    )

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        8080
    )

    await site.start()

    print(
        "Web server running on port 8080"
    )


async def cleanup_loop():

    while True:

        await asyncio.sleep(
            60 * 60
        )

        for folder in [
            DOWNLOADS,
            OUTPUTS,
        ]:

            for file in folder.iterdir():

                try:

                    if file.is_file():
                        file.unlink()

                except Exception:
                    pass


async def main():

    await start_web_server()

    asyncio.create_task(
        cleanup_loop()
    )

    print(
        "Telegram watermark bot started."
    )

    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())
