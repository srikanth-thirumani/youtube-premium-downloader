from flask import Flask, request, jsonify, send_file, abort, send_from_directory, url_for
from flask_cors import CORS
import os
import json
import sqlite3
import traceback
from datetime import datetime as dt, timedelta
import yt_dlp
from urllib.parse import urlparse, parse_qs
import threading
import time
import uuid
import shutil
import re
import subprocess
import requests

# Import your YouTubeDownloader class
from youtube import YouTubeDownloader

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend integration

# Global downloader instance
downloader = YouTubeDownloader()

# Thread-safe download status tracking
download_status = {}
download_lock = threading.Lock()

@app.route('/', methods=['GET'])
def serve_index():
    """Serve the main HTML page"""
    try:
        return send_file('index.html')
    except FileNotFoundError:
        return jsonify({
            "message": "YouTube Downloader API v2.0",
            "version": "2.0",
            "note": "index.html not found - API endpoints available",
            "improvements": [
                "Enhanced video format selection",
                "Better file detection and organization",
                "Improved error handling",
                "Advanced search capabilities",
                "Scheduled downloads",
                "Compression tools",
                "Better metadata handling"
            ],
            "endpoints": {
                "GET /": "API information",
                "POST /download": "Download single video",
                "GET /video-info": "Get video information",
                "POST /queue/add": "Add video to queue",
                "GET /queue": "Get download queue",
                "POST /queue/process": "Process download queue",
                "DELETE /queue/clear": "Clear download queue",
                "GET /downloads": "Get download history",
                "GET /downloads/search": "Search download history",
                "GET /stats": "Get download statistics",
                "GET /config": "Get current configuration",
                "POST /config": "Update configuration",
                "GET /download-status/<task_id>": "Get download progress",
                "GET /file/<video_id>": "Download file",
                "POST /search": "Search YouTube videos",
                "POST /playlist": "Download entire playlist",
                "POST /schedule": "Schedule download",
                "POST /cleanup/duplicates": "Remove duplicates",
                "POST /cleanup/broken-links": "Clean broken links",
                "POST /compress": "Compress old files",
                "GET /thumbnail/<video_id>": "Serve video thumbnail"
            }
        })

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        # Check if required directories exist
        os.makedirs(downloader.downloads_path, exist_ok=True)
        
        # Check database connection
        conn = sqlite3.connect(downloader.db_path)
        conn.close()
        
        # Check FFmpeg availability
        ffmpeg_available = downloader.check_ffmpeg()
        
        return jsonify({
            "status": "healthy",
            "downloads_path": downloader.downloads_path,
            "database_path": downloader.db_path,
            "queue_size": len(downloader.download_queue),
            "ffmpeg_available": ffmpeg_available,
            "timestamp": dt.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": dt.now().isoformat()
        }), 500

@app.route('/video-info', methods=['GET'])
def get_video_info():
    """Get video information without downloading - enhanced version"""
    url = request.args.get('url')
    if not url:
        return jsonify({"error": "URL parameter required"}), 400
    
    if not downloader.is_youtube_url(url):
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    try:
        video_info = downloader.get_video_info(url)
        if 'error' in video_info:
            return jsonify({"error": video_info['error']}), 500
            
        # Enhanced video data with size estimation
        video_data = {
            "id": video_info.get('video_id'),
            "title": video_info.get('title'),
            "uploader": video_info.get('author'),
            "duration": video_info.get('duration'),
            "view_count": video_info.get('views'),
            "upload_date": video_info.get('upload_date'),
            "description": video_info.get('description', '')[:500] + ('...' if len(video_info.get('description', '')) > 500 else ''),
            "thumbnail": url_for('get_thumbnail', video_id=video_info.get('video_id')),
            "tags": video_info.get('tags', [])[:10],  # Limit tags
            "estimated_sizes": {
                "720p": f"{downloader.calculate_file_size({'duration': video_info.get('duration', 0)}, '720p') / (1024*1024):.1f} MB",
                "1080p": f"{downloader.calculate_file_size({'duration': video_info.get('duration', 0)}, '1080p') / (1024*1024):.1f} MB",
                "best": f"{downloader.calculate_file_size({'duration': video_info.get('duration', 0)}, 'best') / (1024*1024):.1f} MB"
            }
        }
        return jsonify(video_data)
    
    except Exception as e:
        return jsonify({"error": f"Failed to get video info: {str(e)}"}), 500

