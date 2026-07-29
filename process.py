import os
import sys
import math
import time
import subprocess
import asyncio
import humanize
import static_ffmpeg
from pyrogram import Client

# Initialize FFmpeg binary path
static_ffmpeg.add_paths()

# Parse Environment Variables
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Command Line Arguments from Cloudflare Dispatch
CHAT_ID = int(sys.argv[1])
MSG_ID = int(sys.argv[2])
MODE = sys.argv[3] if len(sys.argv) > 3 else "video"           # video, audio, phone, screenshot, gif
TARGET_RES = sys.argv[4] if len(sys.argv) > 4 else "360"       # 144, 240, 360, 480, 576, 720, 900, 1080, 1440, 2160, original, 176x144, etc.
PRESET = sys.argv[5] if len(sys.argv) > 5 else "balanced"     # max, balanced, hq, lossless
AUDIO_FORMAT = sys.argv[6] if len(sys.argv) > 6 else "mp3_128" # mp3_128, aac, flac, wav, amr, etc.
CODEC = sys.argv[7] if len(sys.argv) > 7 else "libx264"       # libx264, libx265, vp9, h263

# Preset CRF Mapping (H.264)
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
            if now - last_update_time[0] > 4:  # Throttle updates to avoid Telegram rate limits
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

        # Step 1: Download Media
        start_time = time.time()
        file_path = await app.download_media(msg, progress=progress_callback)
        orig_size = os.path.getsize(file_path)

        await status_msg.edit_text("⚙️ **Analyzing Video Streams & Building FFmpeg Pipeline...**")

        # Probe video dimensions using ffprobe
        probe_cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", file_path
        ]
        try:
            probe_out = subprocess.check_output(probe_cmd).decode().strip()
            src_width, src_height = map(int, probe_out.split("x"))
        except Exception:
            src_width, src_height = 1280, 720  # Fallback assumption

        # Smart Processing: Prevent Upscaling
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
            elif AUDIO_FORMAT == "m4a" or AUDIO_FORMAT == "aac":
                ffmpeg_args.extend(["-vn", "-c:a", "aac", "-b:a", "192k", output_file])
            elif AUDIO_FORMAT == "ogg":
                ffmpeg_args.extend(["-vn", "-c:a", "libvorbis", "-q:a", "5", output_file])
            elif AUDIO_FORMAT == "amr":
                output_ext = "amr"
                output_file = "audio.amr"
                ffmpeg_args.extend(["-vn", "-c:a", "libopencore_amrnb", "-ar", "8000", "-ac", "1", "-b:a", "12.2k", output_file])

        # --- MODE 2: FEATURE PHONE MODE (3GP / Low Profile) ---
        elif MODE == "phone":
            output_ext = "3gp" if "3gp" in TARGET_RES else "mp4"
            output_file = f"phone_video.{output_ext}"

            # Low res targets like 176x144, 128x96, 240x320, 320x240
            if "x" in TARGET_RES:
                res_w, res_h = TARGET_RES.split("x")
                scale_filter = f"scale={res_w}:{res_h}:force_original_aspect_ratio=decrease,pad={res_w}:{res_h}:(ow-iw)/2:(oh-ih)/2"
            else:
                scale_filter = "scale=176:144"

            if output_ext == "3gp":
                ffmpeg_args.extend([
                    "-vf", scale_filter, "-c:v", "h263", "-r", "15", "-b:v", "150k",
                    "-c:a", "libopencore_amrnb", "-ar", "8000", "-ac", "1", "-b:a", "12.2k", output_file
                ])
            else:
                ffmpeg_args.extend([
                    "-vf", scale_filter, "-c:v", "libx264", "-profile:v", "baseline", "-level", "3.0",
                    "-r", "20", "-b:v", "300k", "-c:a", "aac", "-b:a", "48k", "-ar", "22050", output_file
                ])

        # --- MODE 3: SCREENSHOT OR GIF ---
        elif MODE == "screenshot":
            output_ext = "jpg"
            output_file = "screenshot.jpg"
            ffmpeg_args.extend(["-ss", "00:00:02", "-vframes", "1", "-q:v", "2", output_file])

        elif MODE == "gif":
            output_ext = "gif"
            output_file = "preview.gif"
            ffmpeg_args.extend([
                "-ss", "00:00:01", "-t", "5",
                "-vf", "scale=320:-1:flags=lanczos,fps=10", output_file
            ])

        # --- MODE 4: STANDARD / ADVANCED VIDEO CONVERSION ---
        else:
            output_file = f"converted_{TARGET_RES}p.mp4"
            crf = CRF_MAP.get(PRESET, "26")

            if TARGET_RES == "original":
                vf_chain = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
            else:
                target_h = int(TARGET_RES)
                # Smart Check: Never upscale if source height is smaller
                if target_h > src_height:
                    target_h = src_height
                vf_chain = f"scale=-2:{target_h}"

            ffmpeg_args.extend([
                "-vf", vf_chain,
                "-c:v", CODEC,
                "-crf", crf,
                "-preset", "ultrafast",
                "-c:a", "aac", "-b:a", "96k",
                "-movflags", "+faststart",
                output_file
            ])

        # Execute FFmpeg
        await status_msg.edit_text("⚙️ **Encoding media with FFmpeg...**\n*(Multi-threaded processing active)*")
        proc = subprocess.run(ffmpeg_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if proc.returncode != 0:
            err_log = proc.stderr.decode()[-500:]
            await status_msg.edit_text(f"❌ **FFmpeg Encoding Failed:**\n```\n{err_log}\n```")
            return

        # Post-Conversion Analytics
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

        # Upload based on file type
        if MODE == "audio":
            await app.send_audio(CHAT_ID, audio=output_file, caption=stats_text)
        elif MODE == "screenshot":
            await app.send_photo(CHAT_ID, photo=output_file, caption=stats_text)
        elif MODE == "gif":
            await app.send_animation(CHAT_ID, animation=output_file, caption=stats_text)
        else:
            await app.send_video(CHAT_ID, video=output_file, caption=stats_text, supports_streaming=True)

        # Cleanup temporary local storage
        if os.path.exists(file_path): os.remove(file_path)
        if os.path.exists(output_file): os.remove(output_file)
        await status_msg.delete()

if __name__ == "__main__":
    asyncio.run(main())
