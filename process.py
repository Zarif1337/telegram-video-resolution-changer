import os
import sys
import math
import time
import subprocess
import asyncio
import humanize
import static_ffmpeg
from pyrogram import Client
from pyrogram.types import InputMediaPhoto

# Initialize FFmpeg binary path
static_ffmpeg.add_paths()

# Environment Variables
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Command Line Arguments
CHAT_ID = int(sys.argv[1])
MSG_ID = int(sys.argv[2])
MODE = sys.argv[3] if len(sys.argv) > 3 else "video"           # video, audio, phone, screenshot, gif
TARGET_RES = sys.argv[4] if len(sys.argv) > 4 else "360"       # 144, 240, 360, 480, 576, 720, 900, 1080, original, etc.
PRESET = sys.argv[5] if len(sys.argv) > 5 else "balanced"     # max, balanced, hq, lossless
AUDIO_FORMAT = sys.argv[6] if len(sys.argv) > 6 else "mp3_128" # mp3_128, aac, flac, wav, amr, etc.
CODEC = sys.argv[7] if len(sys.argv) > 7 else "libx264"       # libx264, libx265, vp9, h263

CRF_MAP = {
    "max": "32",
    "balanced": "26",
    "hq": "20",
    "lossless": "0"
}

def format_time(seconds):
    return time.strftime("%H:%M:%S", time.gmtime(seconds))

