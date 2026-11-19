# iPhone Shortcuts

sayitship has no app. Three small Shortcuts send requests to your server. Replace
`<server>` with your PC's Tailscale address and port (for example `http://100.x.y.z:8787`)
and `<token>` with `SAYITSHIP_TOKEN` from your `.env`.

Use `http://`, not `https://`. The traffic is already encrypted by Tailscale, and the server
does not speak TLS, so an `https://` URL fails with a TLS error.

## 1. sayitship (voice, for the Action Button)

Recommended: send the recording itself. Apple's dictation turns English technical words in a
Turkish sentence into nonsense ("Bash ile pip list" became "Beş ile Bitlis"). The server lets
Gemini transcribe the audio instead, with your project names and a developer vocabulary in the
prompt, in the same call that routes the request. Needs `GEMINI_API_KEY` on the server.

1. **Record Audio**
   - Audio Quality: Normal
   - Start Recording: Immediately
   - Finish Recording: On Tap (or After Time, e.g. 15 s)
2. **Base64 Encode** (input: Recorded Audio, Line Breaks: None)
3. **Get Contents of URL**
   - URL: `<server>/task` (typed as plain text, not a variable)
   - Method: `POST`
   - Headers: `Authorization` = `Bearer <token>`
   - Request Body: `JSON`, field `audio` (Text) = the **Base64 Encoded** variable
4. *(optional)* **Show Notification**: `Sent`

Assign it in **Settings → Action Button → Shortcut → sayitship**.

### Dictation variant

If you prefer Apple's dictation (it stops by itself when you pause), replace steps 1–2 with
**Dictate Text** and send field `text` = **Dictated Text** instead of `audio`. The router then
tries to repair misheard technical words from the text alone, which works less well.

## 2. sayitship+ (voice + clipboard + latest screenshot)

Same as above, with two extra steps before **Get Contents of URL**:

1. **Record Audio** → **Base64 Encode** (as in shortcut 1)
2. **Get Clipboard**
3. **Get Latest Screenshots** (count: 1) → **Base64 Encode** (Line Breaks: None)
4. **Get Contents of URL**, Request Body `JSON` with three fields:
   - `audio` = the first Base64 Encoded
   - `clipboard` = Clipboard
   - `image` = the second Base64 Encoded

Send this one only when you mean it: the clipboard and the screenshot leave the phone.
Good triggers: Back Tap (Settings → Accessibility → Touch → Back Tap) or a home-screen icon.

## 3. sayitship link (from the Share Sheet)

1. In the Shortcut's details, turn on **Show in Share Sheet** and accept **URLs**.
2. **Record Audio** → **Base64 Encode**
3. **Get Contents of URL**, Request Body `JSON`:
   - `audio` = Base64 Encoded
   - `url` = **Shortcut Input**

In Safari: Share → sayitship link → say what to do with the page.

## Fields the server accepts

| field | meaning |
|---|---|
| `text` | the request as text (dictation); `text` or `audio` is required |
| `audio` | a voice recording, base64 (m4a, wav, mp3, aac, ogg, flac), up to 10 MB |
| `clipboard` | text from the clipboard |
| `url` | a shared link |
| `image` | a PNG/JPEG/GIF/WebP image, base64, up to 10 MB |
| `project` | skip the router's project choice and use this project name |