@app.route('/download', methods=['POST'])
def download_video():
    """Download a single video with enhanced options"""
    data = request.get_json() or {}
    url = data.get('url')
    format_type = data.get('format_type', 'mp4')
    quality = data.get('quality', 'best')
    custom_name = data.get('custom_name')
    tags = data.get('tags', [])
    
    if not url:
        return jsonify({"error": "URL is required"}), 400
    
    if not downloader.is_youtube_url(url):
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    # Check if already downloaded
    video_id = downloader.get_video_id(url)
    if video_id:
        existing_path = downloader.is_already_downloaded(video_id)
        if existing_path:
            return jsonify({
                "message": "Video already exists",
                "existing_file": existing_path,
                "video_id": video_id,
                "ask_overwrite": True
            })
    
    # Generate unique task ID
    task_id = str(uuid.uuid4())
    
    def download_task():
        with download_lock:
            download_status[task_id] = {
                "status": "starting", 
                "progress": 0,
                "video_info": None,
                "error": None
            }
        
        try:
            # Get video info first
            download_status[task_id]["status"] = "extracting_info"
            download_status[task_id]["progress"] = 5
            
            video_info = downloader.get_video_info(url)
            if 'error' in video_info:
                download_status[task_id] = {
                    "status": "failed", 
                    "progress": 0, 
                    "error": video_info['error']
                }
                return
                
            download_status[task_id]["video_info"] = {
                "title": video_info.get('title'),
                "duration": video_info.get('duration'),
                "uploader": video_info.get('author')
            }
            
            # Update status to downloading
            download_status[task_id]["status"] = "downloading"
            download_status[task_id]["progress"] = 10
            
            # Enhanced progress tracking
            def progress_hook(d):
                if d['status'] == 'downloading':
                    if 'total_bytes' in d and d['total_bytes']:
                        progress = int((d['downloaded_bytes'] / d['total_bytes']) * 80) + 10
                        download_status[task_id]["progress"] = min(progress, 90)
                        download_status[task_id]["downloaded_mb"] = d['downloaded_bytes'] / (1024*1024)
                        download_status[task_id]["total_mb"] = d['total_bytes'] / (1024*1024)
                        download_status[task_id]["speed"] = d.get('_speed_str', 'N/A')
                        download_status[task_id]["eta"] = d.get('_eta_str', 'N/A')
                    elif 'total_bytes_estimate' in d and d['total_bytes_estimate']:
                        progress = int((d['downloaded_bytes'] / d['total_bytes_estimate']) * 80) + 10
                        download_status[task_id]["progress"] = min(progress, 90)
                elif d['status'] == 'finished':
                    download_status[task_id]["progress"] = 95
                    download_status[task_id]["status"] = "processing"
            
            # Add progress hook to downloader temporarily
            original_hooks = getattr(downloader, 'progress_hooks', [])
            downloader.progress_hooks = [progress_hook]
            
            success = downloader.download_single_video(
                url, format_type, quality, custom_name, tags
            )
            
            # Restore original hooks
            downloader.progress_hooks = original_hooks
            
            if success:
                download_status[task_id] = {
                    "status": "completed", 
                    "progress": 100,
                    "video_info": download_status[task_id].get("video_info")
                }
            else:
                download_status[task_id] = {
                    "status": "failed", 
                    "progress": 0, 
                    "error": "Download failed - check logs for details"
                }
                
        except Exception as e:
            download_status[task_id] = {
                "status": "failed", 
                "progress": 0, 
                "error": str(e)
            }
    
    # Start download in background thread
    thread = threading.Thread(target=download_task)
    thread.daemon = True
    thread.start()
    
    return jsonify({
        "message": "Download started",
        "task_id": task_id,
        "status_url": f"/download-status/{task_id}"
    })

@app.route('/download-status/<task_id>', methods=['GET'])
def get_download_status(task_id):
    """Get download progress status with enhanced details"""
    status = download_status.get(task_id, {"status": "not_found", "error": "Task not found"})
    return jsonify(status)

@app.route('/search', methods=['POST'])
def search_youtube():
    """Enhanced YouTube search with filtering"""
    data = request.get_json() or {}
    query = data.get('query')
    max_results = min(int(data.get('max_results', 15)), 50)  # Cap at 50
    duration_filter = data.get('duration_filter')  # short, medium, long
    upload_date_filter = data.get('upload_date_filter')  # week, month, year
    sort_by = data.get('sort_by', 'relevance')  # relevance, upload_date, view_count
    
    if not query:
        return jsonify({"error": "Query parameter required"}), 400
    
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'skip_download': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_query = f"ytsearch{max_results}:{query}"
            search_results = ydl.extract_info(search_query, download=False)
        
        if not search_results or 'entries' not in search_results:
            return jsonify({"videos": [], "total": 0})
        
        videos = []
        for video in search_results['entries'][:max_results]:
            if video:
                duration = video.get('duration', 0)
                
                # Apply duration filter
                if duration_filter:
                    if duration_filter == 'short' and duration > 240:
                        continue
                    elif duration_filter == 'medium' and (duration <= 240 or duration > 1200):
                        continue
                    elif duration_filter == 'long' and duration <= 1200:
                        continue
                
                # Format duration
                if duration:
                    hours, rem = divmod(int(duration), 3600)
                    minutes, seconds = divmod(rem, 60)
                    if hours > 0:
                        duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                    else:
                        duration_str = f"{minutes:02d}:{seconds:02d}"
                else:
                    duration_str = "LIVE" if video.get('was_live') else "N/A"
                
                # Format view count
                view_count = video.get('view_count', 0)
                if view_count >= 1_000_000:
                    views_str = f"{view_count / 1_000_000:.1f}M"
                elif view_count >= 1_000:
                    views_str = f"{view_count / 1_000:.1f}K"
                else:
                    views_str = str(view_count) if view_count else "N/A"
                
                video_data = {
                    "id": video.get('id'),
                    "title": video.get('title'),
                    "uploader": video.get('uploader'),
                    "duration": duration,
                    "duration_str": duration_str,
                    "view_count": view_count,
                    "views_str": views_str,
                    "upload_date": video.get('upload_date'),
                    "url": video.get('url') or f"https://www.youtube.com/watch?v={video.get('id')}",
                    "thumbnail": url_for('get_thumbnail', video_id=video.get('id')),
                    "description": (video.get('description') or '')[:200] + ('...' if len(video.get('description') or '') > 200 else '')
                }
                videos.append(video_data)
        
        # Apply sorting
        if sort_by == 'upload_date':
            videos.sort(key=lambda x: x.get('upload_date', ''), reverse=True)
        elif sort_by == 'view_count':
            videos.sort(key=lambda x: x.get('view_count', 0), reverse=True)
        elif sort_by == 'duration':
            videos.sort(key=lambda x: x.get('duration', 0), reverse=True)
        
        return jsonify({"videos": videos, "total": len(videos)})
    
    except Exception as e:
        return jsonify({"error": f"Search failed: {str(e)}"}), 500