def build_progress_bar(percentage):
    completed = int(percentage // 10)
    return "█" * completed + "░" * (10 - completed)

async def main():
    async with Client("github_worker", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN) as app:
        status_msg = await app.send_message(CHAT_ID, "⚡ **GitHub Actions Engine Started!**\n📥 Downloading source media...")
        last_update_time = [0]

        async def progress_callback(current, total):
            now = time.time()
            if now - last_update_time[0] > 4:
                last_update_time[0] = now
                pct = (current / total) * 100
                bar = build_progress_bar(pct)
                cur_str = humanize.naturalsize(current)
                tot_str = humanize.naturalsize(total)
                try:
                    await status_msg.edit_text(f"📥 **Downloading File...**\n`[{bar}]` {pct:.1f}%\n💾 {cur_str} / {tot_str}")
                except Exception:
                    pass

        msg = await app.get_messages(CHAT_ID, MSG_ID)
        if not msg or not (msg.video or msg.document or msg.audio):
            await status_msg.edit_text("❌ **Error:** Source video or file not found.")
            return

        start_time = time.time()
        file_path = await app.download_media(msg, progress=progress_callback)
        orig_size = os.path.getsize(file_path)

        await status_msg.edit_text("⚙️ **Analyzing Media Streams & Probing Metadata...**")

        # Probe video dimensions and total duration
        src_width, src_height, duration = 1280, 720, 60.0
        try:
            probe_dim = subprocess.check_output([
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", file_path
            ]).decode().strip()
            src_width, src_height = map(int, probe_dim.split("x"))
        except Exception:
            pass

        try:
            probe_dur = subprocess.check_output([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprintwrappers=1:nokey=1", file_path
            ]).decode().strip()
            duration = float(probe_dur)
        except Exception:
            pass

        output_ext = "mp4"
        ffmpeg_args = ["ffmpeg", "-y", "-i", file_path, "-threads", "0"]

        # --- MODE 1: AUDIO EXTRACTION ---
        if MODE == "audio":
            output_ext = AUDIO_FORMAT.split("_")[0]
            output_file = f"extracted_audio.{output_ext}"
            
            if "mp3" in AUDIO_FORMAT:
                bitrate = AUDIO_FORMAT.split("_")[1] if "_" in AUDIO_FORMAT else "128"
                ffmpeg_args.extend(["-vn", "-c:a", "libmp3lame", "-b:a", f"{bitrate}k", output_file])
            elif AUDIO_FORMAT == "flac":
                ffmpeg_args.extend(["-vn", "-c:a", "flac", output_file])
            elif AUDIO_FORMAT == "wav":
                ffmpeg_args.extend(["-vn", "-c:a", "pcm_s16le", output_file])
            elif AUDIO_FORMAT in ["m4a", "aac"]:
                ffmpeg_args.extend(["-vn", "-c:a", "aac", "-b:a", "192k", output_file])
            elif AUDIO_FORMAT == "ogg":
                ffmpeg_args.extend(["-vn", "-c:a", "libvorbis", "-q:a", "5", output_file])
            elif AUDIO_FORMAT == "amr":
                output_ext = "amr"
                output_file = "audio.amr"
                ffmpeg_args.extend(["-vn", "-c:a", "libopencore_amrnb", "-ar", "8000", "-ac", "1", "-b:a", "12.2k", output_file])

        # --- MODE 2: LEGACY FEATURE PHONE MODE (STRICT 3GP) ---
        elif MODE == "phone":
            output_ext = "3gp"
            output_file = "phone_video.3gp"
            scale_filter = "scale=176:144:force_original_aspect_ratio=decrease,pad=176:144:(ow-iw)/2:(oh-ih)/2"

            ffmpeg_args.extend([
                "-vf", scale_filter,
                "-c:v", "h263",
                "-pix_fmt", "yuv420p",
                "-r", "15",
                "-b:v", "128k",
                "-c:a", "libopencore_amrnb",
                "-ar", "8000",
                "-ac", "1",
                "-b:a", "12.2k",
                "-f", "3gp",
                output_file
            ])

        # --- MODE 3: 10 EVENLY SPACED SCREENSHOTS (IMAGE GALLERY) ---
        elif MODE == "screenshot":
            await status_msg.edit_text("📸 **Extracting 10 Evenly Spaced Screenshots...**")
            screenshots = []
            
            for i in range(1, 11):
                ts = duration * (i / 11.0)
                img_file = f"screenshot_{i}.jpg"
                ff_cmd = [
                    "ffmpeg", "-y", "-ss", str(ts), "-i", file_path,
                    "-vframes", "1", "-q:v", "2", img_file
                ]
                subprocess.run(ff_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if os.path.exists(img_file):
                    screenshots.append(img_file)

            if screenshots:
                await status_msg.edit_text("📤 **Uploading 10 Screenshots Album to Telegram...**")
                media_group = [
                    InputMediaPhoto(
                        img, 
                        caption=f"📸 **Video Screenshots Overview (10 Photos)**\n⏱ Duration: {format_time(duration)}" if idx == 0 else ""
                    ) for idx, img in enumerate(screenshots)
                ]
                await app.send_media_group(CHAT_ID, media=media_group)
                
                for img in screenshots:
                    if os.path.exists(img): os.remove(img)
                if os.path.exists(file_path): os.remove(file_path)
                await status_msg.delete()
                return
            else:
                await status_msg.edit_text("❌ **Failed to extract screenshots.**")
                return

        # --- MODE 4: GIF CREATION ---
        elif MODE == "gif":
            output_ext = "gif"
            output_file = "preview.gif"
            ffmpeg_args.extend([
                "-ss", "00:00:01", "-t", "5",
                "-vf", "scale=320:-1:flags=lanczos,fps=10", output_file
            ])

        # --- MODE 5: STANDARD / ADVANCED VIDEO (PRESERVES MULTI-AUDIO & SUBTITLES) ---
        else:
            output_file = f"converted_{TARGET_RES}p.mp4"
            crf = CRF_MAP.get(PRESET, "26")

            if TARGET_RES == "original":
                vf_chain = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
            else:
                target_h = int(TARGET_RES)
                if target_h > src_height:
                    target_h = src_height
                vf_chain = f"scale=-2:{target_h}"

            ffmpeg_args.extend([
                "-map", "0:v:0?",
                "-map", "0:a?",
                "-map", "0:s?",
                "-vf", vf_chain,
                "-c:v", CODEC,
                "-crf", crf,
                "-preset", "ultrafast",
                "-c:a", "aac", "-b:a", "96k",
                "-c:s", "copy",
                "-movflags", "+faststart",
                output_file
            ])

        # Execute FFmpeg
        await status_msg.edit_text("⚙️ **Encoding Media with FFmpeg...**\n*(Multi-audio, Subtitles & Multi-threading Active)*")
        proc = subprocess.run(ffmpeg_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if proc.returncode != 0:
            err_log = proc.stderr.decode()[-500:]
            await status_msg.edit_text(f"❌ **FFmpeg Encoding Failed:**\n```\n{err_log}\n```")
            return

        final_size = os.path.getsize(output_file)
        saved_bytes = orig_size - final_size
        saved_pct = (saved_bytes / orig_size) * 100 if orig_size > 0 else 0
        elapsed = time.time() - start_time

        stats_text = (
            f"✅ **Conversion Completed in {format_time(elapsed)}!**\n\n"
            f"📊 **Statistics:**\n"
            f"• **Original Size:** {humanize.naturalsize(orig_size)}\n"
            f"• **Final Size:** {humanize.naturalsize(final_size)}\n"
            f"• **Space Saved:** {humanize.naturalsize(abs(saved_bytes))} ({saved_pct:.1f}%)\n"
            f"• **Output Format:** `{output_ext.upper()}` | `{TARGET_RES}`"
        )

        await status_msg.edit_text("📤 **Uploading processed media to Telegram...**")

        if MODE == "audio":
            await app.send_audio(CHAT_ID, audio=output_file, caption=stats_text)
        elif MODE == "gif":
            await app.send_animation(CHAT_ID, animation=output_file, caption=stats_text)
        else:
            await app.send_video(CHAT_ID, video=output_file, caption=stats_text, supports_streaming=True)

        if os.path.exists(file_path): os.remove(file_path)
        if os.path.exists(output_file): os.remove(output_file)
        await status_msg.delete()

if __name__ == "__main__":
    asyncio.run(main())
            
