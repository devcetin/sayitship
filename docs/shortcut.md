# iPhone Shortcuts

sayitship has no app. Three small Shortcuts send requests to your server. Replace
`<server>` with your PC's Tailscale address and port (for example `http://100.x.y.z:8787`)
and `<token>` with `SAYITSHIP_TOKEN` from your `.env`.

Use `http://`, not `https://`. The traffic is already encrypted by Tailscale, and the server
does not speak TLS, so an `https://` URL fails with a TLS error.

## 1. sayitship (voice only, for the Action Button)

1. **Dictate Text**: language = yours, Stop Listening = After Pause.
2. **Get Contents of URL**
   - URL: `<server>/task` (typed as plain text, not a variable)
   - Method: `POST`
   - Headers: `Authorization` = `Bearer <token>`
   - Request Body: `JSON`, field `text` (Text) = the **Dictated Text** variable
3. *(optional)* **Show Notification**: `Sent`

Assign it in **Settings → Action Button → Shortcut → sayitship**.

## 2. sayitship+ (voice + clipboard + latest screenshot)

Same as above, with two extra steps before **Get Contents of URL**:

1. **Dictate Text**
2. **Get Clipboard**
3. **Get Latest Screenshots** (count: 1) → **Base64 Encode** (Line Breaks: None)
4. **Get Contents of URL**, Request Body `JSON` with three fields:
   - `text` = Dictated Text
   - `clipboard` = Clipboard
   - `image` = Base64 Encoded

Send this one only when you mean it: the clipboard and the screenshot leave the phone.
Good triggers: Back Tap (Settings → Accessibility → Touch → Back Tap) or a home-screen icon.

## 3. sayitship link (from the Share Sheet)

1. In the Shortcut's details, turn on **Show in Share Sheet** and accept **URLs**.
2. **Dictate Text**
3. **Get Contents of URL**, Request Body `JSON`:
   - `text` = Dictated Text
   - `url` = **Shortcut Input**

In Safari: Share → sayitship link → say what to do with the page.

## Fields the server accepts

| field | meaning |
|---|---|
| `text` | the request, required |
| `clipboard` | text from the clipboard |
| `url` | a shared link |
| `image` | a PNG/JPEG/GIF/WebP image, base64, up to 10 MB |
| `project` | skip the router's project choice and use this project name |