@app.route('/thumbnail/<video_id>', methods=['GET'])
def get_thumbnail(video_id):
    """Fetches and serves the thumbnail for a given video ID."""
    try:
        # Check if thumbnail already exists in cache
        cache_dir = os.path.join(os.getcwd(), 'thumbnail_cache')
        os.makedirs(cache_dir, exist_ok=True)
        cached_path = os.path.join(cache_dir, f"{video_id}.jpg")

        if os.path.exists(cached_path):
            return send_file(cached_path, mimetype='image/jpeg')

        # If not in cache, fetch using yt_dlp
        url = f"https://www.youtube.com/watch?v={video_id}"
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'writethumbnail': True,
            'outtmpl': os.path.join(cache_dir, f"{video_id}.%(ext)s")
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            thumbnail_url = info.get('thumbnail')
            if not thumbnail_url:
                abort(404, description="Thumbnail URL not found.")
            
            # Download the thumbnail to cache
            response = requests.get(thumbnail_url)
            if response.status_code == 200:
                with open(cached_path, 'wb') as f:
                    f.write(response.content)
                return send_file(cached_path, mimetype='image/jpeg')
            else:
                abort(500, description="Failed to download thumbnail from source.")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/queue', methods=['GET'])
def get_queue():
    """Get current download queue with status"""
    queue_with_status = []
    for item in downloader.download_queue:
        queue_item = dict(item)
        # Add estimated size if not present
        if 'estimated_size' not in queue_item and queue_item.get('url'):
            try:
                video_info = downloader.get_video_info(queue_item['url'])
                if 'duration' in video_info:
                    size_mb = downloader.calculate_file_size(video_info, queue_item.get('quality', 'best')) / (1024*1024)
                    queue_item['estimated_size_mb'] = round(size_mb, 1)
            except:
                pass
        queue_with_status.append(queue_item)
    
    return jsonify({
        "queue": queue_with_status,
        "total_items": len(queue_with_status),
        "pending_items": len([item for item in queue_with_status if item.get('status') == 'pending'])
    })

