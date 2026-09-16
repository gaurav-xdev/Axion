# VIDEO WORKER POLICY

## PURPOSE
To inspect, trim, transcode, normalize audio, overlay captions, and package media assets using FFmpeg and ffprobe.

## VERIFICATION REQUIREMENT
- Never mark a media render as complete until the generated video has been probed using `ffprobe`.
- Verify duration, resolution, stream integrity, audio tracks, and file readability before handing over to QA.
