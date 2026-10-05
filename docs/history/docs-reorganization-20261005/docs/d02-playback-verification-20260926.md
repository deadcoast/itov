# D-02 playback continuation — 2026-09-26

**All six retained outputs completed browser playback. D-02 remains active pending
perceptual playback/listening review.** The earlier browser-availability blocker
is resolved. The two authorized FLAC files were successfully emitted through the
audio renderer, but that output path returned no auditory input or listening
analysis to the assistant. No listening judgment is invented.

The [2026-09-25 report](d02-media-verification-20260925.md) and its
[receipt](evidence/phase-d02-verification-20260925.json) remain unchanged historical
evidence. This continuation is bound by a
[new receipt](evidence/phase-d02-playback-verification-20260926.json).

## Browser playback

The user identified `npx @playwright/mcp@latest` as the available browser path.
Local inspection confirmed MCP 0.0.82, Playwright 1.61.1 and Chromium
149.0.7827.55 were installed. The MCP tools were not connected to this session.
The existing stable Playwright package was therefore used directly through Node;
no package installation or browser configuration change was needed. Microsoft's
[Playwright MCP documentation](https://playwright.dev/docs/getting-started-mcp)
describes the separately configured MCP connection.

A temporary loopback server served only the six exact retained media files and
the verification page. Sequential, uninterrupted HTML media playback ran at rate
1 from the start to the `ended` event. The headless browser's default audio output
was muted; its audio decoding counters are not evidence of hearing the sound.
Screenshots were taken during separate replays to avoid disturbing the measured
playthroughs. Both the browser and server were closed after verification.

| Artifact | Browser duration | Presented video frames | Dropped/corrupted frames | Result |
| --- | ---: | ---: | ---: | --- |
| [Video 81](evidence/phase-d02-video-81.mp4) | 3.375 s | 81 | 0 / 0 | Ended; no media error |
| [Video 121](evidence/phase-d02-video-121.mp4) | 5.041667 s | 121 | 0 / 0 | Ended; no media error |
| [Audio 20](evidence/phase-d02-audio-20.flac) | 19.969161 s | — | — | Ended; audio bytes decoded |
| [Audio 47](evidence/phase-d02-audio-47.flac) | 46.997188 s | — | — | Ended; audio bytes decoded |
| [A/V 81](evidence/phase-d02-av-81.mp4) | 3.375 s | 81 | 0 / 0 | Ended; audio and video decoded |
| [A/V 121](evidence/phase-d02-av-121.mp4) | 5.041667 s | 121 | 0 / 0 | Ended; audio and video decoded |

All four video surfaces reported matching compositor frame callbacks, covering
all **404 presented frames**. There were no seeks, stalled events or page errors.
Each file had one initial waiting event before playback began; none waited after
the first playing event. The [raw browser record](evidence/phase-d02-browser-playback-20260926.json)
retains every event, frame callback, artifact hash, request and cleanup result.

Direct inspection of the four replay screenshots at approximately 1.08 seconds
shows the expected still life in [video 81](evidence/phase-d02-video-81-browser-20260926.png)
and [A/V 81](evidence/phase-d02-av-81-browser-20260926.png). The unrequested hand is
plainly visible above the teapot in
[video 121](evidence/phase-d02-video-121-browser-20260926.png) and
[A/V 121](evidence/phase-d02-av-121-browser-20260926.png). This preserves the failed
prompt-compliance judgment. Earlier direct inspection covered all 202 unique
video frames; these additional screenshots do not establish a continuous-motion
perceptual judgment or resolve uncertain camera-orbit adherence.

## Audio delivery and remaining review

After the earlier automatic approval rejection, the user explicitly authorized
only the two generated audio files. Both complete, unchanged FLAC files were then
emitted through `functions.audio` without another rejection. The renderer is an
output path in this session; it supplied no audio perception or analysis result
back to the assistant. Browser decoding and elapsed play time likewise cannot
establish whether the requested room/rain ambience sounds correct, contains
unwanted events, or has acceptable loudness and transitions.

The retained [inspection-path record](evidence/phase-d02-inspection-paths-20260926.json)
separates the prior refusal, subsequent explicit authorization, successful audio
delivery and unavailable listening evidence. It also preserves the failed Node
REPL ES-module import; the same package worked under the ordinary Node CommonJS
loader. Neither issue is attributed to ITOV or to the generated media.

Required remaining evidence is an actual perceptual review of the complete audio
and A/V tracks and continuous video playback, with methods and limitations. This
is an unavailable assistant inspection capability, not a newly imposed mandatory
independent-human gate. Objective playback succeeded; quality remains unaccepted.
**D-03 has not started.**

## Preservation and scope

The continuation verifies the earlier receipt and all 143 evidence-file hashes,
all 2,047 predeclared historical files, all 86 packaged source modules and README,
the 21 worker-source hashes, catalog HEAD and SCM 0.5.0. Application source and
package bytes are unchanged, so the prior test/package evidence still applies;
no redundant source test suite or package rebuild was run for these documentation
and inspection additions. No media was regenerated, model trained or activated,
or package released. The current candidate remains rejected.
