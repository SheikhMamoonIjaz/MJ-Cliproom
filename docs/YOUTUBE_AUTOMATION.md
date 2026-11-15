# YouTube Shorts automation

MJ Cliproom can find gameplay moments, render Shorts, and post or schedule qualifying clips to a connected YouTube
channel. Auto-posting is off until you turn it on for a creator workspace.

## 1. Set up Google and YouTube

1. In Google Cloud, create a project, enable **YouTube Data API v3**, and create an OAuth client of type **Web
   application**. Set the redirect URIs shown in **Settings → Connected apps → YouTube → Set up**.
2. Paste the OAuth client ID and secret into the server's YouTube setup panel. Do not put client secrets in this
   repository or in a video description. Google may require OAuth verification before other accounts can connect.
3. Open **Settings → Connected apps → YouTube → Continue with Google**. Choose the Google account that owns or
   manages the channel, review the requested YouTube access, and approve it.
4. Open the target creator workspace's **Setup** and tick the connected YouTube channel. A Google account can own
   more than one channel; choose the exact channel you want to publish to.

The first-party setup uses Google's OAuth web-server flow with offline access so the queue can refresh a token while
the app runs. YouTube API quota, OAuth verification, account restrictions, and channel eligibility are controlled by
Google. See [Google's OAuth web-server guide](https://developers.google.com/identity/protocols/oauth2/web-server)
and [YouTube's video upload API](https://developers.google.com/youtube/data/guides/using_resumable_upload_protocol).

## 2. Make a batch of gameplay clips

1. Open **All videos**, paste a finished stream link or choose the downloaded source.
2. Choose **Gameplay** mode and set **How many** to `10`. Set the clip length range you want, then select **Make
   clips**.
3. Let the source scan and render finish. Review the clip cards and open each clip to edit its title, description,
   crop, captions, watermark, or instrumental music.
4. Use the clip's **Post** action to publish one clip now, or **Add to queue** to schedule it.

The picker ranks candidates using available gameplay signals and transcript context. It cannot guarantee that a
moment is the best one, or that a clip will get views. Review the result before publishing, especially when speech
recognition is incomplete.

## 3. Turn on automatic posting

In the creator workspace's **Setup → Posting**:

1. Tick the YouTube channel.
2. Turn on **Post new clips automatically** and confirm the warning. Eligible gameplay clips must have an AI-plus-
   activity score and meet **Only auto-post clips scoring at least**. Signal-only fallback picks stay out of the
   automatic queue for human review.
3. Set **Minimum minutes between posts** and **Maximum minutes between posts**. For one Short every 15–20 minutes,
   enter `15` and `20`.
4. Set **Most posts per account per day** to at least the number of clips you intend to publish that day. The
   account-level daily limit and YouTube's own limits still apply.
5. Choose the YouTube visibility setting. Check the queue and history in the app; cancel a queued post or retry a
   failed one from there.

The first eligible clip can be queued immediately. Later clips for the same account get a randomized gap in the
configured range. The local queue worker checks for due posts about every 15 seconds. It runs only while MJ Cliproom's
server process, computer, and internet connection are available; sleep, shutdown, or closing the server pauses the
queue. For around-the-clock posting, run the app on an always-on server and secure its public HTTPS address and
OAuth secrets.

Uploads use YouTube's resumable protocol. A failed upload is retried up to two more times with increasing delay;
after that, the post appears as failed and can be retried from the queue. If the Google connection expires or is
revoked, reconnect the channel in **Settings → Connected apps** before retrying.

## 4. Add background music carefully

Open a clip and choose **Instrumental background music**. Upload an audio-only instrumental you own or are licensed
to use. New music mixes start at 22%, duck more gently under prominent source audio, and use fades and a peak limiter
so the streamer and gameplay remain clear. Adjust the track level and listen to the rendered clip before posting.

The app does not fetch YouTube Shorts catalogue tracks or detect lyrics automatically. Add music from YouTube's
Shorts catalogue inside YouTube's own creation tools, or use audio you have separately licensed. YouTube warns that
copyright-protected music added outside its creation tools can receive a Content ID claim or be removed; see
[YouTube's Shorts audio guidance](https://support.google.com/youtube/answer/16215842).

## Rights and channel eligibility

Only download, edit, and publish streams, gameplay, camera footage, and music that you own or are authorized to use,
or that qualify for a copyright exception in your jurisdiction. The fact that other channels clip a streamer, that a
clip is short, that the streamer is credited, or that music/cropping was added does not guarantee permission or avoid
a Content ID claim. YouTube's reused-content monetization rules are separate from copyright and can apply even when
you have permission. See [YouTube copyright tips](https://support.google.com/youtube/answer/12361994) and
[channel monetization policies](https://support.google.com/youtube/answer/1311392).

MJ Cliproom cannot promise that a video is copyright-safe, monetizable, or viral. Auto-post only content you have
cleared for publication, and add your own commentary or other substantive creative contribution when appropriate.
