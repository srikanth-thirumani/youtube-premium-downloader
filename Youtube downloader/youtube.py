import os
import re
import shutil
import sqlite3
import json
import csv
import datetime
import time
import traceback
import subprocess
from datetime import datetime as dt, timedelta
from urllib.parse import urlparse, parse_qs
import yt_dlp
import schedule
import threading

# Thread-safe download status tracking (for internal use)
internal_download_status = {}
internal_download_lock = threading.Lock()

class YouTubeDownloader:
    def __init__(self):
        self.downloads_path = "downloads"
        self.config_path = "."
        self.db_path = os.path.join(self.config_path, "downloads.db")
        self.config_file = os.path.join(self.config_path, "config.json")
        self.queue_file = os.path.join(self.config_path, "queue.json")
        self.download_queue = self.load_queue()
        self.progress_hooks = [] # Store hooks for dynamic progress updates

        # Default config
        default_config = {
            "default_quality": "best",
            "default_format": "mp4",
            "auto_organize": True,
            "download_subtitles": False,
            "download_thumbnails": True,
            "max_file_size_mb": 1000,
            "custom_naming_pattern": "%(title)s.%(ext)s",
            "preferred_audio_quality": "192"
        }

        # Load or create config
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                self.config = {**default_config, **json.load(f)}
        else:
            self.config = default_config
            self.save_config()

        os.makedirs(self.downloads_path, exist_ok=True)
        self.init_database()

    def init_database(self):
        """Initialize SQLite database for download history and playlists"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY,
                video_id TEXT UNIQUE,
                title TEXT,
                uploader TEXT,
                duration INTEGER,
                file_path TEXT,
                file_size INTEGER,
                format_type TEXT,
                quality TEXT,
                download_date TIMESTAMP,
                tags TEXT,
                thumbnail_path TEXT,
                subtitle_path TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id TEXT,
                playlist_title TEXT,
                video_id TEXT,
                download_date TIMESTAMP,
                FOREIGN KEY (video_id) REFERENCES downloads (video_id)
            )
        ''')
        conn.commit()
        conn.close()
    def sanitize_filename(self, filename):
        """Remove invalid characters from filename"""
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        if len(filename) > 150:
            filename = filename[:150]
        return filename
    def cleanup_old_files(self, max_age_hours=24):
        """Remove files older than specified hours"""
        try:
            now = dt.now()
            max_age = timedelta(hours=max_age_hours)
            removed_count = 0
            
            for filename in os.listdir(self.downloads_path):
                filepath = os.path.join(self.downloads_path, filename)
                if os.path.isfile(filepath):
                    file_time = dt.fromtimestamp(os.path.getctime(filepath))
                    if now - file_time > max_age:
                        os.remove(filepath)
                        print(f"🗑️ Removed old file: {filename}")
                        removed_count += 1
            
            if removed_count > 0:
                print(f"✅ Cleaned up {removed_count} old files.")
            else:
                print("ℹ️ No old files to clean up.")
                
        except Exception as e:
            print(f"❌ Error in cleanup: {e}")
    def get_video_id(self, url):
        """Extract video ID from YouTube URL - improved version"""
        try:
            youtube_domains = ['youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be']
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.lower()
            
            if any(y in domain for y in youtube_domains):
                if 'youtu.be' in domain:
                    return parsed_url.path[1:] if parsed_url.path else None
                else:
                    query_params = parse_qs(parsed_url.query)
                    return query_params.get('v', [None])[0]
            return None
        except Exception as e:
            print(f"❌ Error extracting video ID: {e}")
            return None
    def save_config(self):
        """Save user configuration to file"""
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)

    def load_queue(self):
        """Load download queue from JSON file"""
        try:
            with open(self.queue_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return []

    def save_queue(self):
        """Save download queue to JSON file"""
        with open(self.queue_file, 'w') as f:
            json.dump(self.download_queue, f, indent=2)

    def check_ffmpeg(self):
        """Check if FFmpeg is available"""
        return shutil.which("ffmpeg") is not None

    def is_youtube_url(self, text):
        """Check if input is a valid YouTube URL"""
        patterns = [
            r'(?:https?://)?(?:www\.)?(?:youtube\.com|youtu\.be)',
            r'(?:https?://)?(?:m\.)?youtube\.com',
            r'(?:https?://)?youtu\.be'
        ]
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)
    def wait_for_file(self, filepath, timeout=30):
        """Wait for file to be fully written"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                return True
            time.sleep(0.5)
        return False
    def calculate_file_size(self, info, quality):
        """Estimate file size based on duration and quality"""
        duration = info.get('duration', 0)
        bitrate_map = {
            '144p': 0.1, '240p': 0.2, '360p': 0.5, '480p': 1.0,
            '720p': 2.0, '1080p': 4.0, '1440p': 6.0, '2160p': 12.0,
            'best': 5.0, 'highest': 8.0
        }
        kbps = bitrate_map.get(quality, 2.0)
        return int(duration * kbps * 1024 * 1024 / 8)
    def extract_video_id(self, url):
        """Extract video ID from YouTube URL"""
        patterns = [
            r'(?:v=)([a-zA-Z0-9_-]{11})',
            r'(?:youtu\.be/)([a-zA-Z0-9_-]{11})',
            r'(?:embed/)([a-zA-Z0-9_-]{11})'
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
    def get_video_info(self, url):
        """Get video information without downloading - improved version"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                video_info = {
                    'title': info.get('title', 'Unknown Title'),
                    'thumbnail': info.get('thumbnail', ''),
                    'duration': info.get('duration', 0),
                    'views': info.get('view_count', 0),
                    'author': info.get('uploader', 'Unknown Author'),
                    'video_id': info.get('id', ''),
                    'upload_date': info.get('upload_date', ''),
                    'description': info.get('description', ''),
                    'tags': info.get('tags', [])
                }
                return video_info
        except Exception as e:
            print(f"❌ Error getting video info: {e}")
            return {'error': str(e)}
    def calculate_file_size(self, info, quality):
        """Estimate file size based on duration and quality"""
        duration = info.get('duration', 0)
        bitrate_map = {
            '144': 0.1,
            '240': 0.2,
            '360': 0.5,
            '480': 1.0,
            '720': 2.0,
            '1080': 4.0,
            'best': 5.0
        }
        kbps = bitrate_map.get(quality, 2.0)
        return int(duration * kbps * 1024 * 1024 / 8)

    def embed_metadata(self, file_path, info):
        """Embed metadata using FFmpeg"""
        if not self.check_ffmpeg():
            return
        temp_file = file_path + ".temp"
        cmd = [
            'ffmpeg', '-i', file_path,
            '-metadata', f'title={info.get("title", "")}',
            '-metadata', f'artist={info.get("uploader", "")}',
            '-metadata', f'comment={info.get("description", "")[:500]}',
            '-codec', 'copy',
            '-y', temp_file
        ]
        try:
            result = subprocess.call([str(arg) for arg in cmd])
            if result == 0 and os.path.exists(temp_file):
                shutil.move(temp_file, file_path)
                print("✅ Metadata embedded successfully.")
        except Exception as e:
            print(f"❌ Could not embed metadata: {e}")

    def save_to_database(self, info, file_path, format_type, quality, tags=None, thumbnail_path=None, subtitle_path=None):
        """Save download info to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        video_id = info.get('id')
        cursor.execute('''
            INSERT OR IGNORE INTO downloads 
            (video_id, title, uploader, duration, file_path, file_size, format_type, quality, download_date, tags, thumbnail_path, subtitle_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            video_id,
            info.get('title'),
            info.get('uploader'),
            info.get('duration'),
            file_path,
            os.path.getsize(file_path) if os.path.exists(file_path) else 0,
            format_type,
            quality,
            dt.now().isoformat(),
            json.dumps(tags or []),
            thumbnail_path,
            subtitle_path
        ))
        conn.commit()
        conn.close()

    def organize_file(self, file_path, info):
        """Organize file into subdirectories by uploader or date"""
        if not self.config.get('auto_organize'):
            return file_path
        uploader = info.get('uploader', 'Unknown').replace('/', '_').replace('\\', '_')
        new_dir = os.path.join(self.downloads_path, uploader)
        os.makedirs(new_dir, exist_ok=True)
        new_path = os.path.join(new_dir, os.path.basename(file_path))
        if file_path != new_path:
            shutil.move(file_path, new_path)
        return new_path

    def download_single_video(self, link, format_type="mp4", quality="best", custom_name=None, tags=None):
        """Download a single video with improved robustness"""
        try:
            video_id = self.get_video_id(link)
            if video_id:
                existing_path = self.is_already_downloaded(video_id)
                if existing_path:
                    print(f"✅ Video already downloaded: {existing_path}")
                    overwrite = input("Download anyway? (y/n): ").strip().lower()
                    if overwrite not in ['y', 'yes']:
                        return False

            # Clean up old files before download
            self.cleanup_old_files()

            # Get video info first
            ydl_opts_info = {'quiet': True, 'no_warnings': True, 'skip_download': True}
            with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
                info = ydl.extract_info(link, download=False)
                if not info:
                    print("❌ Could not retrieve video info.")
                    return False

            # Estimate file size
            estimated_size = self.calculate_file_size(info, quality)
            max_size = self.config.get('max_file_size_mb', 1000) * 1024 * 1024
            if estimated_size > max_size:
                print(f"⚠️ File size ({estimated_size / 1024 / 1024:.1f} MB) exceeds limit.")
                proceed = input("Continue anyway? (y/n): ").strip().lower()
                if proceed not in ['y', 'yes']:
                    return False

            # Filename handling
            if custom_name:
                filename_pattern = f"{custom_name}.%(ext)s"
            else:
                filename_pattern = self.config.get('custom_naming_pattern', '%(title)s.%(ext)s')
            outtmpl = os.path.join(self.downloads_path, filename_pattern)

            # Setup download options with improved format selection
            ydl_opts = {
                'outtmpl': outtmpl,
                'progress_hooks': self.progress_hooks, # Use the list of hooks
                'quiet': False,
                'no_warnings': False,
                'prefer_ffmpeg': True,
                'merge_output_format': 'mp4',
                'postprocessor_args': ['-movflags', 'faststart'],
                'noplaylist': True,
            }

            # Format selection based on youtube4.py improvements
            ffmpeg_available = self.check_ffmpeg()
            
            if format_type == "mp3":
                if not ffmpeg_available:
                    print("❌ FFmpeg not found. Cannot convert to MP3.")
                    return False
                ydl_opts['format'] = 'bestaudio/best'
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': self.config.get('preferred_audio_quality', '192'),
                }]
            else:
                # Improved video format selection
                height_map = {
                    '144p': 144, '240p': 240, '360p': 360, '480p': 480,
                    '720p': 720, '1080p': 1080, '1440p': 1440, '2160p': 2160,
                    'highest': None, 'best': None, 'max': None
                }
                
                if quality in height_map:
                    h = height_map[quality]
                    if h is None:
                        ydl_opts['format'] = 'bv*+ba/b'  # best video + best audio
                    else:
                        ydl_opts['format'] = f"bv*[height<={h}]+ba/b[height<={h}]"
                else:
                    # Legacy quality handling
                    if quality == "best":
                        ydl_opts['format'] = 'bv*+ba/b'
                    else:
                        ydl_opts['format'] = f'best[height<={quality}][ext=mp4]/best[height<={quality}]/best[ext=mp4]/best'

            print(f"🚀 Starting download...")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result = ydl.download([link])
                if result != 0:
                    print("❌ Download failed.")
                    return False

            # --- Start of new file detection logic to prevent "file not found" error ---
            
            # Use the prepare_filename method to predict the final filename
            # This is more reliable than hardcoding it
            expected_filename = ydl.prepare_filename(info)
            if format_type == "mp3":
                base_name = os.path.splitext(expected_filename)[0]
                expected_filename = base_name + '.mp3'

            final_path = os.path.join(self.downloads_path, self.sanitize_filename(os.path.basename(expected_filename)))
            
            # Wait for the file to exist before proceeding
            # This is the crucial step that solves the timing issue
            timeout = 30 # seconds
            start_time = time.time()
            file_found = False
            while time.time() - start_time < timeout:
                if os.path.exists(final_path) and os.path.getsize(final_path) > 0:
                    file_found = True
                    break
                # Check for alternative naming if it's a merged file
                temp_files = [f for f in os.listdir(self.downloads_path) if f.startswith(os.path.basename(final_path).split('.')[0]) and f != os.path.basename(final_path)]
                if temp_files:
                    try:
                        os.rename(os.path.join(self.downloads_path, temp_files[0]), final_path)
                        file_found = True
                        break
                    except OSError:
                        pass # File might be in use by another process

                time.sleep(1)

            if not file_found:
                print("❌ Download completed but final file was not found after waiting.")
                return False
            
            # --- End of new file detection logic ---

            # Organize and process file
            organized_path = self.organize_file(final_path, info)
            thumbnail_path = None
            subtitle_path = None

            # Embed metadata if supported
            if format_type in ['mp4', 'mp3']:
                self.embed_metadata(organized_path, info)

            # Save to database
            self.save_to_database(info, organized_path, format_type, quality, tags, thumbnail_path, subtitle_path)

            print(f"✅ Download completed successfully!")
            print(f"📁 File saved to: {organized_path}")
            if thumbnail_path:
                print(f"🖼️ Thumbnail: {thumbnail_path}")
            if subtitle_path:
                print(f"📝 Subtitles: {subtitle_path}")
            return True

        except yt_dlp.DownloadError as e:
            print(f"❌ Download error: {e}")
            return False
        except Exception as e:
            print(f"❌ Error: {e}")
            traceback.print_exc()
            return False
    def progress_hook(self, d):
        """Enhanced progress hook with better status handling"""
        if d['status'] == 'downloading':
            if d.get('total_bytes'):
                progress = (d['downloaded_bytes'] / d['total_bytes']) * 100
                percent_str = f"{progress:.1f}%"
            elif d.get('total_bytes_estimate'):
                progress = (d['downloaded_bytes'] / d['total_bytes_estimate']) * 100
                percent_str = f"{progress:.1f}%"
            else:
                percent_str = d.get('_percent_str', 'N/A')
                
            speed = d.get('_speed_str', 'N/A')
            eta = d.get('_eta_str', 'N/A')
            downloaded = d.get('downloaded_bytes', 0)
            
            if downloaded > 0:
                downloaded_mb = downloaded / (1024 * 1024)
                print(f"\r📥 Progress: {percent_str} | Speed: {speed} | ETA: {eta} | Downloaded: {downloaded_mb:.1f}MB", 
                      end='', flush=True)
            else:
                print(f"\r📥 Progress: {percent_str} | Speed: {speed} | ETA: {eta}", end='', flush=True)
                
        elif d['status'] == 'finished':
            print(f"\n✅ Download completed: {os.path.basename(d['filename'])}")
        elif d['status'] == 'error':
            print(f"\n❌ Download error occurred")

    def is_already_downloaded(self, video_id):
        """Check if video is already in database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT file_path FROM downloads WHERE video_id = ?", (video_id,))
        result = cursor.fetchone()
        conn.close()
        if result and os.path.exists(result[0]):
            return result[0]
        return None

    def add_to_queue(self, url, format_type="mp4", quality="best", custom_name=None, tags=None):
        """Add video to download queue"""
        queue_item = {
            'url': url,
            'format_type': format_type,
            'quality': quality,
            'custom_name': custom_name,
            'tags': tags or [],
            'added_date': dt.now().isoformat(),
            'status': 'pending'
        }
        self.download_queue.append(queue_item)
        self.save_queue()
        print(f"✅ Added to queue: {url}")

    def show_queue(self):
        """Display current download queue"""
        if not self.download_queue:
            print("📥 Download queue is empty.")
            return
        print("\n" + "=" * 80)
        print("📥 DOWNLOAD QUEUE:")
        print("=" * 80)
        for i, item in enumerate(self.download_queue, 1):
            status_emoji = "⏳" if item['status'] == 'pending' else "✅" if item['status'] == 'completed' else "❌"
            print(f"{i:2d}. {status_emoji} {item['url']}")
            print(f"     Format: {item['format_type']} | Quality: {item['quality']}")
            if item.get('custom_name'):
                print(f"     Custom name: {item['custom_name']}")
            if item.get('tags'):
                print(f"     Tags: {', '.join(item['tags'])}")

    def process_queue(self):
        """Process all items in download queue"""
        if not self.download_queue:
            print("Queue is empty.")
            return
        pending_items = [item for item in self.download_queue if item['status'] == 'pending']
        if not pending_items:
            print("No pending downloads in queue.")
            return
        # This function should be managed by the Flask API now
        print("This function is now managed by the Flask API.")
        
    def clear_completed_queue(self):
        """Remove completed items from queue"""
        original_count = len(self.download_queue)
        self.download_queue = [item for item in self.download_queue if item['status'] != 'completed']
        removed = original_count - len(self.download_queue)
        self.save_queue()
        print(f"✅ Removed {removed} completed items from queue.")

    def reorder_queue(self):
        """Reorder items in download queue"""
        if len(self.download_queue) < 2:
            print("Need at least 2 items to reorder.")
            return
        self.show_queue()
        print("Reorder options:")
        print("1. Move item up")
        print("2. Move item down")
        print("3. Move item to position")
        choice = input("Select option (1-3): ").strip()
        try:
            item_index = int(input("Enter item number: ")) - 1
            if not (0 <= item_index < len(self.download_queue)):
                print("❌ Invalid item number.")
                return
            if choice == '1' and item_index > 0:
                self.download_queue[item_index], self.download_queue[item_index - 1] = \
                    self.download_queue[item_index - 1], self.download_queue[item_index]
            elif choice == '2' and item_index < len(self.download_queue) - 1:
                self.download_queue[item_index], self.download_queue[item_index + 1] = \
                    self.download_queue[item_index + 1], self.download_queue[item_index]
            elif choice == '3':
                new_pos = int(input(f"New position (1-{len(self.download_queue)}): ")) - 1
                if 0 <= new_pos < len(self.download_queue):
                    item = self.download_queue.pop(item_index)
                    self.download_queue.insert(new_pos, item)
            self.save_queue()
            print("✅ Queue reordered successfully.")
        except ValueError:
            print("❌ Please enter valid numbers.")

    def manage_queue(self):
        """Interactive queue management"""
        while True:
            print("\n" + "=" * 50)
            print("📥 QUEUE MANAGEMENT")
            print("=" * 50)
            print("1. View queue")
            print("2. Process queue")
            print("3. Add URL to queue")
            print("4. Remove item from queue")
            print("5. Clear completed")
            print("6. Clear all")
            print("7. Reorder queue")
            print("0. Back")
            choice = input("Select option (0-7): ").strip()
            if choice == '0':
                break
            elif choice == '1':
                self.show_queue()
            elif choice == '2':
                self.process_queue()
            elif choice == '3':
                url = input("Enter URL: ").strip()
                if url:
                    format_type = input("Format (mp4/mp3): ").strip() or "mp4"
                    quality = input("Quality: ").strip() or "best"
                    tags = input("Tags (comma-separated, optional): ").split(',') if input("Add tags? (y/n): ").strip().lower() == 'y' else None
                    self.add_to_queue(url, format_type, quality, tags=tags)
            elif choice == '4':
                self.show_queue()
                if self.download_queue:
                    try:
                        index = int(input("Enter item number to remove: ")) - 1
                        if 0 <= index < len(self.download_queue):
                            removed = self.download_queue.pop(index)
                            self.save_queue()
                            print(f"✅ Removed: {removed['url']}")
                    except ValueError:
                        print("❌ Invalid number.")
            elif choice == '5':
                self.clear_completed_queue()
            elif choice == '6':
                confirm = input("Clear entire queue? (y/n): ").strip().lower()
                if confirm in ['y', 'yes']:
                    self.download_queue = []
                    self.save_queue()
                    print("✅ Queue cleared.")
            elif choice == '7':
                self.reorder_queue()

    def search_youtube_videos(self, query, max_results=15):
        """Search for YouTube videos and return up to 15 results"""
        print(f"🔍 Searching YouTube for: '{query}'...")
        print(f"Fetching up to {max_results} results. Please wait...")

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'skip_download': True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                search_query = f"ytsearch{max_results}:{query}"
                search_results = ydl.extract_info(search_query, download=False)

            if not search_results or 'entries' not in search_results:
                print("❌ No videos found for your search query.")
                return None

            videos = search_results['entries']
            if not videos or len(videos) == 0:
                print("❌ No valid videos returned.")
                return None

            videos = videos[:max_results]
            print(f"✅ Found {len(videos)} videos.")
            return self.display_search_results(videos, query)

        except Exception as e:
            print(f"❌ Search error: {e}")
            traceback.print_exc()
            return None

    def display_search_results(self, videos, query):
        """Display up to 15 search results with filtering, sorting, and selection"""
        if not videos:
            print("❌ No videos to display.")
            return None

        print(f"\n{'='*90}")
        print(f"🔍 SEARCH RESULTS FOR: '{query}'")
        print(f"{'='*90}")

        print("🔧 Options:")
        print("  f → Apply filters (duration, date, channel)")
        print("  s → Sort results (date, views, duration)")
        print("  q → Quit search")
        print("  Enter video number (1–15) to download")
        print("-" * 90)

        filtered_videos = videos
        while True:
            for idx, video in enumerate(filtered_videos, 1):
                title = video.get('title', 'Unknown Title')
                duration = video.get('duration', 0)
                view_count = video.get('view_count', 0)
                uploader = video.get('uploader', 'Unknown')
                upload_date = video.get('upload_date', '')

                if duration:
                    hours, rem = divmod(int(duration), 3600)
                    minutes, seconds = divmod(rem, 60)
                    if hours > 0:
                        duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                    else:
                        duration_str = f"{minutes:02d}:{seconds:02d}"
                else:
                    duration_str = "LIVE" if video.get('was_live') else "N/A"

                if view_count >= 1_000_000:
                    views_str = f"{view_count / 1_000_000:.1f}M"
                elif view_count >= 1_000:
                    views_str = f"{view_count / 1_000:.1f}K"
                else:
                    views_str = str(view_count) if view_count else "N/A"

                if upload_date and len(upload_date) == 8:
                    try:
                        upload_date_str = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
                    except:
                        upload_date_str = "Unknown"
                else:
                    upload_date_str = "Unknown"

                print(f"{idx:2}. {title}")
                print(f"     🕒 {duration_str} │ 👁️ {views_str} │ 📅 {upload_date_str} │ 📺 {uploader}")
                print()

            selection = input(f"👉 Select video (1–{len(filtered_videos)}), 'f', 's', or 'q' to quit: ").strip().lower()

            if selection == 'q':
                print("🚪 Exiting search...")
                return None

            elif selection == 'f':
                filtered_videos = self.apply_filters(filtered_videos)
                if not filtered_videos:
                    print("🚫 No videos match the filter criteria.")
                    return None
                print(f"✅ Filter applied. {len(filtered_videos)} videos remain.")
                continue

            elif selection == 's':
                filtered_videos = self.sort_results(filtered_videos)
                continue

            else:
                try:
                    choice = int(selection)
                    if 1 <= choice <= len(filtered_videos):
                        selected_video = filtered_videos[choice - 1]
                        video_url = selected_video.get('url') or f"https://www.youtube.com/watch?v={selected_video.get('id')}"
                        print(f"✅ Selected: {selected_video.get('title')}")
                        return video_url
                    else:
                        print(f"❌ Please enter a number between 1 and {len(filtered_videos)}.")
                except ValueError:
                    print("❌ Invalid input. Please enter a number or command.")

    def apply_filters(self, videos):
        """Apply filters to search results"""
        print("\n📋 FILTER OPTIONS:")
        print("1. Duration: Short (<4 min)")
        print("2. Duration: Medium (4–20 min)")
        print("3. Duration: Long (>20 min)")
        print("4. Upload Date: Last week")
        print("5. Upload Date: Last month")
        print("6. Channel name contains...")
        choice = input("Choose filter (1-6): ").strip()

        now = dt.now()

        if choice == '1':
            return [v for v in videos if v.get('duration', 0) and v['duration'] < 240]
        elif choice == '2':
            return [v for v in videos if v.get('duration', 0) and 240 <= v['duration'] <= 1200]
        elif choice == '3':
            return [v for v in videos if v.get('duration', 0) and v['duration'] > 1200]
        elif choice == '4':
            cutoff = now - timedelta(days=7)
        elif choice == '5':
            cutoff = now - timedelta(days=30)
        elif choice == '6':
            channel = input("Channel name (partial): ").strip().lower()
            return [v for v in videos if channel in v.get('uploader', '').lower()]
        else:
            return videos

        filtered = []
        for v in videos:
            upload_date = v.get('upload_date', '')
            if upload_date and len(upload_date) == 8:
                try:
                    video_date = dt.strptime(upload_date, '%Y%m%d')
                    if video_date >= cutoff:
                        filtered.append(v)
                except:
                    continue
        return filtered

    def sort_results(self, videos):
        """Sort search results"""
        print("\n📊 SORT OPTIONS:")
        print("1. Upload date (newest first)")
        print("2. View count (highest first)")
        print("3. Duration (longest first)")
        print("4. Title (A-Z)")
        choice = input("Choose sort option (1-4): ").strip()

        if choice == '1':
            key = 'upload_date'
            reverse = True
        elif choice == '2':
            key = 'view_count'
            reverse = True
        elif choice == '3':
            key = 'duration'
            reverse = True
        elif choice == '4':
            key = 'title'
            reverse = False
        else:
            return videos

        return sorted(
            videos,
            key=lambda x: x.get(key, '') or ('' if isinstance(x.get(key), str) else 0),
            reverse=reverse
        )

    def add_tags(self):
        """Prompt user to add tags"""
        if input("Add tags? (y/n): ").strip().lower() == 'y':
            tags_input = input("Enter tags (comma-separated): ").strip()
            return [tag.strip() for tag in tags_input.split(',') if tag.strip()]
        return []

    def schedule_download(self, url, schedule_time, format_type, quality):
        """Schedule a download"""
        try:
            scheduled_dt = dt.strptime(schedule_time, "%Y-%m-%d %H:%M")
            queue_item = {
                'url': url,
                'format_type': format_type,
                'quality': quality,
                'scheduled_time': scheduled_dt.isoformat(),
                'status': 'scheduled',
                'added_date': dt.now().isoformat()
            }
            self.download_queue.append(queue_item)
            self.save_queue()
            print(f"✅ Scheduled download for {scheduled_dt}")
        except ValueError:
            print("❌ Invalid date format.")

    def run_scheduled_tasks(self):
        """Run scheduled downloads"""
        now = dt.now()
        processed = 0
        for item in self.download_queue:
            if item['status'] == 'scheduled':
                scheduled_time = dt.fromisoformat(item['scheduled_time'])
                if now >= scheduled_time:
                    print(f"📥 Processing scheduled download: {item['url']}")
                    success = self.download_single_video(item['url'], item['format_type'], item['quality'])
                    item['status'] = 'completed' if success else 'failed'
                    processed += 1
        if processed > 0:
            self.save_queue()
            print(f"✅ Processed {processed} scheduled downloads.")

    def manage_scheduled_downloads(self):
        """Manage scheduled downloads"""
        scheduled_items = [item for item in self.download_queue if item['status'] == 'scheduled']
        while True:
            print("\n" + "=" * 50)
            print("⏰ SCHEDULED DOWNLOADS")
            print("=" * 50)
            if not scheduled_items:
                print("No scheduled downloads.")
                return
            for i, item in enumerate(scheduled_items, 1):
                scheduled_time = dt.fromisoformat(item['scheduled_time'])
                print(f"{i}. {item['url']} @ {scheduled_time}")
            print("1. Add new scheduled download")
            print("2. Remove scheduled download")
            print("0. Back")
            choice = input("Select option (0-2): ").strip()
            if choice == '0':
                break
            elif choice == '1':
                url = input("Enter URL: ").strip()
                schedule_time = input("Schedule time (YYYY-MM-DD HH:MM): ").strip()
                format_type = input("Format (mp4/mp3): ").strip() or "mp4"
                quality = input("Quality: ").strip() or "best"
                self.schedule_download(url, schedule_time, format_type, quality)
            elif choice == '2':
                try:
                    index = int(input("Enter item number to remove: ")) - 1
                    if 0 <= index < len(scheduled_items):
                        item = scheduled_items[index]
                        self.download_queue.remove(item)
                        self.save_queue()
                        print("✅ Scheduled download removed.")
                except ValueError:
                    print("❌ Invalid number.")

    def show_statistics(self):
        """Show download statistics"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), SUM(file_size) FROM downloads")
        count, total_size = cursor.fetchone()
        conn.close()
        print(f"\n📊 Download Statistics:")
        print(f"Total downloads: {count}")
        print(f"Total size: {total_size / (1024*1024):.1f} MB" if total_size else "Total size: 0 MB")

    def search_download_history(self, query):
        """Search download history"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT title, file_path FROM downloads WHERE title LIKE ?", (f'%{query}%',))
        results = cursor.fetchall()
        conn.close()
        if results:
            print(f"\nFound {len(results)} matching downloads:")
            for title, path in results:
                print(f"📄 {title}")
                if os.path.exists(path):
                    print(f"   ✅ {path}")
                else:
                    print(f"   ❌ File not found")
        else:
            print("No matches found.")

    def manage_settings(self):
        """Manage application settings"""
        while True:
            print("\n" + "=" * 50)
            print("⚙️ SETTINGS MENU:")
            print("=" * 50)
            print("1. Download location")
            print("2. Default quality settings")
            print("3. File naming pattern")
            print("4. Auto-organization")
            print("5. Subtitle preferences")
            print("6. Thumbnail preferences")
            print("7. File size limits")
            print("8. Export settings")
            print("9. Import settings")
            print("10. Reset to defaults")
            print("0. Back")
            choice = input("Select option (0-10): ").strip()
            if choice == '0':
                break
            elif choice == '1':
                new_path = input(f"Current: {self.downloads_path}\nNew path: ").strip()
                if new_path and os.path.exists(os.path.dirname(new_path)):
                    self.downloads_path = new_path
                    print("✅ Download location updated.")
            elif choice == '2':
                print("1. Always ask")
                print("2. Always best quality")
                print("3. Always 1080p")
                print("4. Always 720p")
                quality_choice = input("Select default (1-4): ").strip()
                quality_map = {'1': 'ask', '2': 'best', '3': '1080', '4': '720'}
                if quality_choice in quality_map:
                    self.config['default_quality'] = quality_map[quality_choice]
            elif choice == '3':
                print("Current pattern:", self.config['custom_naming_pattern'])
                print("Available variables: %(title)s, %(uploader)s, %(upload_date)s, %(duration)s")
                new_pattern = input("New pattern: ").strip()
                if new_pattern:
                    self.config['custom_naming_pattern'] = new_pattern
            elif choice == '4':
                self.config['auto_organize'] = input("Auto-organize files? (y/n): ").strip().lower() in ['y', 'yes']
            self.save_config()

    def cleanup_tools(self):
        """Cleanup and maintenance tools"""
        while True:
            print("\n" + "=" * 50)
            print("🧹 CLEANUP TOOLS")
            print("=" * 50)
            print("1. Remove duplicates")
            print("2. Clean broken links")
            print("3. Verify file integrity")
            print("4. Compress old downloads")
            print("5. Delete old files")
            print("6. Organize existing files")
            print("7. Fix missing metadata")
            print("0. Back")
            choice = input("Select option (0-7): ").strip()
            if choice == '0':
                break
            elif choice == '4':
                self.compress_old_downloads()

    def compress_old_downloads(self):
        """Compress old downloads to save space"""
        if not self.check_ffmpeg():
            print("❌ FFmpeg is required for compression.")
            return
        try:
            days_old = int(input("Compress files older than how many days? "))
        except ValueError:
            print("❌ Invalid number.")
            return
        cutoff_date = dt.now() - timedelta(days=days_old)
        total_space_saved = 0
        for root, _, files in os.walk(self.downloads_path):
            for file in files:
                if file.endswith('.mp4'):
                    file_path = os.path.join(root, file)
                    file_mtime = dt.fromtimestamp(os.path.getmtime(file_path))
                    if file_mtime < cutoff_date:
                        compressed_path = file_path + ".compressed.mp4"
                        original_size = os.path.getsize(file_path)
                        cmd = [
                            'ffmpeg', '-i', file_path,
                            '-vcodec', 'libx264', '-crf', '28',
                            '-preset', 'fast', '-y', compressed_path
                        ]
                        try:
                            result = subprocess.call([str(arg) for arg in cmd])
                            if result == 0 and os.path.exists(compressed_path):
                                compressed_size = os.path.getsize(compressed_path)
                                if compressed_size < original_size:
                                    space_saved = original_size - compressed_size
                                    total_space_saved += space_saved
                                    replace = input("Replace original? (y/n): ").strip().lower()
                                    if replace in ['y', 'yes']:
                                        os.remove(file_path)
                                        shutil.move(compressed_path, file_path)
                                        print("✅ Original replaced with compressed version.")
                                    else:
                                        os.remove(compressed_path)
                                        print("❌ Compressed version discarded.")
                                else:
                                    os.remove(compressed_path)
                                    print("❌ Compression did not save space.")
                            else:
                                print("❌ Compression failed.")
                        except Exception as e:
                            print(f"❌ Error compressing file: {e}")
        print(f"✅ Compression completed. Total space saved: {total_space_saved / (1024*1024):.1f} MB")

    def main_menu(self):
        """Main interactive menu"""
        while True:
            print("\n" + "=" * 60)
            print("🎬 YOUTUBE DOWNLOADER")
            print("=" * 60)
            print("1. Download Video")
            print("2. Manage Queue")
            print("3. Search YouTube")
            print("4. Show Statistics")
            print("5. Search Downloads")
            print("6. Settings")
            print("7. Scheduled Downloads")
            print("8. Cleanup Tools")
            print("0. Exit")
            choice = input("Select option (0-8): ").strip()
            try:
                if choice == '1':
                    self.interactive_download()
                elif choice == '2':
                    self.manage_queue()
                elif choice == '3':
                    query = input("Search YouTube: ").strip()
                    if query:
                        link = self.search_youtube_videos(query)
                        if link:
                            self.interactive_download_from_url(link)
                elif choice == '4':
                    self.show_statistics()
                elif choice == '5':
                    query = input("Search downloads: ").strip()
                    if query:
                        self.search_download_history(query)
                elif choice == '6':
                    self.manage_settings()
                elif choice == '7':
                    self.manage_scheduled_downloads()
                elif choice == '8':
                    self.cleanup_tools()
                elif choice == '0':
                    print("👋 Goodbye!")
                    break
                else:
                    print("❌ Invalid option.")
            except KeyboardInterrupt:
                print("\n👋 Program terminated by user.")
                break
            except Exception as e:
                print(f"❌ An error occurred: {e}")

    def interactive_download(self):
        """Interactive download prompt"""
        url = input("Enter YouTube URL: ").strip()
        if not self.is_youtube_url(url):
            print("❌ Invalid URL.")
            return False
        return self.interactive_download_from_url(url)

    def interactive_download_from_url(self, url):
        """Interactive download when URL is already known"""
        try:
            ydl_opts = {'quiet': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            print(f"🎬 Title: {info.get('title', 'Unknown')}")
            print(f"⏱️ Duration: {info.get('duration', 'Unknown')} seconds")
            print(f"👤 Uploader: {info.get('uploader', 'Unknown')}")

            print("\n" + "=" * 50)
            print("DOWNLOAD OPTIONS:")
            print("=" * 50)
            print("1. Quick Download (Best MP4)")
            print("2. Quick Download (Best MP3)")
            print("3. Custom Download")
            print("4. Add to Queue")
            print("5. Schedule Download")
            choice = input("Select option (1-5): ").strip()

            if choice == '1':
                return self.download_single_video(url, "mp4", "best")
            elif choice == '2':
                return self.download_single_video(url, "mp3", "best")
            elif choice == '3':
                format_type = input("Format (mp4/mp3): ").strip() or "mp4"
                quality = input("Quality (best/720/1080/etc): ").strip() or "best"
                tags = self.add_tags()
                return self.download_single_video(url, format_type, quality, tags=tags)
            elif choice == '4':
                format_type = input("Format (mp4/mp3): ").strip() or "mp4"
                quality = input("Quality: ").strip() or "best"
                tags = self.add_tags()
                self.add_to_queue(url, format_type, quality, tags=tags)
                return True
            elif choice == '5':
                schedule_time = input("Schedule time (YYYY-MM-DD HH:MM): ").strip()
                format_type = input("Format (mp4/mp3): ").strip() or "mp4"
                quality = input("Quality: ").strip() or "best"
                self.schedule_download(url, schedule_time, format_type, quality)
                return True
            else:
                print("❌ Invalid choice.")
                return False
        except Exception as e:
            print(f"❌ Error: {e}")
            return False

    def run(self):
        """Main entry point"""
        print("🎬 Welcome to YouTube Downloader!")
        print("=" * 60)
        if not self.check_ffmpeg():
            print("⚠️  FFmpeg not found. Some features limited.")
        print("Quick start:")
        print("1. Download a video now")
        print("2. Open full menu")
        quick_choice = input("Select (1-2): ").strip()
        if quick_choice == '1':
            self.interactive_download()
        self.main_menu()


def main():
    try:
        downloader = YouTubeDownloader()
        downloader.run()
    except KeyboardInterrupt:
        print("\n👋 Program terminated by user. Goodbye!")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()