@app.route('/queue/add', methods=['POST'])
def add_to_queue():
    """Add video to download queue with enhanced validation"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON data required"}), 400
    
    url = data.get('url')
    format_type = data.get('format_type', 'mp4')
    quality = data.get('quality', 'best')
    custom_name = data.get('custom_name')
    tags = data.get('tags', [])
    priority = data.get('priority', 'normal')  # high, normal, low
    
    if not url:
        return jsonify({"error": "URL is required"}), 400
    
    if not downloader.is_youtube_url(url):
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    try:
        # Get video info for validation and display
        video_info = downloader.get_video_info(url)
        if 'error' in video_info:
            return jsonify({"error": f"Cannot get video info: {video_info['error']}"}), 400
        
        # Check if already in queue
        for item in downloader.download_queue:
            if item['url'] == url and item.get('status') == 'pending':
                return jsonify({"error": "Video already in queue"}), 409
        
        # Check if already downloaded
        video_id = downloader.get_video_id(url)
        if video_id and downloader.is_already_downloaded(video_id):
            return jsonify({
                "warning": "Video already downloaded",
                "ask_confirmation": True,
                "video_info": {
                    "title": video_info.get('title'),
                    "uploader": video_info.get('author')
                }
            })
        
        # Add to queue with enhanced metadata
        queue_item = {
            "url": url,
            "format_type": format_type,
            "quality": quality,
            "custom_name": custom_name,
            "tags": tags,
            "priority": priority,
            "status": "pending",
            "added_date": dt.now().isoformat(),
            "video_info": {
                "title": video_info.get('title'),
                "uploader": video_info.get('author'),
                "duration": video_info.get('duration')
            },
            "estimated_size_mb": round(downloader.calculate_file_size(video_info, quality) / (1024*1024), 1)
        }
        
        # Insert based on priority
        if priority == 'high':
            downloader.download_queue.insert(0, queue_item)
        else:
            downloader.download_queue.append(queue_item)
        
        downloader.save_queue()
        
        return jsonify({
            "message": "Added to queue successfully",
            "queue_position": len(downloader.download_queue),
            "video_info": queue_item["video_info"]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/queue/process', methods=['POST'])
def process_queue():
    """Process all items in download queue with enhanced progress tracking"""
    try:
        pending_items = [item for item in downloader.download_queue if item.get('status') == 'pending']
        if not pending_items:
            return jsonify({"error": "No pending items in queue"}), 400
        
        # Generate task ID for queue processing
        task_id = str(uuid.uuid4())
        
        def process_task():
            download_status[task_id] = {
                "status": "processing_queue",
                "progress": 0,
                "total_items": len(pending_items),
                "current_item": 0,
                "successful_downloads": 0,
                "failed_downloads": 0,
                "current_video": None
            }
            
            for i, item in enumerate(pending_items):
                try:
                    # Update status
                    download_status[task_id].update({
                        "current_item": i + 1,
                        "progress": int((i / len(pending_items)) * 100),
                        "current_video": item.get('video_info', {}).get('title', item['url'])
                    })
                    
                    item['status'] = 'processing'
                    downloader.save_queue()
                    
                    success = downloader.download_single_video(
                        item['url'],
                        item.get('format_type', 'mp4'),
                        item.get('quality', 'best'),
                        custom_name=item.get('custom_name'),
                        tags=item.get('tags', [])
                    )
                    
                    if success:
                        item['status'] = 'completed'
                        download_status[task_id]["successful_downloads"] += 1
                    else:
                        item['status'] = 'failed'
                        download_status[task_id]["failed_downloads"] += 1
                        
                    item['processed_date'] = dt.now().isoformat()
                    downloader.save_queue()
                    
                except Exception as e:
                    item['status'] = 'failed'
                    item['error'] = str(e)
                    download_status[task_id]["failed_downloads"] += 1
                    downloader.save_queue()
            
            # Final status
            download_status[task_id].update({
                "status": "completed",
                "progress": 100,
                "total_videos": len(pending_items),
                "successful_downloads": download_status[task_id]["successful_downloads"],
                "failed_downloads": download_status[task_id]["failed_downloads"],
                "current_video": "Queue processing completed"
            })
        
        thread = threading.Thread(target=process_task)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            "message": "Queue processing started",
            "task_id": task_id,
            "status_url": f"/download-status/{task_id}",
            "total_items": len(pending_items)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/queue/clear', methods=['DELETE'])
def clear_queue():
    """Clear download queue with options"""
    try:
        queue_type = request.args.get('type', 'completed')
        
        if queue_type == 'all':
            cleared_count = len(downloader.download_queue)
            downloader.download_queue = []
        elif queue_type == 'completed':
            original_count = len(downloader.download_queue)
            downloader.download_queue = [
                item for item in downloader.download_queue 
                if item.get('status') not in ['completed']
            ]
            cleared_count = original_count - len(downloader.download_queue)
        elif queue_type == 'failed':
            original_count = len(downloader.download_queue)
            downloader.download_queue = [
                item for item in downloader.download_queue 
                if item.get('status') not in ['failed']
            ]
            cleared_count = original_count - len(downloader.download_queue)
        else:
            return jsonify({"error": "Invalid type. Use 'all', 'completed', or 'failed'"}), 400
        
        downloader.save_queue()
        return jsonify({
            "message": f"Queue cleared ({queue_type})",
            "cleared_count": cleared_count,
            "remaining_items": len(downloader.download_queue)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/queue/item/<int:index>', methods=['DELETE'])
def remove_queue_item(index):
    """Remove specific item from queue"""
    try:
        if 0 <= index < len(downloader.download_queue):
            removed_item = downloader.download_queue.pop(index)
            downloader.save_queue()
            return jsonify({
                "message": "Item removed from queue",
                "removed_item": {
                    "url": removed_item.get('url'),
                    "title": removed_item.get('video_info', {}).get('title', 'Unknown')
                },
                "remaining_items": len(downloader.download_queue)
            })
        else:
            return jsonify({"error": "Invalid queue index"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/downloads', methods=['GET'])
def get_downloads():
    """Get download history with enhanced pagination and filtering"""
    try:
        page = int(request.args.get('page', 1))
        per_page = min(int(request.args.get('per_page', 20)), 100)  # Cap at 100
        format_filter = request.args.get('format')
        uploader_filter = request.args.get('uploader')
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        
        offset = (page - 1) * per_page
        
        conn = sqlite3.connect(downloader.db_path)
        cursor = conn.cursor()
        
        # Build query with filters
        where_clauses = []
        params = []
        
        if format_filter:
            where_clauses.append("format_type = ?")
            params.append(format_filter)
            
        if uploader_filter:
            where_clauses.append("uploader LIKE ?")
            params.append(f"%{uploader_filter}%")
            
        if date_from:
            where_clauses.append("download_date >= ?")
            params.append(date_from)
            
        if date_to:
            where_clauses.append("download_date <= ?")
            params.append(date_to)
        
        where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        
        # Get total count
        count_query = f"SELECT COUNT(*) FROM downloads{where_sql}"
        cursor.execute(count_query, params)
        total = cursor.fetchone()[0]
        
        # Get paginated results
        query = f'''
            SELECT video_id, title, uploader, duration, file_path, file_size, 
                   format_type, quality, download_date, tags, thumbnail_path,
                   subtitle_path
            FROM downloads 
            {where_sql}
            ORDER BY download_date DESC 
            LIMIT ? OFFSET ?
        '''
        cursor.execute(query, params + [per_page, offset])
        
        downloads = []
        for row in cursor.fetchall():
            file_path = row[4]
            file_exists = os.path.exists(file_path) if file_path else False
            file_size_mb = round(row[5] / (1024*1024), 2) if row[5] else 0
            
            download_data = {
                "video_id": row[0],
                "title": row[1],
                "uploader": row[2],
                "duration": row[3],
                "file_path": file_path,
                "file_size": row[5],
                "file_size_mb": file_size_mb,
                "format_type": row[6],
                "quality": row[7],
                "download_date": row[8],
                "tags": json.loads(row[9]) if row[9] else [],
                "thumbnail_path": row[10],
                "subtitle_path": row[11],
                "file_exists": file_exists
            }
            downloads.append(download_data)
        
        conn.close()
        
        return jsonify({
            "downloads": downloads,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page
            },
            "filters_applied": {
                "format": format_filter,
                "uploader": uploader_filter,
                "date_from": date_from,
                "date_to": date_to
            }
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/downloads/search', methods=['GET'])
def search_downloads():
    """Enhanced search in download history"""
    query = request.args.get('query')
    search_type = request.args.get('type', 'all')  # title, uploader, tags, all
    
    if not query:
        return jsonify({"error": "Query parameter required"}), 400
    
    try:
        conn = sqlite3.connect(downloader.db_path)
        cursor = conn.cursor()
        
        if search_type == 'title':
            sql = "SELECT * FROM downloads WHERE title LIKE ? ORDER BY download_date DESC LIMIT 100"
            params = (f'%{query}%',)
        elif search_type == 'uploader':
            sql = "SELECT * FROM downloads WHERE uploader LIKE ? ORDER BY download_date DESC LIMIT 100"
            params = (f'%{query}%',)
        elif search_type == 'tags':
            sql = "SELECT * FROM downloads WHERE tags LIKE ? ORDER BY download_date DESC LIMIT 100"
            params = (f'%{query}%',)
        else:  # all
            sql = '''
                SELECT * FROM downloads 
                WHERE title LIKE ? OR uploader LIKE ? OR tags LIKE ?
                ORDER BY download_date DESC LIMIT 100
            '''
            params = (f'%{query}%', f'%{query}%', f'%{query}%')
        
        cursor.execute(sql, params)
        
        downloads = []
        for row in cursor.fetchall():
            download_data = {
                "video_id": row[1],
                "title": row[2],
                "uploader": row[3],
                "duration": row[4],
                "file_path": row[5],
                "file_size": row[6],
                "file_size_mb": round(row[6] / (1024*1024), 2) if row[6] else 0,
                "format_type": row[7],
                "quality": row[8],
                "download_date": row[9],
                "tags": json.loads(row[10]) if row[10] else [],
                "thumbnail_path": row[11] if len(row) > 11 else None,
                "subtitle_path": row[12] if len(row) > 12 else None,
                "file_exists": os.path.exists(row[5]) if row[5] else False
            }
            downloads.append(download_data)
        
        conn.close()
        return jsonify({
            "downloads": downloads, 
            "total": len(downloads),
            "search_query": query,
            "search_type": search_type
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/downloads/<video_id>', methods=['DELETE'])
def delete_download(video_id):
    """Delete download record and optionally the file"""
    try:
        delete_file = request.args.get('delete_file', 'false').lower() == 'true'
        
        conn = sqlite3.connect(downloader.db_path)
        cursor = conn.cursor()
        
        # Get file info before deletion
        cursor.execute("SELECT file_path, thumbnail_path, subtitle_path FROM downloads WHERE video_id = ?", (video_id,))
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            return jsonify({"error": "Download not found"}), 404
        
        file_path, thumbnail_path, subtitle_path = result
        
        # Delete from database
        cursor.execute("DELETE FROM downloads WHERE video_id = ?", (video_id,))
        rows_affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        if rows_affected == 0:
            return jsonify({"error": "Download not found"}), 404
        
        # Optionally delete files
        files_deleted = []
        if delete_file:
            for path_type, path in [("video file", file_path), ("thumbnail", thumbnail_path), ("subtitle", subtitle_path)]:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                        files_deleted.append(path_type)
                    except Exception as e:
                        print(f"Error deleting {path_type}: {e}")
        
        message = "Download record deleted"
        if files_deleted:
            message += f" and {', '.join(files_deleted)} deleted"
        
        return jsonify({"message": message, "files_deleted": files_deleted})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/stats', methods=['GET'])
def get_statistics():
    """Get enhanced download statistics"""
    try:
        conn = sqlite3.connect(downloader.db_path)
        cursor = conn.cursor()
        
        # Basic stats
        cursor.execute("SELECT COUNT(*), SUM(file_size) FROM downloads")
        count_result = cursor.fetchone()
        total_downloads = count_result[0] if count_result else 0
        total_size = count_result[1] if count_result and count_result[1] else 0
        
        # Recent downloads (last 7 days)
        cursor.execute('''
            SELECT COUNT(*) FROM downloads 
            WHERE download_date >= datetime('now', '-7 days')
        ''')
        recent_result = cursor.fetchone()
        recent_downloads = recent_result[0] if recent_result else 0
        
        # Format breakdown
        cursor.execute("SELECT format_type, COUNT(*), SUM(file_size) FROM downloads GROUP BY format_type")
        format_breakdown = {}
        for row in cursor.fetchall():
            format_breakdown[row[0]] = {
                "count": row[1],
                "total_size_mb": round(row[2] / (1024*1024), 2) if row[2] else 0
            }
        
        # Quality breakdown
        cursor.execute("SELECT quality, COUNT(*) FROM downloads GROUP BY quality")
        quality_breakdown = {}
        for row in cursor.fetchall():
            quality_breakdown[row[0]] = row[1]
        
        # Top uploaders
        cursor.execute('''
            SELECT uploader, COUNT(*) as count, SUM(file_size) as total_size
            FROM downloads 
            WHERE uploader IS NOT NULL
            GROUP BY uploader 
            ORDER BY count DESC 
            LIMIT 10
        ''')
        top_uploaders = []
        for row in cursor.fetchall():
            top_uploaders.append({
                "uploader": row[0],
                "count": row[1],
                "total_size_mb": round(row[2] / (1024*1024), 2) if row[2] else 0
            })
        
        # Downloads by month (last 12 months)
        cursor.execute('''
            SELECT strftime('%Y-%m', download_date) as month, COUNT(*), SUM(file_size)
            FROM downloads 
            WHERE download_date >= datetime('now', '-12 months')
            GROUP BY month
            ORDER BY month
        ''')
        monthly_stats = []
        for row in cursor.fetchall():
            monthly_stats.append({
                "month": row[0],
                "downloads": row[1],
                "size_mb": round(row[2] / (1024*1024), 2) if row[2] else 0
            })
        
        # Average file size by format
        cursor.execute('''
            SELECT format_type, AVG(file_size) as avg_size
            FROM downloads 
            WHERE file_size > 0
            GROUP BY format_type
        ''')
        avg_sizes = {}
        for row in cursor.fetchall():
            avg_sizes[row[0]] = round(row[1] / (1024*1024), 2) if row[1] else 0
        
        conn.close()
        
        return jsonify({
            "summary": {
                "total_downloads": total_downloads,
                "total_size_mb": round(total_size / (1024 * 1024), 2) if total_size else 0,
                "recent_downloads": recent_downloads,
                "queue_size": len(downloader.download_queue),
                "pending_in_queue": len([item for item in downloader.download_queue if item.get('status') == 'pending'])
            },
            "breakdowns": {
                "formats": format_breakdown,
                "qualities": quality_breakdown,
                "average_sizes_mb": avg_sizes
            },
            "top_uploaders": top_uploaders,
            "monthly_stats": monthly_stats,
            "system_info": {
                "ffmpeg_available": downloader.check_ffmpeg(),
                "downloads_path": downloader.downloads_path,
                "database_size_mb": round(os.path.getsize(downloader.db_path) / (1024*1024), 2) if os.path.exists(downloader.db_path) else 0
            }
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/config', methods=['GET'])
def get_config():
    """Get current configuration with descriptions"""
    config_with_descriptions = {
        "current_config": downloader.config,
        "config_descriptions": {
            "default_quality": "Default video quality (best, 720p, 1080p, etc.)",
            "default_format": "Default download format (mp4, mp3)",
            "auto_organize": "Automatically organize files by uploader",
            "download_subtitles": "Download subtitle files when available",
            "download_thumbnails": "Download video thumbnails",
            "max_file_size_mb": "Maximum file size limit in MB",
            "custom_naming_pattern": "File naming pattern (use %(title)s, %(uploader)s, etc.)",
            "preferred_audio_quality": "Audio quality for MP3 downloads (128, 192, 320)"
        },
        "available_qualities": ["best", "720p", "1080p", "1440p", "2160p", "worst"],
        "available_formats": ["mp4", "mp3"]
    }
    return jsonify(config_with_descriptions)

@app.route('/config', methods=['POST'])
def update_config():
    """Update configuration with validation"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON data required"}), 400
    
    try:
        updated_keys = []
        
        # Validate and update config with type checking
        valid_keys = {
            "default_quality": str,
            "default_format": str,
            "auto_organize": bool,
            "download_subtitles": bool,
            "download_thumbnails": bool,
            "max_file_size_mb": (int, float),
            "custom_naming_pattern": str,
            "preferred_audio_quality": str
        }
        
        for key, value in data.items():
            if key in valid_keys:
                expected_type = valid_keys[key]
                if isinstance(expected_type, tuple):
                    if not isinstance(value, expected_type):
                        return jsonify({"error": f"Invalid type for {key}"}), 400
                else:
                    if not isinstance(value, expected_type):
                        return jsonify({"error": f"Invalid type for {key}. Expected {expected_type.__name__}"}), 400
                
                # Additional validation
                if key == "max_file_size_mb" and value <= 0:
                    return jsonify({"error": "max_file_size_mb must be positive"}), 400
                if key == "default_format" and value not in ["mp4", "mp3"]:
                    return jsonify({"error": "default_format must be mp4 or mp3"}), 400
                
                downloader.config[key] = value
                updated_keys.append(key)
        
        if updated_keys:
            downloader.save_config()
            return jsonify({
                "message": "Configuration updated successfully",
                "updated_keys": updated_keys,
                "new_config": {k: downloader.config[k] for k in updated_keys}
            })
        else:
            return jsonify({"message": "No valid configuration keys provided"})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/file/<video_id>')
