# AutoShorts Engine

A beginner-friendly Python project that creates a vertical short video automatically:

1. Takes a topic from the user
2. Uses Google Gemini to create a short script and visual keywords
3. Uses Edge TTS to generate narration
4. Downloads matching portrait videos from Pexels
5. Joins clips, adds narration and subtitles
6. Exports a 1080x1920 MP4 video

## Recommended Python

Use Python 3.11.

## Windows Setup

Open Command Prompt in the project folder:

```bat
py -3.11 -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Copy `.env.example` and rename the copy to `.env`.

Add your keys:

```env
GEMINI_API_KEY=your_real_key
PEXELS_API_KEY=your_real_key
```

Run:

```bat
python make_video.py
```

The generated video will appear in the `output` folder.

## Notes

- Keep API keys private.
- Do not upload `.env` to GitHub.
- Pexels results depend on the topic.
- Subtitle timings are estimated from word count, which is suitable for this beginner MVP.
