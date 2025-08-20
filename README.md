# YouTube Downloader Flask API v2.0

A powerful, feature-rich YouTube video downloader built with Flask, providing both REST API endpoints and web interface for downloading YouTube videos with advanced features like queue management, scheduling, and compression.
<div align="center">
  <img src="assets/logo.png" alt="YouTube 4K Downloader API" width="200"/>
  <h1>YouTube 4K Downloader API</h1>
  <p>Professional high-resolution YouTube video downloader with REST API</p>
</div>
## 🚀 Features

### Core Functionality
- **Single Video Downloads**: Download individual YouTube videos in various formats (MP4, MP3)
- **Playlist Downloads**: Download entire playlists with progress tracking
- **Queue Management**: Add multiple videos to a download queue and process them batch-wise
- **Scheduled Downloads**: Schedule videos to be downloaded at specific times
- **Search Integration**: Search YouTube directly from the interface
- **Progress Tracking**: Real-time download progress with detailed statistics

### Advanced Features
- **File Compression**: Compress old video files using FFmpeg to save storage space
- **Duplicate Detection**: Automatically detect and handle duplicate downloads
- **Broken Link Cleanup**: Clean up database entries for missing files
- **Subtitle Downloads**: Download subtitle files when available
- **Thumbnail Caching**: Cache and serve video thumbnails
- **Custom Naming**: Use custom naming patterns for downloaded files
- **Format Selection**: Choose from multiple video qualities (720p, 1080p, best, etc.)

### Management & Analytics
- **Download History**: Complete history with search and filtering capabilities
- **Statistics Dashboard**: Detailed analytics including file sizes, format breakdown, and trends
- **Configuration Management**: Customizable settings for default quality, format, and behavior
- **Health Monitoring**: System health checks and status monitoring

## 📋 Prerequisites

- Python 3.7 or higher
- FFmpeg (optional, for video compression and format conversion)
- YouTube downloader backend class (`youtube.py` - must be implemented separately)

## 🛠️ Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/srikanth-thirumani/youtube-premium-downloader.git
   cd youtube-premium-downloader-api
   ```

2. **Install Python dependencies:**
   ```bash
   pip install flask flask-cors yt-dlp requests sqlite3
   ```

3. **Install FFmpeg (optional but recommended):**
   ```bash
   # Ubuntu/Debian
   sudo apt install ffmpeg
   
   # macOS
   brew install ffmpeg
   
   # Windows
   # Download from https://ffmpeg.org/download.html
   ```

4. **Create the YouTube downloader backend:**
   You need to implement a `youtube.py` file with a `YouTubeDownloader` class. The class should have the following methods:
   ```python
   class YouTubeDownloader:
       def __init__(self):
           self.downloads_path = "downloads"
           self.db_path = "downloads.db"
           self.download_queue = []
           self.config = {}
       
       def is_youtube_url(self, url): pass
       def get_video_info(self, url): pass
       def download_single_video(self, url, format_type, quality, custom_name=None, tags=None): pass
       def get_video_id(self, url): pass
       def is_already_downloaded(self, video_id): pass
       def calculate_file_size(self, video_info, quality): pass
       def check_ffmpeg(self): pass
       def save_queue(self): pass
       def save_config(self): pass
   ```

5. **Create HTML frontend (optional):**
   Create an `index1.html` file in the same directory for the web interface.

## 🚀 Quick Start

1. **Start the server:**
   ```bash
   python app.py
   ```

2. **Access the application:**
   - Web Interface: http://localhost:5000/
   - API Documentation: http://localhost:5000/ (when index.html is not found)
   - Health Check: http://localhost:5000/health

## 📡 API Endpoints

### Core Download Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/download` | Download a single video |
| `GET` | `/video-info` | Get video information without downloading |
| `GET` | `/download-status/<task_id>` | Check download progress |
| `GET` | `/file/<video_id>` | Download/stream a file |

### Queue Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/queue` | Get current download queue |
| `POST` | `/queue/add` | Add video to queue |
| `POST` | `/queue/process` | Process entire queue |
| `DELETE` | `/queue/clear` | Clear queue (all/completed/failed) |
| `DELETE` | `/queue/item/<index>` | Remove specific queue item |

### Search & Discovery

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/search` | Search YouTube videos |
| `POST` | `/playlist` | Download entire playlist |
| `GET` | `/thumbnail/<video_id>` | Get video thumbnail |

### History & Analytics

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/downloads` | Get download history (paginated) |
| `GET` | `/downloads/search` | Search download history |
| `DELETE` | `/downloads/<video_id>` | Delete download record |
| `GET` | `/stats` | Get download statistics |