def download_file(video_id):
    """Serve downloaded files by video ID with better error handling"""
    try:
        conn = sqlite3.connect(downloader.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT file_path, title, format_type FROM downloads WHERE video_id = ?", (video_id,))
        result = cursor.fetchone()
        conn.close()
        
        if not result:
            abort(404)
        
        file_path, title, format_type = result
        
        if not file_path or not os.path.exists(file_path):
            return jsonify({"error": "File not found on disk"}), 404
        
        # Get the directory and filename
        directory = os.path.dirname(file_path)
        filename = os.path.basename(file_path)
        
        # Set proper content type
        mimetype = None
        if format_type == 'mp3':
            mimetype = 'audio/mpeg'
        elif format_type == 'mp4':
            mimetype = 'video/mp4'
        
        return send_from_directory(
            directory, 
            filename, 
            as_attachment=True,
            mimetype=mimetype,
            download_name=f"{title}.{format_type}" if title else filename
        )
    
    except Exception as e:
        print(f"Error serving file: {e}")
        abort(500)

@app.route('/playlist', methods=['POST'])
def download_playlist():
    """Download entire playlist with enhanced progress tracking"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON data required"}), 400
    
    url = data.get('url')
    format_type = data.get('format_type', 'mp4')
    quality = data.get('quality', 'best')
    max_videos = data.get('max_videos', 50)  # Limit playlist size
    
    if not url:
        return jsonify({"error": "URL is required"}), 400
    
    # Generate task ID for progress tracking
    task_id = str(uuid.uuid4())
    
    def playlist_download_task():
        try:
            download_status[task_id] = {"status": "extracting", "progress": 5}
            
            ydl_opts = {
                'quiet': True,
                'extract_flat': True,
                'skip_download': True
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                playlist_info = ydl.extract_info(url, download=False)
            
            if not playlist_info or 'entries' not in playlist_info:
                download_status[task_id] = {"status": "failed", "error": "Could not extract playlist"}
                return
            
            videos = [v for v in playlist_info['entries'] if v and v.get('id')][:max_videos]
            total_videos = len(videos)
            
            if total_videos == 0:
                download_status[task_id] = {"status": "failed", "error": "No videos found in playlist"}
                return
            
            download_status[task_id] = {
                "status": "downloading", 
                "progress": 10, 
                "total_videos": total_videos,
                "current_video": 0,
                "successful_downloads": 0,
                "failed_downloads": 0,
                "current_title": "Starting downloads...",
                "playlist_title": playlist_info.get('title', 'Unknown Playlist')
            }
            
            successful_downloads = 0
            failed_downloads = 0
            
            for i, video in enumerate(videos):
                video_url = f"https://www.youtube.com/watch?v={video['id']}"
                video_title = video.get('title', 'Unknown Title')
                
                # Update current video info
                download_status[task_id].update({
                    "current_video": i + 1,
                    "current_title": video_title,
                    "progress": int(10 + (i / total_videos) * 85)
                })
                
                try:
                    # Check if already downloaded
                    if downloader.is_already_downloaded(video['id']):
                        print(f"Skipping already downloaded: {video_title}")
                        successful_downloads += 1
                        continue
                    
                    success = downloader.download_single_video(video_url, format_type, quality)
                    if success:
                        successful_downloads += 1
                    else:
                        failed_downloads += 1
                        
                except Exception as video_error:
                    print(f"Failed to download video {video_url}: {video_error}")
                    failed_downloads += 1
                
                # Update progress
                download_status[task_id].update({
                    "successful_downloads": successful_downloads,
                    "failed_downloads": failed_downloads
                })
            
            download_status[task_id] = {
                "status": "completed",
                "progress": 100,
                "total_videos": total_videos,
                "successful_downloads": successful_downloads,
                "failed_downloads": failed_downloads,
                "playlist_title": playlist_info.get('title', 'Unknown Playlist'),
                "summary": f"Downloaded {successful_downloads}/{total_videos} videos successfully"
            }
            
        except Exception as e:
            download_status[task_id] = {"status": "failed", "error": str(e)}
    
    # Start playlist download in background
    thread = threading.Thread(target=playlist_download_task)
    thread.daemon = True
    thread.start()
    
    return jsonify({
        "message": "Playlist download started",
        "task_id": task_id,
        "status_url": f"/download-status/{task_id}",
        "max_videos": max_videos
    })

@app.route('/schedule', methods=['POST'])
def schedule_download():
    """Schedule a download for later"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON data required"}), 400
    
    url = data.get('url')
    schedule_time = data.get('schedule_time')  # ISO format
    format_type = data.get('format_type', 'mp4')
    quality = data.get('quality', 'best')
    
    if not url or not schedule_time:
        return jsonify({"error": "URL and schedule_time are required"}), 400
    
    if not downloader.is_youtube_url(url):
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    try:
        # Validate schedule time
        scheduled_dt = dt.fromisoformat(schedule_time.replace('Z', '+00:00'))
        if scheduled_dt <= dt.now():
            return jsonify({"error": "Schedule time must be in the future"}), 400
        
        # Get video info for validation
        video_info = downloader.get_video_info(url)
        if 'error' in video_info:
            return jsonify({"error": f"Cannot get video info: {video_info['error']}"}), 400
        
        # Add to queue with scheduled status
        queue_item = {
            'url': url,
            'format_type': format_type,
            'quality': quality,
            'scheduled_time': scheduled_dt.isoformat(),
            'status': 'scheduled',
            'added_date': dt.now().isoformat(),
            'video_info': {
                'title': video_info.get('title'),
                'uploader': video_info.get('author'),
                'duration': video_info.get('duration')
            }
        }
        
        downloader.download_queue.append(queue_item)
        downloader.save_queue()
        
        return jsonify({
            "message": "Download scheduled successfully",
            "scheduled_time": scheduled_dt.isoformat(),
            "video_info": queue_item['video_info']
        })
        
    except ValueError as e:
        return jsonify({"error": f"Invalid schedule time format: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/schedule/process', methods=['POST'])
def process_scheduled():
    """Process scheduled downloads that are due"""
    try:
        now = dt.now()
        processed = 0
        
        for item in downloader.download_queue:
            if item['status'] == 'scheduled':
                scheduled_time = dt.fromisoformat(item['scheduled_time'])
                if now >= scheduled_time:
                    print(f"Processing scheduled download: {item['url']}")
                    try:
                        success = downloader.download_single_video(
                            item['url'], 
                            item['format_type'], 
                            item['quality']
                        )
                        item['status'] = 'completed' if success else 'failed'
                        item['processed_date'] = now.isoformat()
                        processed += 1
                    except Exception as e:
                        item['status'] = 'failed'
                        item['error'] = str(e)
                        processed += 1
        
        if processed > 0:
            downloader.save_queue()
        
        return jsonify({
            "message": f"Processed {processed} scheduled downloads",
            "processed_count": processed
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Enhanced cleanup and utility endpoints

@app.route('/cleanup/duplicates', methods=['POST'])
def remove_duplicates():
    """Remove duplicate downloads from database"""
    try:
        conn = sqlite3.connect(downloader.db_path)
        cursor = conn.cursor()
        
        # Find and remove duplicates by video_id, keeping the most recent
        cursor.execute('''
            DELETE FROM downloads 
            WHERE id NOT IN (
                SELECT MAX(id) 
                FROM downloads 
                GROUP BY video_id
            )
        ''')
        
        removed_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        return jsonify({
            "message": f"Removed {removed_count} duplicate records",
            "removed_count": removed_count
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/cleanup/broken-links', methods=['POST'])
def clean_broken_links():
    """Remove database entries for missing files"""
    try:
        conn = sqlite3.connect(downloader.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, file_path, thumbnail_path, subtitle_path FROM downloads WHERE file_path IS NOT NULL")
        all_downloads = cursor.fetchall()
        
        removed_count = 0
        orphaned_files = []
        
        for download_id, file_path, thumbnail_path, subtitle_path in all_downloads:
            if not os.path.exists(file_path):
                cursor.execute("DELETE FROM downloads WHERE id = ?", (download_id,))
                removed_count += 1
                
                # Check for orphaned thumbnail/subtitle files
                for aux_path in [thumbnail_path, subtitle_path]:
                    if aux_path and os.path.exists(aux_path):
                        orphaned_files.append(aux_path)
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "message": f"Removed {removed_count} broken links",
            "removed_count": removed_count,
            "orphaned_files": orphaned_files
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/cleanup/old-files', methods=['POST'])
def cleanup_old_files():
    """Remove files older than specified days"""
    try:
        data = request.get_json() or {}
        max_age_days = data.get('max_age_days', 30)
        
        if max_age_days <= 0:
            return jsonify({"error": "max_age_days must be positive"}), 400
        
        removed_files = []
        removed_size = 0
        
        cutoff_time = time.time() - (max_age_days * 24 * 3600)
        
        for root, dirs, files in os.walk(downloader.downloads_path):
            for file in files:
                file_path = os.path.join(root, file)
                if os.path.getctime(file_path) < cutoff_time:
                    file_size = os.path.getsize(file_path)
                    os.remove(file_path)
                    removed_files.append(file)
                    removed_size += file_size
        
        return jsonify({
            "message": f"Removed {len(removed_files)} old files",
            "removed_files_count": len(removed_files),
            "removed_size_mb": round(removed_size / (1024*1024), 2),
            "max_age_days": max_age_days
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/compress', methods=['POST'])
def compress_files():
    """Compress old video files to save space"""
    if not downloader.check_ffmpeg():
        return jsonify({"error": "FFmpeg is required for compression"}), 400
    
    try:
        data = request.get_json() or {}
        days_old = data.get('days_old', 30)
        crf_value = data.get('crf', 28)  # Compression level (18-28)
        dry_run = data.get('dry_run', False)
        
        if days_old <= 0:
            return jsonify({"error": "days_old must be positive"}), 400
        
        cutoff_date = dt.now() - timedelta(days=days_old)
        total_space_saved = 0
        processed_files = []
        
        conn = sqlite3.connect(downloader.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT file_path, video_id FROM downloads WHERE format_type = 'mp4'")
        
        for file_path, video_id in cursor.fetchall():
            if not os.path.exists(file_path):
                continue
                
            file_mtime = dt.fromtimestamp(os.path.getmtime(file_path))
            if file_mtime < cutoff_date:
                original_size = os.path.getsize(file_path)
                
                if dry_run:
                    processed_files.append({
                        "file": os.path.basename(file_path),
                        "original_size_mb": round(original_size / (1024*1024), 2),
                        "age_days": (dt.now() - file_mtime).days
                    })
                    continue
                
                compressed_path = file_path + ".compressed.mp4"
                cmd = [
                    'ffmpeg', '-i', file_path,
                    '-vcodec', 'libx264', '-crf', str(crf_value),
                    '-preset', 'fast', '-y', compressed_path
                ]
                
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.returncode == 0 and os.path.exists(compressed_path):
                        compressed_size = os.path.getsize(compressed_path)
                        if compressed_size < original_size:
                            space_saved = original_size - compressed_size
                            total_space_saved += space_saved
                            
                            # Replace original with compressed
                            os.remove(file_path)
                            shutil.move(compressed_path, file_path)
                            
                            # Update database
                            cursor.execute("UPDATE downloads SET file_size = ? WHERE video_id = ?", 
                                          (compressed_size, video_id))
                            
                            processed_files.append({
                                "file": os.path.basename(file_path),
                                "original_size_mb": round(original_size / (1024*1024), 2),
                                "compressed_size_mb": round(compressed_size / (1024*1024), 2),
                                "space_saved_mb": round(space_saved / (1024*1024), 2)
                            })
                        else:
                            os.remove(compressed_path)
                    else:
                        if os.path.exists(compressed_path):
                            os.remove(compressed_path)
                        print(f"Compression failed for {file_path}")
                        
                except Exception as e:
                    print(f"Error compressing {file_path}: {e}")
                    if os.path.exists(compressed_path):
                        os.remove(compressed_path)
        
        if not dry_run:
            conn.commit()
        conn.close()
        
        return jsonify({
            "message": f"{'Would process' if dry_run else 'Processed'} {len(processed_files)} files",
            "total_space_saved_mb": round(total_space_saved / (1024*1024), 2),
            "processed_files": processed_files,
            "dry_run": dry_run,
            "settings": {
                "days_old": days_old,
                "crf_value": crf_value
            }
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    """Handle unexpected exceptions"""
    return jsonify({
        "error": "An unexpected error occurred",
        "details": str(e) if app.debug else "Enable debug mode for details"
    }), 500

# Background tasks and cleanup

def cleanup_download_status():
    """Clean up old download status entries"""
    while True:
        try:
            current_time = time.time()
            with download_lock:
                # Remove status entries that are not actively downloading and are older than a reasonable time
                keys_to_remove = [
                    key for key, status in download_status.items()
                    if status.get('status') in ['completed', 'failed', 'not_found']
                ]
                for key in keys_to_remove:
                    del download_status[key]
                
        except Exception as e:
            print(f"Error in cleanup: {e}")
        
        time.sleep(300)  # Run every 5 minutes

def process_scheduled_downloads():
    """Background task to process scheduled downloads"""
    while True:
        try:
            # Send a request to the /schedule/process endpoint
            requests.post('http://localhost:5000/schedule/process')
        except requests.exceptions.ConnectionError:
            print("Server not running, cannot process scheduled downloads.")
        except Exception as e:
            print(f"Error in background scheduled task: {e}")
        time.sleep(60)  # Check every minute

if __name__ == '__main__':
    # Ensure required directories exist
    os.makedirs(downloader.downloads_path, exist_ok=True)
    
    # Start background threads
    cleanup_thread = threading.Thread(target=cleanup_download_status)
    cleanup_thread.daemon = True
    cleanup_thread.start()
    
    # Start scheduled downloads processor
    schedule_thread = threading.Thread(target=process_scheduled_downloads)
    schedule_thread.daemon = True
    schedule_thread.start()
    
    print("🚀 Starting Enhanced YouTube Downloader Flask API v2.0...")
    print("🌐 Frontend available at: http://localhost:5000/")
    print("📖 API Documentation available at: http://localhost:5000/")
    print("🔧 Make sure you have the following dependencies installed:")
    print("   pip install flask flask-cors yt-dlp")
    print("💡 Make sure your youtube4.py file is in the same directory")
    print("⚡ Enhanced features: Better search, scheduling, compression, improved error handling")
    print("🎬 Starting server...")
    
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)