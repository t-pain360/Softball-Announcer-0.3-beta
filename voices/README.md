# NeuTTS Air voice references

This directory is intentionally empty of real voice recordings. Add only recordings you own or have permission to use.

Create these pairs to enable the four personas:

- `classic.wav` + `classic.txt`
- `hype.wav` + `hype.txt`
- `radio.wav` + `radio.txt`
- `velvet.wav` + `velvet.txt`

NeuTTS Air uses a WAV reference plus its exact transcript to clone the reference voice. Short, clean, continuous speech works best. The upstream project recommends mono WAV, 16–44 kHz, roughly 3–15 seconds, with little background noise.

The application will fall back to browser SpeechSynthesis if a reference pair is missing or NeuTTS Air is unavailable.

Do not commit private recordings or voices you do not have permission to clone.
