# TODO — YouTube Downloader Fixes

This TODO tracks the work to fix and harden the YouTube Downloader feature (Ambil Info and Download).

## Plan (Approved)
- Frontend
  - Stop forcing `itag` to `Number` before POST. Allow string/number `itag` so non-numeric or yt-dlp-only formats are supported.
  - Keep existing UX for status/error parsing.

- Backend
  - Improve yt-dlp error handling:
    - Catch `subprocess.CalledProcessError` in `_ytdlp_json` and raise a clear exception with combined stderr/stdout.
  - Return 400 (Bad Request) with human-readable error when info/download fails after fallback attempts, instead of 500.
  - Add descriptive logging for traceability.

- Tests / Manual QA
  - Ambil Info with:
    - watch URL: https://www.youtube.com/watch?v=<id>
    - short URL: https://youtu.be/<id>
    - encoded URL: url=...v%3D<id>
  - Download:
    - Progressive video (e.g., 360p/720p)
    - Video-only 1080p merged to MP4 on backend
    - Audio (m4a/mp3) with and without ffmpeg present

## Checklist
- [ ] Frontend: send `itag` as-is (string or number)
- [ ] Backend: `_ytdlp_json` robust exception handling
- [ ] Backend: `/api/ytdl/info` return 400 with clear error on failure
- [ ] Backend: `/api/ytdl/download` return 400 with clear error on failure
- [ ] Logging: improved messages for failures and fallbacks
- [ ] Manual tests for 3 URL forms and 3 download modes
- [ ] Verify that the browser console no longer shows 500 for info failures
