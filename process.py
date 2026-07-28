
import os
import sys
import subprocess
import asyncio
import static_ffmpeg
from pyrogram import Client

static_ffmpeg.add_paths()

API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

CHAT_ID = int(sys.argv[1])
MSG_ID = int(sys.argv[2])
RESOLUTION = sys.argv[3] if len(sys.argv) > 3 else "360"

async def main():
    async with Client("github_worker", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN) as app:
        status = await app.send_message(CHAT_ID, "⚡ Processing started on GitHub Actions! Downloading class video...")
        
        msg = await app.get_messages(CHAT_ID, MSG_ID)
        if not msg or not (msg.video or msg.document):
            await status.edit_text("❌ No video found in that message.")
            return

        file_path = await app.download_media(msg)
        await status.edit_text(f"⚙️ Compressing video to {RESOLUTION}p...")

        output_file = f"compressed_{RESOLUTION}p_{os.path.basename(file_path)}"

        # FFmpeg compression command tuned for low mobile data
        cmd = [
            "ffmpeg", "-y", "-i", file_path,
            "-vf", f"scale=-2:{RESOLUTION}",
            "-crf", "32",
            "-preset", "ultrafast",
            "-c:a", "aac", "-b:a", "32k",
            output_file
        ]
        subprocess.run(cmd)

        await status.edit_text("📤 Uploading low-data video to Telegram...")

        await app.send_video(
            chat_id=CHAT_ID,
            video=output_file,
            caption=f"✅ Class Video Ready ({RESOLUTION}p)!"
        )

        if os.path.exists(file_path): os.remove(file_path)
        if os.path.exists(output_file): os.remove(output_file)
        await status.delete()

if __name__ == "__main__":
    asyncio.run(main())