### Scheduling & Automation

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/schedule` | Schedule download for later |
| `POST` | `/schedule/process` | Process due scheduled downloads |

### Maintenance & Cleanup

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/cleanup/duplicates` | Remove duplicate records |
| `POST` | `/cleanup/broken-links` | Clean up missing files |
| `POST` | `/cleanup/old-files` | Remove old files |
| `POST` | `/compress` | Compress video files |

### Configuration

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/config` | Get current configuration |
| `POST` | `/config` | Update configuration |
| `GET` | `/health` | Health check |

## 💡 Usage Examples

### Download a single video
```bash
curl -X POST http://localhost:5000/download \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=VIDEO_ID",
    "format_type": "mp4",
    "quality": "720p",
    "custom_name": "My Custom Video Name",
    "tags": ["music", "favorite"]
  }'
```

### Search YouTube videos
```bash
curl -X POST http://localhost:5000/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "python tutorial",
    "max_results": 10,
    "duration_filter": "medium",
    "sort_by": "view_count"
  }'
```

### Add video to queue
```bash
curl -X POST http://localhost:5000/queue/add \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=VIDEO_ID",
    "format_type": "mp4",
    "quality": "best",
    "priority": "high"
  }'
```

### Schedule a download
```bash
curl -X POST http://localhost:5000/schedule \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=VIDEO_ID",
    "schedule_time": "2024-12-25T10:00:00",
    "format_type": "mp4",
    "quality": "1080p"
  }'
```

### Get download statistics
```bash
curl http://localhost:5000/stats
```

## ⚙️ Configuration Options

The application supports various configuration options that can be updated via the `/config` endpoint:

```json
{
  "default_quality": "best",
  "default_format": "mp4",
  "auto_organize": true,
  "download_subtitles": true,
  "download_thumbnails": true,
  "max_file_size_mb": 1000,
  "custom_naming_pattern": "%(uploader)s - %(title)s.%(ext)s",
  "preferred_audio_quality": "192"
}
```

## 📁 Directory Structure

```
youtube-premium-downloader/
├── app.py                 # Main Flask application
├── youtube.py              # YouTube downloader backend (to be implemented)
├── index.html            # Web interface (optional)
├── downloads/             # Downloaded files directory
├── thumbnail_cache/       # Cached thumbnails
├── downloads.db           # SQLite database
├── queue.json            # Download queue storage
├── config.json           # Configuration file
└── README.md             # This file
```

## 🔧 Advanced Features

### File Compression
Compress old video files to save storage space:
```bash
curl -X POST http://localhost:5000/compress \
  -H "Content-Type: application/json" \
  -d '{
    "days_old": 30,
    "crf": 28,
    "dry_run": false
  }'
```

### Cleanup Operations
Remove duplicate downloads:
```bash
curl -X POST http://localhost:5000/cleanup/duplicates
```

Remove files older than 30 days:
```bash
curl -X POST http://localhost:5000/cleanup/old-files \
  -H "Content-Type: application/json" \
  -d '{"max_age_days": 30}'
```

### Progress Tracking
All long-running operations return a `task_id` that can be used to track progress:
```bash
curl http://localhost:5000/download-status/TASK_ID
```

## 🐛 Error Handling

The API provides comprehensive error handling with detailed error messages:

- **400 Bad Request**: Invalid parameters or malformed requests
- **404 Not Found**: Resource not found (video, file, etc.)
- **409 Conflict**: Duplicate entries or conflicts
- **500 Internal Server Error**: Server-side errors

## 🔒 Security Considerations

- The application runs on all interfaces (`0.0.0.0`) by default - consider restricting this in production
- No authentication is implemented - add authentication mechanisms for production use
- File paths are not sanitized beyond basic validation - implement additional security measures
- Rate limiting is not implemented - consider adding rate limiting for public deployments

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## ⚠️ Disclaimer

This tool is for educational purposes only. Please respect YouTube's Terms of Service and copyright laws. Users are responsible for ensuring they have the right to download the content they choose to download.

## 🙏 Acknowledgments

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - The powerful YouTube downloader library
- [Flask](https://flask.palletsprojects.com/) - The web framework used
- [FFmpeg](https://ffmpeg.org/) - For video processing and compression

## 📞 Support

If you encounter any issues or have questions, please:
1. Check the existing issues on GitHub
2. Create a new issue with detailed information about the problem
3. Include relevant logs and system information

---

**Happy Downloading! 🎥⬇️**
